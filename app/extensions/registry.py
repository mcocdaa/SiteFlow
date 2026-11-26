import re
from typing import Any

from markupsafe import Markup
from sqlalchemy.orm import Session

from app.config import Config
from app.extensions.base import (
    EXT_ID_RE,
    LAYOUT_MODE_RE,
    STRUCTURED_SLOTS,
    Extension,
    PageKind,
    TargetType,
    capabilities_for_target,
    sanitize_bool,
    sanitize_icon_overrides,
    sanitize_theme_tokens,
)
from app.extensions.inheritance import (
    SITE_SOURCE_TITLE,
    ResolvedExtension,
    load_site_extensions,
    normalize_sparse_config,
    parse_layer_state,
    resolve_project_extensions,
)
from app.extensions.mascot import MascotExtension
from app.extensions.packs import PackExtension, load_pack_extensions
from app.extensions.post_background import PostBackgroundExtension
from app.extensions.post_cover import PostCoverExtension
from app.extensions.resume_style import ResumeStyleExtension
from app.extensions.space_background import SpaceBackgroundExtension
from app.extensions.space_banner import SpaceBannerExtension
from app.extensions.space_layout import SpaceLayoutExtension
from app.models import Project
from app.plugins.base import InvalidContent
from app.surface import Capability
from app.templating import static_url

_builtins: dict[str, Extension] = {}
_BODY_BLOG_MEDIA_URL_RE = re.compile(r"/media/blog/[a-z0-9][a-z0-9_-]{0,63}/[a-z0-9][a-z0-9_-]{0,63}\.webp")


def _matches_scope(
    ext: Extension,
    *,
    target: TargetType | None = None,
    capabilities: frozenset[Capability] | None = None,
) -> bool:
    if capabilities is not None:
        return ext.matches_capabilities(capabilities)
    if target is not None:
        return ext.matches_capabilities(capabilities_for_target(target))
    return True


def register(extension: Extension) -> None:
    if not EXT_ID_RE.match(extension.id):
        raise ValueError(f"Invalid extension id: {extension.id}")
    _builtins[extension.id] = extension


def builtin_extensions(
    *,
    target: TargetType | None = None,
    capabilities: frozenset[Capability] | None = None,
) -> list[Extension]:
    if target is None and capabilities is None:
        return list(_builtins.values())
    return [
        ext for ext in _builtins.values() if _matches_scope(ext, target=target, capabilities=capabilities)
    ]


def all_extensions(
    *,
    target: TargetType | None = None,
    capabilities: frozenset[Capability] | None = None,
    config: Config | None = None,
) -> list[Extension]:
    items = builtin_extensions(target=target, capabilities=capabilities)
    if config is not None:
        for ext in load_pack_extensions(config):
            if _matches_scope(ext, target=target, capabilities=capabilities):
                items.append(ext)
    return items


def get(ext_id: str, *, config: Config | None = None) -> Extension | None:
    builtin = _builtins.get(ext_id)
    if builtin is not None:
        return builtin
    if config is not None and "." in ext_id:
        for ext in load_pack_extensions(config):
            if ext.id == ext_id:
                return ext
    return None


def normalize_extensions(
    raw: object,
    *,
    strict: bool = False,
    project_slug: str | None = None,
    target: TargetType | None = None,
    capabilities: frozenset[Capability] | None = None,
    config: Config | None = None,
) -> dict[str, dict[str, Any]]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        if strict:
            raise InvalidContent("插件配置格式不正确")
        return {}
    out: dict[str, dict[str, Any]] = {}
    for ext_id, state in raw.items():
        ext = get(str(ext_id), config=config)
        if ext is None:
            if strict:
                raise InvalidContent(f"不支持的插件：{ext_id}")
            continue
        if not _matches_scope(ext, target=target, capabilities=capabilities):
            if strict:
                raise InvalidContent(f"插件 {ext.id} 不适用于当前空间类型")
            continue
        if not isinstance(state, dict):
            if strict:
                raise InvalidContent("插件状态格式不正确")
            continue
        if "mode" in state:
            parsed = parse_layer_state(state, is_site=False, strict=strict)
            if parsed.mode == "inherit":
                continue
            sparse_cfg = normalize_sparse_config(
                ext,
                state.get("config"),
                strict=strict,
                project_slug=project_slug,
            )
            out[ext.id] = {
                "mode": parsed.mode,
                "cascade": parsed.cascade,
                "config": sparse_cfg,
            }
            continue
        installed = sanitize_bool(state.get("installed", True), True, strict=strict)
        if not installed:
            continue
        enabled = sanitize_bool(state.get("enabled", False), False, strict=strict)
        ext_cfg = ext.normalize_config(state.get("config"), strict=strict, project_slug=project_slug)
        out[ext.id] = {
            "installed": True,
            "enabled": enabled,
            "config": ext_cfg,
        }
    return out


def normalize_post_meta(
    raw_meta: object,
    *,
    strict: bool = False,
    project_slug: str | None = None,
    config: Config | None = None,
) -> dict[str, Any]:
    if raw_meta is None:
        return {}
    if not isinstance(raw_meta, dict):
        if strict:
            raise InvalidContent("文章扩展元数据格式不正确")
        return {}
    merged: dict[str, Any] = {}
    for ext in all_extensions(target="blog", config=config):
        normalized = ext.normalize_post_meta(raw_meta, strict=strict, project_slug=project_slug)
        for key, value in normalized.items():
            if value not in ("", None, [], {}):
                merged[key] = value
    return merged


def active_extensions(
    content: dict[str, Any],
    *,
    target: TargetType | None = None,
    capabilities: frozenset[Capability] | None = None,
    config: Config | None = None,
) -> list[tuple[Extension, dict[str, Any]]]:
    raw_map = content.get("extensions")
    if not isinstance(raw_map, dict):
        return []
    active: list[tuple[Extension, dict[str, Any]]] = []
    for ext in all_extensions(target=target, capabilities=capabilities, config=config):
        state = raw_map.get(ext.id)
        if not isinstance(state, dict):
            continue
        parsed = parse_layer_state(state, is_site=False)
        if parsed.mode == "override":
            active.append((ext, ext.normalize_config(parsed.config)))
    return active


def active_extensions_for_project(
    db: Session,
    project: Project,
    *,
    target: TargetType | None = None,
    capabilities: frozenset[Capability] | None = None,
    config: Config | None = None,
    content: dict[str, Any] | None = None,
) -> list[tuple[Extension, dict[str, Any]]]:
    resolved = resolve_project_extensions(
        db,
        project,
        target=target,
        capabilities=capabilities,
        config=config,
        content=content,
    )
    return [(item.extension, item.effective_config) for item in resolved.values() if item.effective_enabled]


def _base_catalog_meta(ext: Extension) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": ext.id,
        "pack_id": ext.pack_id,
        "pack_name": ext.pack_name,
        "targets": list(ext.targets),
        "requires": sorted(ext.requires),
        "excludes": sorted(ext.excludes),
        "name": ext.name,
        "name_key": ext.name_key,
        "description": ext.description,
        "description_key": ext.description_key,
        "version": ext.version,
        "icon": ext.icon,
        "config_schema": [field.as_dict() for field in ext.config_schema],
    }
    name_en = getattr(ext, "name_en", "")
    description_en = getattr(ext, "description_en", "")
    if name_en:
        item["name_en"] = name_en
    if description_en:
        item["description_en"] = description_en
    return item


def extension_catalog_item(ext: Extension, content: dict[str, Any]) -> dict[str, Any]:
    raw_map = content.get("extensions") if isinstance(content.get("extensions"), dict) else {}
    state = raw_map.get(ext.id) if isinstance(raw_map, dict) else None
    parsed = parse_layer_state(state, is_site=False)
    installed = parsed.mode != "inherit"
    enabled = parsed.mode == "override"
    raw_cfg = ext.normalize_config(parsed.config if installed else None)
    raw_default = ext.normalize_config(None)
    redacted_cfg, secrets_set = ext.redact_config(raw_cfg)
    redacted_default, _ = ext.redact_config(raw_default)
    redacted_local, local_secrets = ext.redact_config(parsed.config)
    secret_inherited = {key: False for key in sorted(ext.secret_fields())}
    return {
        **_base_catalog_meta(ext),
        "installed": installed,
        "enabled": enabled,
        "effective_enabled": enabled,
        "config": redacted_cfg,
        "effective_config": redacted_cfg,
        "local_config": redacted_local if installed else {},
        "inherited_config": redacted_default,
        "default_config": redacted_default,
        "secrets_set": secrets_set,
        "secret_inherited": secret_inherited,
        "local_secrets_set": local_secrets if installed else {k: False for k in sorted(ext.secret_fields())},
        "source": "local" if installed else "none",
        "source_slug": "",
        "source_title": "",
        "local_mode": parsed.mode,
        "cascade": parsed.cascade,
        "inherited_enabled": False,
        "inherited_source": "none",
        "inherited_source_title": "",
    }


def resolved_catalog_item(res: ResolvedExtension) -> dict[str, Any]:
    ext = res.extension
    redacted_effective, _ = ext.redact_config(res.effective_config)
    redacted_default, _ = ext.redact_config(ext.normalize_config(None))
    redacted_inherited, _ = ext.redact_config(res.inherited_config)
    redacted_local_full, _ = ext.redact_config(res.local_config)
    redacted_local = {k: redacted_local_full[k] for k in res.local_config if k in redacted_local_full}
    installed = res.local_mode != "inherit"
    return {
        **_base_catalog_meta(ext),
        "installed": installed,
        "enabled": res.effective_enabled,
        "effective_enabled": res.effective_enabled,
        "config": redacted_effective,
        "effective_config": redacted_effective,
        "local_config": redacted_local,
        "inherited_config": redacted_inherited,
        "default_config": redacted_default,
        "secrets_set": dict(res.secrets_set),
        "secret_inherited": dict(res.secret_inherited),
        "local_secrets_set": dict(res.local_secrets_set),
        "source": res.source,
        "source_slug": res.source_slug,
        "source_title": res.source_title,
        "local_mode": res.local_mode,
        "cascade": res.cascade,
        "inherited_enabled": res.inherited_enabled,
        "inherited_source": res.inherited_source,
        "inherited_source_title": res.inherited_source_title,
    }


def site_catalog_item(ext: Extension, site_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    raw_state = site_map.get(ext.id)
    configured = isinstance(raw_state, dict)
    parsed = parse_layer_state(raw_state, is_site=True)
    enabled = parsed.mode == "override"
    raw_cfg = ext.normalize_config(parsed.config if configured else None, strict=False, project_slug=None)
    raw_default = ext.normalize_config(None)
    redacted_cfg, secrets_set = ext.redact_config(raw_cfg)
    redacted_default, _ = ext.redact_config(raw_default)
    secret_inherited = {key: False for key in sorted(ext.secret_fields())}
    return {
        **_base_catalog_meta(ext),
        "configured": configured,
        "installed": configured,
        "enabled": enabled,
        "effective_enabled": enabled,
        "config": redacted_cfg,
        "effective_config": redacted_cfg,
        "default_config": redacted_default,
        "secrets_set": secrets_set,
        "secret_inherited": secret_inherited,
        "local_secrets_set": dict(secrets_set),
        "source": "site" if enabled else "none",
        "source_slug": "",
        "source_title": SITE_SOURCE_TITLE if enabled else "",
        "local_mode": parsed.mode,
        "cascade": parsed.cascade,
        "inherited_enabled": False,
        "inherited_source": "none",
        "inherited_source_title": "",
    }


def build_admin_catalog(
    content: dict[str, Any],
    *,
    target: TargetType | None = None,
    capabilities: frozenset[Capability] | None = None,
    config: Config | None = None,
) -> list[dict[str, Any]]:
    return [
        extension_catalog_item(ext, content)
        for ext in all_extensions(target=target, capabilities=capabilities, config=config)
    ]


def build_project_admin_catalog(
    db: Session,
    project: Project,
    *,
    target: TargetType | None = None,
    capabilities: frozenset[Capability] | None = None,
    config: Config | None = None,
    content: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    resolved = resolve_project_extensions(
        db,
        project,
        target=target,
        capabilities=capabilities,
        config=config,
        content=content,
    )
    return [resolved_catalog_item(item) for item in resolved.values()]


def build_site_admin_catalog(
    db: Session,
    *,
    config: Config | None = None,
) -> list[dict[str, Any]]:
    site_map = load_site_extensions(db)
    return [site_catalog_item(ext, site_map) for ext in all_extensions(target=None, config=config)]


def _resolve_asset_url(url: str) -> str:
    if url.startswith("/media/plugins/"):
        return url
    return static_url(url)


def build_render_bundle(
    page: PageKind,
    project: Project,
    content: dict[str, Any],
    posts: list[dict[str, Any]] | None = None,
    post: dict[str, Any] | None = None,
    *,
    target: TargetType | None = None,
    capabilities: frozenset[Capability] | None = None,
    config: Config | None = None,
    is_admin: bool = False,
    db: Session | None = None,
) -> dict[str, Any]:
    resolved_target: TargetType | None = target
    if capabilities is None and resolved_target is None:
        if page == "space":
            resolved_target = "space"
        elif page == "resume":
            resolved_target = "resume"
        else:
            resolved_target = "blog"

    css_files: list[str] = []
    js_files: list[str] = []
    body_classes: list[str] = []
    body_start_fragments: list[Markup] = []
    main_start_fragments: list[Markup] = []
    body_end_fragments: list[Markup] = []
    slots: dict[str, list[Markup]] = {slot_name: [] for slot_name in STRUCTURED_SLOTS}
    tokens: dict[str, str] = {}
    icon_overrides: dict[str, str] = {}
    layout = ""
    list_card_templates: list[tuple[str, str]] = []
    post_header_templates: list[tuple[str, str]] = []
    contexts: dict[str, dict[str, Any]] = {}

    ext_pairs = (
        active_extensions_for_project(
            db,
            project,
            target=resolved_target,
            capabilities=capabilities,
            config=config,
            content=content,
        )
        if db is not None
        else active_extensions(
            content,
            target=resolved_target,
            capabilities=capabilities,
            config=config,
        )
    )

    for ext, cfg in ext_pairs:
        if isinstance(ext, PackExtension) and not ext.matches_page(page):
            continue
        for href in ext.static_css:
            versioned_href = _resolve_asset_url(href)
            if versioned_href not in css_files:
                css_files.append(versioned_href)
        for src in ext.static_js:
            versioned_src = _resolve_asset_url(src)
            if versioned_src not in js_files:
                js_files.append(versioned_src)
        for cls in ext.body_classes(page=page, config=cfg):
            if cls not in body_classes:
                body_classes.append(cls)
        ctx = ext.render_page_context(
            page=page,
            project=project,
            content=content,
            config=cfg,
            posts=posts,
            post=post,
            is_admin=is_admin,
        )
        if page == "list" and ext.list_card_template:
            list_card_templates.append((ext.id, ext.list_card_template))
        elif page == "post" and ext.post_header_template:
            post_header_templates.append((ext.id, ext.post_header_template))
        contexts[ext.id] = ctx

        ext_tokens = sanitize_theme_tokens(ext.theme_tokens(page, cfg), strict=False)
        if ext_tokens:
            tokens.update(ext_tokens)

        ext_icons = sanitize_icon_overrides(ext.icon_overrides(page, cfg), strict=False)
        if ext_icons:
            icon_overrides.update(ext_icons)

        ext_layout = ext.layout_mode(page, cfg)
        if isinstance(ext_layout, str) and LAYOUT_MODE_RE.match(ext_layout):
            layout = ext_layout

        start_html = ext.inject_html(
            slot="start",
            page=page,
            project=project,
            content=content,
            config=cfg,
            context=ctx,
        )
        if start_html:
            body_start_fragments.append(start_html)
        main_start_html = ext.inject_html(
            slot="main_start",
            page=page,
            project=project,
            content=content,
            config=cfg,
            context=ctx,
        )
        if main_start_html:
            main_start_fragments.append(main_start_html)
        end_html = ext.inject_html(
            slot="end",
            page=page,
            project=project,
            content=content,
            config=cfg,
            context=ctx,
        )
        if end_html:
            body_end_fragments.append(end_html)

        for slot_name in STRUCTURED_SLOTS:
            slot_html = ext.inject_slot(
                slot_name,
                page,
                project,
                content,
                cfg,
                ctx,
            )
            if slot_html:
                slots[slot_name].append(slot_html)

    return {
        "css_files": css_files,
        "js_files": js_files,
        "body_classes": body_classes,
        "body_start_fragments": body_start_fragments,
        "main_start_fragments": main_start_fragments,
        "body_end_fragments": body_end_fragments,
        "slots": slots,
        "tokens": tokens,
        "icon_overrides": icon_overrides,
        "layout": layout,
        "list_card_templates": list_card_templates,
        "post_header_templates": post_header_templates,
        "contexts": contexts,
    }


def build_editor_bundle(
    blog: dict[str, Any],
    project: Project,
    post: dict[str, Any] | None = None,
    *,
    config: Config | None = None,
    db: Session | None = None,
) -> dict[str, Any]:
    fields: list[dict[str, Any]] = []
    ext_pairs = (
        active_extensions_for_project(db, project, target="blog", config=config, content=blog)
        if db is not None
        else active_extensions(blog, target="blog", config=config)
    )
    for ext, cfg in ext_pairs:
        if not ext.editor_fields_template:
            continue
        fields.append(
            {
                "id": ext.id,
                "template": ext.editor_fields_template,
                "config": cfg,
                "context": ext.render_editor_context(project=project, post=post, config=cfg),
            }
        )
    return {"fields": fields}


def referenced_media_urls(
    content: dict[str, Any],
    *,
    target: TargetType | None = None,
    capabilities: frozenset[Capability] | None = None,
    config: Config | None = None,
) -> set[str]:
    urls: set[str] = set()
    posts = content.get("posts")
    if isinstance(posts, list):
        for post in posts:
            if not isinstance(post, dict):
                continue
            meta = post.get("meta")
            if isinstance(meta, dict):
                for value in meta.values():
                    if isinstance(value, str) and value.startswith(("/media/blog/", "/media/ext/")):
                        urls.add(value)
            body = post.get("body")
            if isinstance(body, str) and "/media/blog/" in body:
                urls.update(_BODY_BLOG_MEDIA_URL_RE.findall(body))
    raw_ext = content.get("extensions")
    if isinstance(raw_ext, dict):
        for ext in all_extensions(target=target, capabilities=capabilities, config=config):
            state = raw_ext.get(ext.id)
            if isinstance(state, dict):
                parsed = parse_layer_state(state, is_site=False)
                if parsed.mode != "inherit":
                    cfg = ext.normalize_config(parsed.config)
                    for url in ext.local_media_urls(cfg):
                        if url.startswith(("/media/blog/", "/media/ext/")):
                            urls.add(url)
    return urls


def redact_content_extensions(
    content: dict[str, Any],
    *,
    target: TargetType | None = None,
    capabilities: frozenset[Capability] | None = None,
    config: Config | None = None,
) -> dict[str, Any]:
    if not isinstance(content, dict):
        return content
    raw_ext = content.get("extensions")
    if not isinstance(raw_ext, dict):
        return dict(content)
    out = dict(content)
    redacted_map: dict[str, Any] = {}
    for ext_id, state in raw_ext.items():
        if not isinstance(state, dict):
            redacted_map[ext_id] = state
            continue
        ext = get(str(ext_id), config=config)
        if ext is None or not _matches_scope(ext, target=target, capabilities=capabilities):
            redacted_map[ext_id] = dict(state)
            continue
        raw_cfg = state.get("config")
        if isinstance(raw_cfg, dict) and ext.secret_fields():
            redacted_cfg, _ = ext.redact_config(raw_cfg)
            redacted_map[ext_id] = {**state, "config": redacted_cfg}
        else:
            redacted_map[ext_id] = dict(state)
    out["extensions"] = redacted_map
    return out


def merge_content_extension_secrets(
    existing_content: dict[str, Any],
    incoming_content: dict[str, Any],
    *,
    target: TargetType | None = None,
    capabilities: frozenset[Capability] | None = None,
    config: Config | None = None,
) -> dict[str, Any]:
    if not isinstance(incoming_content, dict):
        return incoming_content
    raw_incoming = incoming_content.get("extensions")
    if not isinstance(raw_incoming, dict):
        return dict(incoming_content)
    raw_existing = existing_content.get("extensions") if isinstance(existing_content, dict) else {}
    existing_map = raw_existing if isinstance(raw_existing, dict) else {}
    out = dict(incoming_content)
    merged_map: dict[str, Any] = {}
    for ext_id, state in raw_incoming.items():
        if not isinstance(state, dict):
            merged_map[ext_id] = state
            continue
        ext = get(str(ext_id), config=config)
        if (
            ext is None
            or not _matches_scope(ext, target=target, capabilities=capabilities)
            or not ext.secret_fields()
        ):
            merged_map[ext_id] = dict(state)
            continue
        prev_state = existing_map.get(ext_id)
        prev_cfg = prev_state.get("config") if isinstance(prev_state, dict) else None
        inc_cfg = state.get("config")
        if isinstance(inc_cfg, dict):
            merged_cfg = ext.merge_config(
                prev_cfg if isinstance(prev_cfg, dict) else None,
                inc_cfg,
            )
            merged_map[ext_id] = {**state, "config": merged_cfg}
        else:
            merged_map[ext_id] = dict(state)
    out["extensions"] = merged_map
    return out


register(PostCoverExtension())
register(PostBackgroundExtension())
register(MascotExtension())
register(SpaceBannerExtension())
register(SpaceBackgroundExtension())
register(SpaceLayoutExtension())
register(ResumeStyleExtension())
