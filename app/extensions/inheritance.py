import json
from dataclasses import dataclass
from typing import Any, Literal, cast

from sqlalchemy.orm import Session

from app import store
from app.config import Config
from app.extensions.base import (
    EXTENSIBLE_TARGETS,
    Extension,
    TargetType,
    capabilities_for_target,
    sanitize_bool,
)
from app.models import Project
from app.plugins.base import InvalidContent
from app.surface import Capability

SITE_EXTENSIONS_KEY = "site_extensions"
SITE_SOURCE_TITLE = "全站默认"

ExtensionMode = Literal["inherit", "override", "disabled"]
SourceKind = Literal["site", "ancestor", "local", "none"]
VALID_MODES: frozenset[str] = frozenset({"inherit", "override", "disabled"})


@dataclass(frozen=True)
class LayerState:
    mode: ExtensionMode
    cascade: bool
    config: dict[str, Any]


@dataclass(frozen=True)
class ResolvedExtension:
    extension: Extension
    effective_enabled: bool
    effective_config: dict[str, Any]
    raw_merged_config: dict[str, Any]
    source: SourceKind
    source_slug: str
    source_title: str
    local_mode: ExtensionMode
    cascade: bool
    inherited_enabled: bool
    inherited_source: SourceKind
    inherited_source_title: str
    inherited_config: dict[str, Any]
    local_config: dict[str, Any]
    secrets_set: dict[str, bool]
    secret_inherited: dict[str, bool]
    local_secrets_set: dict[str, bool]


def parse_layer_state(
    raw_state: object,
    *,
    is_site: bool = False,
    strict: bool = False,
) -> LayerState:
    default_cascade = bool(is_site)
    if raw_state is None:
        return LayerState(mode="inherit", cascade=default_cascade, config={})
    if not isinstance(raw_state, dict):
        if strict:
            raise InvalidContent("插件状态格式不正确")
        return LayerState(mode="inherit", cascade=default_cascade, config={})

    raw_cfg = raw_state.get("config")
    cfg = dict(raw_cfg) if isinstance(raw_cfg, dict) else {}

    if "mode" in raw_state:
        raw_mode = raw_state.get("mode")
        if isinstance(raw_mode, str) and raw_mode in VALID_MODES:
            mode = cast(ExtensionMode, raw_mode)
            if mode == "inherit":
                return LayerState(mode="inherit", cascade=default_cascade, config={})
            cascade = sanitize_bool(raw_state.get("cascade"), default_cascade, strict=strict)
            return LayerState(mode=mode, cascade=cascade, config=cfg)
        if strict:
            raise InvalidContent("插件继承模式必须是 inherit、override 或 disabled")
        return LayerState(mode="inherit", cascade=default_cascade, config={})

    installed = sanitize_bool(raw_state.get("installed", True), True, strict=strict)
    if not installed:
        return LayerState(mode="inherit", cascade=default_cascade, config={})
    enabled = sanitize_bool(raw_state.get("enabled", False), False, strict=strict)
    cascade = sanitize_bool(raw_state.get("cascade"), default_cascade, strict=strict)
    mode = "override" if enabled else "disabled"
    return LayerState(mode=mode, cascade=cascade, config=cfg)


def normalize_sparse_config(
    ext: Extension,
    raw: object,
    *,
    strict: bool = False,
    project_slug: str | None = None,
) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        if strict:
            ext.normalize_config(raw, strict=True, project_slug=project_slug)
        return {}
    if not raw:
        return {}
    full = ext.normalize_config(raw, strict=strict, project_slug=project_slug)
    return {key: full[key] for key in raw if key in full}


def merge_layer_config(
    ext: Extension,
    existing: dict[str, Any] | None,
    incoming: dict[str, Any] | None,
    *,
    strict: bool = True,
    project_slug: str | None = None,
) -> dict[str, Any]:
    prev = dict(existing) if isinstance(existing, dict) else {}
    if incoming is None:
        return normalize_sparse_config(ext, prev, strict=False, project_slug=project_slug)
    if not isinstance(incoming, dict):
        if strict:
            ext.normalize_config(incoming, strict=True, project_slug=project_slug)
        return normalize_sparse_config(ext, prev, strict=False, project_slug=project_slug)

    merged_for_val = ext.merge_config(prev, incoming)
    full = ext.normalize_config(merged_for_val, strict=strict, project_slug=project_slug)
    secret_keys = ext.secret_fields()
    keep_keys = (set(prev.keys()) | set(incoming.keys())) & set(full.keys())
    for sk in secret_keys:
        if sanitize_bool(incoming.get(f"clear_{sk}"), False) or (
            sk in keep_keys and not str(full.get(sk, "")).strip()
        ):
            keep_keys.discard(sk)
    return {key: full[key] for key in full if key in keep_keys}


def shallow_merge_config(
    base: dict[str, Any],
    overlay: dict[str, Any],
    *,
    secret_keys: set[str],
) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        if key in secret_keys:
            if isinstance(value, str) and value.strip():
                merged[key] = value.strip()
        else:
            merged[key] = value
    return merged


def load_site_extensions(db: Session) -> dict[str, dict[str, Any]]:
    raw = store.get_site_setting(db, SITE_EXTENSIONS_KEY)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for ext_id, state in parsed.items():
        if isinstance(ext_id, str) and isinstance(state, dict):
            out[ext_id] = dict(state)
    return out


def save_site_extensions(db: Session, data: dict[str, dict[str, Any]]) -> None:
    store.set_site_setting(db, SITE_EXTENSIONS_KEY, json.dumps(data, ensure_ascii=False))


def _project_extensions_map(
    project: Project,
    content_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if content_override is not None:
        raw_ext = content_override.get("extensions")
        return raw_ext if isinstance(raw_ext, dict) else {}
    try:
        parsed = json.loads(project.content or "{}")
    except (TypeError, ValueError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    raw_ext = parsed.get("extensions")
    return raw_ext if isinstance(raw_ext, dict) else {}


def _resolve_single(
    ext: Extension,
    site_map: dict[str, dict[str, Any]],
    ancestor_layers: list[tuple[Project, dict[str, Any]]],
    project: Project,
    local_map: dict[str, Any],
) -> ResolvedExtension:
    secret_keys = ext.secret_fields()
    enabled = False
    merged_raw: dict[str, Any] = {}
    source: SourceKind = "none"
    source_slug = ""
    source_title = ""

    site_state = parse_layer_state(site_map.get(ext.id), is_site=True)
    if site_state.mode == "override" and site_state.cascade:
        enabled = True
        merged_raw = shallow_merge_config({}, site_state.config, secret_keys=secret_keys)
        source = "site"
        source_slug = ""
        source_title = SITE_SOURCE_TITLE

    for ancestor, anc_map in ancestor_layers:
        anc_state = parse_layer_state(anc_map.get(ext.id), is_site=False)
        if not anc_state.cascade or anc_state.mode == "inherit":
            continue
        if anc_state.mode == "override":
            enabled = True
            merged_raw = shallow_merge_config(merged_raw, anc_state.config, secret_keys=secret_keys)
            source = "ancestor"
            source_slug = ancestor.slug
            source_title = ancestor.title
        elif anc_state.mode == "disabled":
            enabled = False
            merged_raw = {}
            source = "none"
            source_slug = ""
            source_title = ""

    inherited_enabled = enabled
    inherited_source = source
    inherited_source_title = source_title
    inherited_raw = dict(merged_raw)
    inherited_config = ext.normalize_config(inherited_raw or None, strict=False, project_slug=None)

    local_state = parse_layer_state(local_map.get(ext.id), is_site=False)
    local_mode = local_state.mode
    local_cascade = local_state.cascade
    local_config = dict(local_state.config)

    if local_mode == "override":
        effective_enabled = True
        raw_merged = shallow_merge_config(inherited_raw, local_config, secret_keys=secret_keys)
        eff_source: SourceKind = "local"
        eff_source_slug = project.slug
        eff_source_title = project.title
    elif local_mode == "disabled":
        effective_enabled = False
        raw_merged = shallow_merge_config(inherited_raw, local_config, secret_keys=secret_keys)
        eff_source = "local"
        eff_source_slug = project.slug
        eff_source_title = project.title
    else:
        effective_enabled = inherited_enabled
        raw_merged = dict(inherited_raw)
        eff_source = inherited_source
        eff_source_slug = source_slug
        eff_source_title = inherited_source_title

    effective_config = ext.normalize_config(raw_merged or None, strict=False, project_slug=None)

    secrets_set: dict[str, bool] = {}
    local_secrets_set: dict[str, bool] = {}
    secret_inherited: dict[str, bool] = {}
    for key in sorted(secret_keys):
        has_effective = bool(
            isinstance(effective_config.get(key), str) and str(effective_config.get(key)).strip()
        )
        has_local = bool(
            local_mode != "inherit"
            and isinstance(local_config.get(key), str)
            and str(local_config.get(key)).strip()
        )
        secrets_set[key] = has_effective
        local_secrets_set[key] = has_local
        secret_inherited[key] = has_effective and not has_local

    return ResolvedExtension(
        extension=ext,
        effective_enabled=effective_enabled,
        effective_config=effective_config,
        raw_merged_config=raw_merged,
        source=eff_source,
        source_slug=eff_source_slug,
        source_title=eff_source_title,
        local_mode=local_mode,
        cascade=local_cascade,
        inherited_enabled=inherited_enabled,
        inherited_source=inherited_source,
        inherited_source_title=inherited_source_title,
        inherited_config=inherited_config,
        local_config=local_config,
        secrets_set=secrets_set,
        secret_inherited=secret_inherited,
        local_secrets_set=local_secrets_set,
    )


def _project_capabilities(project: Project) -> frozenset[Capability] | None:
    from app.plugins import registry as plugins_registry

    plugin = plugins_registry.get(project.type)
    if plugin is not None:
        caps = getattr(plugin, "capabilities", None)
        if isinstance(caps, frozenset):
            return caps
    if project.type in EXTENSIBLE_TARGETS:
        return capabilities_for_target(cast(TargetType, project.type))
    return None


def resolve_project_extensions(
    db: Session,
    project: Project,
    *,
    target: TargetType | None = None,
    capabilities: frozenset[Capability] | None = None,
    config: Config | None = None,
    content: dict[str, Any] | None = None,
) -> dict[str, ResolvedExtension]:
    from app.extensions.registry import all_extensions

    resolved_caps = capabilities
    resolved_target: TargetType | None = target
    if resolved_caps is None and resolved_target is None:
        resolved_caps = _project_capabilities(project)
        if resolved_caps is None:
            return {}

    site_map = load_site_extensions(db)
    ancestor_chain = list(reversed(store.ancestors(db, project)))
    ancestor_layers = [(anc, _project_extensions_map(anc)) for anc in ancestor_chain]
    local_map = _project_extensions_map(project, content_override=content)

    resolved: dict[str, ResolvedExtension] = {}
    for ext in all_extensions(target=resolved_target, capabilities=resolved_caps, config=config):
        resolved[ext.id] = _resolve_single(ext, site_map, ancestor_layers, project, local_map)
    return resolved


def resolve_project_extension(
    db: Session,
    project: Project,
    ext_id: str,
    *,
    target: TargetType | None = None,
    capabilities: frozenset[Capability] | None = None,
    config: Config | None = None,
    content: dict[str, Any] | None = None,
) -> ResolvedExtension | None:
    from app.extensions.registry import _matches_scope
    from app.extensions.registry import get as get_extension

    ext = get_extension(ext_id, config=config)
    if ext is None:
        return None
    resolved_caps = capabilities
    resolved_target: TargetType | None = target
    if resolved_caps is None and resolved_target is None:
        resolved_caps = _project_capabilities(project)
        if resolved_caps is None:
            return None
    if not _matches_scope(ext, target=resolved_target, capabilities=resolved_caps):
        return None

    site_map = load_site_extensions(db)
    ancestor_chain = list(reversed(store.ancestors(db, project)))
    ancestor_layers = [(anc, _project_extensions_map(anc)) for anc in ancestor_chain]
    local_map = _project_extensions_map(project, content_override=content)
    return _resolve_single(ext, site_map, ancestor_layers, project, local_map)
