import hashlib
import json
import os
import re
import secrets
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast
from urllib.parse import urlparse

from markupsafe import Markup
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Config
from app.extensions.base import (
    ALLOWED_OVERRIDE_ICONS,
    EXT_ID_RE,
    EXTENSIBLE_TARGETS,
    OFFICIAL_PACK_ID,
    OFFICIAL_PACK_NAME,
    PACK_ID_RE,
    STRUCTURED_SLOTS,
    BaseExtension,
    ConfigField,
    ConfigOption,
    PageKind,
    SlotKind,
    StructuredSlotKind,
    TargetType,
    sanitize_bool,
    sanitize_choice,
    sanitize_float,
    sanitize_int,
    sanitize_text,
    sanitize_theme_tokens,
)
from app.models import Project
from app.og import fetch_archive, validate_public_host
from app.plugins.base import InvalidContent
from app.uploads import (
    InvalidUpload,
    delete_project_media_url,
    extract_zip_tree,
    remove_tree,
    sanitize_svg,
)

MAX_PACKS = 20
MAX_PLUGINS_PER_PACK = 30
MAX_PACK_ARCHIVE_BYTES = 10 * 1024 * 1024
MAX_PACK_EXTRACT_BYTES = 20 * 1024 * 1024
MAX_PACK_ZIP_ENTRIES = 300
MAX_ASSET_FILE_BYTES = 256 * 1024
MAX_MANIFEST_BYTES = 256 * 1024
MAX_ASSETS_PER_KIND = 5
MAX_CONFIG_FIELDS = 20
MAX_SELECT_OPTIONS = 30

ALLOWED_ASSET_EXTS = frozenset(
    {".css", ".js", ".svg", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".woff2", ".json"}
)
ALLOWED_PACK_FIELD_KINDS = frozenset({"select", "text", "textarea", "number", "range", "boolean"})
ALLOWED_MOUNT_TAGS = frozenset({"div", "aside", "section", "span"})
ALLOWED_SLOTS = frozenset(
    {
        "body_start",
        "main_start",
        "body_end",
        "header",
        "aside",
        "overlay",
        "footer",
        "title_deco",
        "none",
    }
)
ALLOWED_PAGES: tuple[PageKind, ...] = ("list", "post", "space", "resume")
MAX_THEME_TOKENS = 30
MAX_ICON_OVERRIDES = 30

_SEMVER_RE = re.compile(r"^[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}(?:-[a-zA-Z0-9.-]{1,32})?$")
_ICON_RE = re.compile(r"^[a-z0-9-]{1,32}$")
_PLUGIN_PATH_RE = re.compile(r"^plugins/([a-z][a-z0-9_]{1,31})$")
_FIELD_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_SAFE_CSS_CLASS_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,48}$")
_GH_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
_GH_REF_RE = re.compile(r"^[A-Za-z0-9._/-]{1,120}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")

_PACK_CACHE: dict[Path, tuple[tuple[int, int] | None, list["PackExtension"]]] = {}


class PackError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class PackExtension(BaseExtension):
    def __init__(
        self,
        *,
        pack_id: str,
        pack_name: str,
        local_id: str,
        name: str,
        name_en: str,
        description: str,
        description_en: str,
        version: str,
        icon: str,
        targets: tuple[TargetType, ...],
        pages: tuple[PageKind, ...],
        slot: str,
        mount: dict[str, str],
        static_css: tuple[str, ...],
        static_js: tuple[str, ...],
        config_schema: tuple[ConfigField, ...],
        defaults: dict[str, Any],
        int_fields: set[str],
        tokens: dict[str, str] | None = None,
        icon_overrides: dict[str, str] | None = None,
    ) -> None:
        self.id = f"{pack_id}.{local_id}"
        self.pack_id = pack_id
        self.pack_name = pack_name
        self.local_id = local_id
        self.targets = targets
        self.pages = pages
        self.slot = slot
        self.mount = mount
        self.name = name
        self.name_en = name_en
        self.name_key = ""
        self.description = description
        self.description_en = description_en
        self.description_key = ""
        self.version = version
        self.icon = icon
        self.media_kinds = ()
        self.static_css = static_css
        self.static_js = static_js
        self.asset_base = f"/media/plugins/{pack_id}/{local_id}/"
        self.config_schema = config_schema
        self._defaults = defaults
        self._int_fields = int_fields
        self._tokens = dict(tokens) if tokens else {}
        self._icon_overrides = dict(icon_overrides) if icon_overrides else {}
        self.body_start_template = "extensions/_declarative_widget.html" if slot == "body_start" else None
        self.main_start_template = "extensions/_declarative_widget.html" if slot == "main_start" else None
        self.body_end_template = "extensions/_declarative_widget.html" if slot == "body_end" else None

    @property
    def default_config(self) -> dict[str, Any]:
        return dict(self._defaults)

    @default_config.setter
    def default_config(self, value: dict[str, Any]) -> None:
        self._defaults = dict(value)

    def normalize_config(
        self,
        raw: object,
        *,
        strict: bool = False,
        project_slug: str | None = None,
    ) -> dict[str, Any]:
        if raw is None:
            return dict(self._defaults)
        if not isinstance(raw, dict):
            if strict:
                raise InvalidContent(f"插件 {self.name} 的配置必须是对象")
            return dict(self._defaults)
        out: dict[str, Any] = {}
        for field in self.config_schema:
            default_val = self._defaults.get(field.key)
            raw_val = raw.get(field.key)
            if field.kind == "boolean":
                out[field.key] = sanitize_bool(raw_val, bool(default_val), strict=strict)
            elif field.kind == "select":
                allowed = [opt.value for opt in field.options]
                out[field.key] = sanitize_choice(raw_val, allowed, str(default_val or ""), strict=strict)
            elif field.kind in ("text", "textarea"):
                if raw_val is None:
                    out[field.key] = str(default_val or "")
                elif not isinstance(raw_val, str):
                    if strict:
                        raise InvalidContent(f"配置项 {field.label_default} 必须是文本")
                    out[field.key] = str(default_val or "")
                else:
                    out[field.key] = sanitize_text(raw_val, field.max_length)
            elif field.kind == "number" and field.key in self._int_fields:
                low_i = int(field.min_value) if field.min_value is not None else -1_000_000
                high_i = int(field.max_value) if field.max_value is not None else 1_000_000
                out[field.key] = sanitize_int(
                    raw_val,
                    int(default_val) if isinstance(default_val, (int, float)) else low_i,
                    low=low_i,
                    high=high_i,
                    strict=strict,
                )
            elif field.kind in ("number", "range"):
                low_f = float(field.min_value) if field.min_value is not None else -1_000_000.0
                high_f = float(field.max_value) if field.max_value is not None else 1_000_000.0
                out[field.key] = sanitize_float(
                    raw_val,
                    float(default_val) if isinstance(default_val, (int, float)) else low_f,
                    low=low_f,
                    high=high_f,
                    step=field.step,
                    strict=strict,
                )
        return out

    def render_page_context(
        self,
        *,
        page: PageKind,
        project: Project,
        content: dict[str, Any],
        config: dict[str, Any],
        posts: list[dict[str, Any]] | None = None,
        post: dict[str, Any] | None = None,
        is_admin: bool = False,
    ) -> dict[str, Any]:
        if page not in self.pages:
            return {"active": False}
        return {
            "active": True,
            "ext_id": self.id,
            "pack_id": self.pack_id,
            "local_id": self.local_id,
            "page": page,
            "project_slug": project.slug,
            "asset_base": self.asset_base,
            "mount_tag": self.mount.get("tag", "div"),
            "mount_class": self.mount.get("class", ""),
            "aria_label": self.mount.get("aria_label", ""),
            "config": config,
        }

    def theme_tokens(
        self,
        page: PageKind,
        config: dict[str, Any],
    ) -> dict[str, str]:
        if page not in self.pages or not self._tokens:
            return {}
        return dict(self._tokens)

    def icon_overrides(
        self,
        page: PageKind,
        config: dict[str, Any],
    ) -> dict[str, str]:
        if page not in self.pages or not self._icon_overrides:
            return {}
        return dict(self._icon_overrides)

    def inject_html(
        self,
        *,
        slot: SlotKind,
        page: PageKind,
        project: Project,
        content: dict[str, Any],
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> Markup:
        if not context.get("active"):
            return Markup("")
        expected = {
            "start": "body_start",
            "main_start": "main_start",
            "end": "body_end",
        }.get(slot)
        if expected != self.slot:
            return Markup("")
        return self.render_fragment(
            "extensions/_declarative_widget.html",
            {
                "page": page,
                "project": project,
                "content": content,
                "config": config,
                "ext_ctx": context,
            },
        )

    def inject_slot(
        self,
        slot: StructuredSlotKind | SlotKind,
        page: PageKind,
        project: Project,
        content: dict[str, Any],
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> Markup:
        if slot in ("start", "main_start", "end"):
            return self.inject_html(
                slot=slot,
                page=page,
                project=project,
                content=content,
                config=config,
                context=context,
            )
        if not context.get("active") or slot not in STRUCTURED_SLOTS or slot != self.slot:
            return Markup("")
        return self.render_fragment(
            "extensions/_declarative_widget.html",
            {
                "slot": slot,
                "page": page,
                "project": project,
                "content": content,
                "config": config,
                "ext_ctx": context,
            },
        )


def _plugins_dir(data_dir: Path) -> Path:
    return data_dir / "plugins"


def _packs_index_path(data_dir: Path) -> Path:
    return _plugins_dir(data_dir) / "packs.json"


def _packs_store_dir(data_dir: Path) -> Path:
    return _plugins_dir(data_dir) / "packs"


def invalidate_pack_cache(data_dir: Path | None = None) -> None:
    if data_dir is None:
        _PACK_CACHE.clear()
        return
    _PACK_CACHE.pop(data_dir.resolve(), None)


def _read_index(data_dir: Path) -> list[dict[str, Any]]:
    index_path = _packs_index_path(data_dir)
    if not index_path.is_file():
        return []
    try:
        parsed = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, dict) or not isinstance(parsed.get("packs"), list):
        return []
    return [item for item in parsed["packs"] if isinstance(item, dict)]


def _write_index(data_dir: Path, packs: list[dict[str, Any]]) -> None:
    folder = _plugins_dir(data_dir)
    folder.mkdir(parents=True, exist_ok=True)
    index_path = _packs_index_path(data_dir)
    tmp_path = folder / f"packs.{secrets.token_hex(6)}.tmp"
    payload = {"schema_version": 1, "packs": packs}
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, index_path)


def _read_json_file(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise PackError(f"缺少有效的 {label}", 422)
    if path.stat().st_size > MAX_MANIFEST_BYTES:
        raise PackError(f"{label} 文件过大", 422)
    try:
        raw = path.read_text(encoding="utf-8")
        parsed = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PackError(f"{label} 不是合法的 UTF-8 JSON", 422) from exc
    if not isinstance(parsed, dict):
        raise PackError(f"{label} 根节点必须是 JSON 对象", 422)
    return parsed


def _require_str(
    obj: dict[str, Any],
    key: str,
    label: str,
    *,
    min_len: int = 0,
    max_len: int = 200,
    required: bool = False,
) -> str:
    val = obj.get(key)
    if val is None:
        if required:
            raise PackError(f"清单缺少必填字段 {label}", 422)
        return ""
    if not isinstance(val, str):
        raise PackError(f"清单字段 {label} 必须是文本", 422)
    cleaned = val.strip()
    if len(cleaned) < min_len or len(cleaned) > max_len:
        raise PackError(f"清单字段 {label} 长度超出限制（{min_len}~{max_len}）", 422)
    if _CONTROL_RE.search(cleaned.replace("\n", "").replace("\r", "")):
        raise PackError(f"清单字段 {label} 包含非法控制字符", 422)
    return cleaned


def _validate_pack_id(pack_id: str) -> str:
    if pack_id == OFFICIAL_PACK_ID:
        raise PackError("不能使用官方保留插件包标识", 400)
    if not PACK_ID_RE.match(pack_id) or "--" in pack_id:
        raise PackError("插件包标识格式不正确（仅允许小写字母、数字和单个连字符，长度 2-32）", 422)
    return pack_id


def _validate_homepage(raw: object) -> str:
    if raw is None or raw == "":
        return ""
    if not isinstance(raw, str):
        raise PackError("插件包主页地址必须是文本", 422)
    text = raw.strip()
    if len(text) > 300 or _CONTROL_RE.search(text):
        raise PackError("插件包主页地址格式不正确", 422)
    parsed = urlparse(text)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
        raise PackError("插件包主页地址仅支持 http(s)://", 422)
    return text


def _normalize_asset_rel(raw: object, expected_suffix: str) -> str:
    if not isinstance(raw, str):
        raise PackError("插件资源路径必须是文本", 422)
    cleaned = raw.strip().replace("\\", "/").removeprefix("assets/")
    if not cleaned or cleaned.startswith("/") or "\x00" in cleaned or ":" in cleaned:
        raise PackError("插件资源路径不合法", 422)
    parts = PurePosixPath(cleaned).parts
    if not parts or any(part in ("", ".", "..") or part.startswith(".") for part in parts):
        raise PackError("插件资源路径包含非法片段", 422)
    rel = PurePosixPath(*parts).as_posix()
    if not rel.lower().endswith(expected_suffix):
        raise PackError(f"插件资源路径必须以 {expected_suffix} 结尾", 422)
    return rel


def _parse_pack_tokens(raw_tokens: object, local_id: str) -> dict[str, str]:
    if raw_tokens is None:
        return {}
    if not isinstance(raw_tokens, dict) or len(raw_tokens) > MAX_THEME_TOKENS:
        raise PackError(f"插件 {local_id} 的 tokens 必须是对象且不超过 {MAX_THEME_TOKENS} 项", 422)
    try:
        return sanitize_theme_tokens(raw_tokens, strict=True)
    except InvalidContent as exc:
        raise PackError(f"插件 {local_id} 的 tokens 校验失败：{exc}", 422) from exc


def _parse_pack_icon_overrides(raw_overrides: object, local_id: str) -> dict[str, str]:
    if raw_overrides is None:
        return {}
    if not isinstance(raw_overrides, dict) or len(raw_overrides) > MAX_ICON_OVERRIDES:
        raise PackError(
            f"插件 {local_id} 的 icon_overrides 必须是对象且不超过 {MAX_ICON_OVERRIDES} 项",
            422,
        )
    out: dict[str, str] = {}
    for key, raw_path in raw_overrides.items():
        if not isinstance(key, str) or key.strip() not in ALLOWED_OVERRIDE_ICONS:
            raise PackError(f"插件 {local_id} 声明了不支持的图标覆盖名称：{key}", 422)
        if not isinstance(raw_path, str):
            raise PackError(f"插件 {local_id} 的图标覆盖路径必须是文本", 422)
        stripped = raw_path.strip()
        if (
            stripped.startswith(("/", "\\"))
            or "://" in stripped
            or ".." in stripped.replace("\\", "/").split("/")
        ):
            raise PackError(f"插件 {local_id} 的图标覆盖路径不合法：{raw_path}", 422)
        rel = _normalize_asset_rel(stripped, ".svg")
        out[key.strip()] = rel
    return out


def _default_pages_for_targets(targets: tuple[TargetType, ...]) -> tuple[PageKind, ...]:
    pages: list[PageKind] = []
    if "blog" in targets:
        pages.extend(["list", "post"])
    if "space" in targets:
        pages.append("space")
    if "resume" in targets:
        pages.append("resume")
    return tuple(pages)


def _parse_config_schema(
    raw_schema: object,
) -> tuple[list[dict[str, Any]], tuple[ConfigField, ...], dict[str, Any], set[str]]:
    if raw_schema is None:
        return [], (), {}, set()
    if not isinstance(raw_schema, list) or len(raw_schema) > MAX_CONFIG_FIELDS:
        raise PackError("插件 config_schema 格式不正确或字段数超过上限", 422)
    seen_keys: set[str] = set()
    normalized_raw: list[dict[str, Any]] = []
    fields: list[ConfigField] = []
    defaults: dict[str, Any] = {}
    int_fields: set[str] = set()
    for item in raw_schema:
        if not isinstance(item, dict):
            raise PackError("插件配置项定义必须是对象", 422)
        key = _require_str(item, "key", "config_schema.key", min_len=1, max_len=40, required=True)
        if not _FIELD_KEY_RE.match(key) or key in seen_keys:
            raise PackError(f"插件配置项 key 非法或重复：{key}", 422)
        seen_keys.add(key)
        kind = _require_str(item, "kind", "config_schema.kind", min_len=1, max_len=20, required=True)
        if kind not in ALLOWED_PACK_FIELD_KINDS:
            raise PackError(f"外部插件不支持的配置字段类型：{kind}", 422)
        label_default = _require_str(
            item,
            "label_default" if "label_default" in item else "label",
            f"config_schema.{key}.label",
            min_len=1,
            max_len=80,
            required=True,
        )
        label_key = _require_str(item, "label_key", f"config_schema.{key}.label_key", max_len=80)
        help_default = _require_str(
            item,
            "help_default" if "help_default" in item else "help",
            f"config_schema.{key}.help",
            max_len=200,
        )
        help_key = _require_str(item, "help_key", f"config_schema.{key}.help_key", max_len=80)
        placeholder_default = _require_str(
            item,
            "placeholder_default" if "placeholder_default" in item else "placeholder",
            f"config_schema.{key}.placeholder",
            max_len=120,
        )
        placeholder_key = _require_str(
            item,
            "placeholder_key",
            f"config_schema.{key}.placeholder_key",
            max_len=80,
        )
        group = _require_str(item, "group", f"config_schema.{key}.group", max_len=40)
        group_key = _require_str(item, "group_key", f"config_schema.{key}.group_key", max_len=80)
        group_default = _require_str(item, "group_default", f"config_schema.{key}.group_default", max_len=60)

        options: list[ConfigOption] = []
        raw_options_out: list[dict[str, str]] = []
        min_val: float | None = None
        max_val: float | None = None
        step_val: float | None = None
        max_length = 200
        raw_default = item.get("default")
        default_val: Any

        if kind == "select":
            raw_opts = item.get("options")
            if not isinstance(raw_opts, list) or not (1 <= len(raw_opts) <= MAX_SELECT_OPTIONS):
                raise PackError(f"选项字段 {key} 必须提供 1~{MAX_SELECT_OPTIONS} 个选项", 422)
            seen_opt_vals: set[str] = set()
            for opt in raw_opts:
                if not isinstance(opt, dict):
                    raise PackError(f"选项字段 {key} 的选项必须是对象", 422)
                opt_val = _require_str(
                    opt, "value", f"{key}.options.value", min_len=1, max_len=60, required=True
                )
                if opt_val in seen_opt_vals:
                    raise PackError(f"选项字段 {key} 包含重复选项值：{opt_val}", 422)
                seen_opt_vals.add(opt_val)
                opt_label = _require_str(
                    opt,
                    "label_default" if "label_default" in opt else "label",
                    f"{key}.options.label",
                    min_len=1,
                    max_len=80,
                    required=True,
                )
                opt_key = _require_str(opt, "label_key", f"{key}.options.label_key", max_len=80)
                options.append(ConfigOption(opt_val, opt_key, opt_label))
                raw_options_out.append({"value": opt_val, "label_key": opt_key, "label_default": opt_label})
            first_opt = options[0].value
            default_val = sanitize_choice(raw_default, seen_opt_vals, first_opt)
        elif kind == "boolean":
            default_val = sanitize_bool(raw_default, False)
        elif kind in ("text", "textarea"):
            raw_max_len = item.get("max_length", 500 if kind == "textarea" else 200)
            if isinstance(raw_max_len, bool) or not isinstance(raw_max_len, int):
                raise PackError(f"字段 {key} 的 max_length 必须是整数", 422)
            max_length = min(max(raw_max_len, 1), 2000)
            default_val = sanitize_text(raw_default, max_length)
        else:
            raw_min = item.get("min_value", item.get("min"))
            raw_max = item.get("max_value", item.get("max"))
            raw_step = item.get("step")
            if raw_min is not None:
                if isinstance(raw_min, bool) or not isinstance(raw_min, (int, float)):
                    raise PackError(f"字段 {key} 的最小值必须是数字", 422)
                min_val = float(raw_min)
            if raw_max is not None:
                if isinstance(raw_max, bool) or not isinstance(raw_max, (int, float)):
                    raise PackError(f"字段 {key} 的最大值必须是数字", 422)
                max_val = float(raw_max)
            if min_val is not None and max_val is not None and min_val > max_val:
                raise PackError(f"字段 {key} 的最小值不能大于最大值", 422)
            if raw_step is not None:
                if isinstance(raw_step, bool) or not isinstance(raw_step, (int, float)) or raw_step <= 0:
                    raise PackError(f"字段 {key} 的步进值必须是正数", 422)
                step_val = float(raw_step)
            low_f = min_val if min_val is not None else 0.0
            high_f = max_val if max_val is not None else 100.0
            if kind == "number" and (
                (step_val is None or step_val == 1.0)
                and (
                    raw_default is None
                    or (isinstance(raw_default, int) and not isinstance(raw_default, bool))
                )
            ):
                int_fields.add(key)
                low_i = int(low_f)
                high_i = int(high_f)
                default_val = sanitize_int(raw_default, low_i, low=low_i, high=high_i)
            else:
                default_val = sanitize_float(raw_default, low_f, low=low_f, high=high_f, step=step_val)

        field_kind = cast(
            Literal["select", "text", "textarea", "number", "range", "boolean"],
            kind,
        )
        field_obj = ConfigField(
            key=key,
            kind=field_kind,
            label_key=label_key,
            label_default=label_default,
            help_key=help_key,
            help_default=help_default,
            placeholder_key=placeholder_key,
            placeholder_default=placeholder_default,
            options=tuple(options),
            min_value=min_val,
            max_value=max_val,
            step=step_val,
            max_length=max_length,
            group=group,
            group_key=group_key,
            group_default=group_default,
        )
        fields.append(field_obj)
        defaults[key] = default_val
        normalized_raw.append(
            {
                "key": key,
                "kind": kind,
                "label_key": label_key,
                "label_default": label_default,
                "help_key": help_key,
                "help_default": help_default,
                "placeholder_key": placeholder_key,
                "placeholder_default": placeholder_default,
                "options": raw_options_out,
                "min_value": min_val,
                "max_value": max_val,
                "step": step_val,
                "max_length": max_length,
                "group": group,
                "group_key": group_key,
                "group_default": group_default,
                "default": default_val,
            }
        )
    return normalized_raw, tuple(fields), defaults, int_fields


def _validate_mount(raw_mount: object, slot: str) -> dict[str, str]:
    if raw_mount is None:
        return {"tag": "div", "class": "", "aria_label": ""} if slot != "none" else {}
    if not isinstance(raw_mount, dict):
        raise PackError("插件 mount 配置必须是对象", 422)
    tag = _require_str(raw_mount, "tag", "mount.tag", max_len=20) or "div"
    if tag not in ALLOWED_MOUNT_TAGS:
        raise PackError(f"插件 mount.tag 不受支持：{tag}", 422)
    raw_class = _require_str(raw_mount, "class", "mount.class", max_len=200)
    classes: list[str] = []
    if raw_class:
        tokens = raw_class.split()
        if len(tokens) > 8:
            raise PackError("插件 mount.class 类名数量超过上限", 422)
        for token in tokens:
            if not _SAFE_CSS_CLASS_RE.match(token):
                raise PackError(f"插件 mount.class 包含非法类名：{token}", 422)
            classes.append(token)
    aria_label = _require_str(raw_mount, "aria_label", "mount.aria_label", max_len=80)
    return {"tag": tag, "class": " ".join(classes), "aria_label": aria_label}


def _validate_plugin_dir(
    pack_id: str,
    pack_name: str,
    local_id: str,
    src_plugin_dir: Path,
    dst_plugin_dir: Path,
) -> dict[str, Any]:
    manifest = _read_json_file(src_plugin_dir / "plugin.json", f"plugins/{local_id}/plugin.json")
    schema_version = manifest.get("schema_version")
    if type(schema_version) is not int or schema_version != 1:
        raise PackError(f"插件 {local_id} 的 schema_version 必须为 1", 422)
    declared_id = _require_str(manifest, "id", "id", min_len=2, max_len=32, required=True)
    if not EXT_ID_RE.match(declared_id) or declared_id != local_id:
        raise PackError(f"插件标识 {declared_id} 必须与目录名 {local_id} 一致", 422)
    name = _require_str(manifest, "name", "name", min_len=1, max_len=80, required=True)
    name_en = _require_str(manifest, "name_en", "name_en", max_len=80)
    description = _require_str(manifest, "description", "description", max_len=300)
    description_en = _require_str(manifest, "description_en", "description_en", max_len=300)
    version = _require_str(manifest, "version", "version", min_len=1, max_len=40, required=True)
    if not _SEMVER_RE.match(version):
        raise PackError(f"插件 {local_id} 的版本号格式不正确", 422)
    icon = _require_str(manifest, "icon", "icon", max_len=32) or "puzzle"
    if not _ICON_RE.match(icon):
        raise PackError(f"插件 {local_id} 的图标名称格式不正确", 422)

    raw_targets = manifest.get("targets")
    if not isinstance(raw_targets, list) or not raw_targets:
        raise PackError(f"插件 {local_id} 必须声明至少一个适用目标空间", 422)
    targets: list[TargetType] = []
    for t in raw_targets:
        if not isinstance(t, str) or t not in EXTENSIBLE_TARGETS:
            raise PackError(f"插件 {local_id} 包含不受支持的目标空间：{t}", 422)
        t_typed = cast(TargetType, t)
        if t_typed not in targets:
            targets.append(t_typed)

    raw_pages = manifest.get("pages")
    if raw_pages is None:
        pages = list(_default_pages_for_targets(tuple(targets)))
    else:
        if not isinstance(raw_pages, list) or not raw_pages:
            raise PackError(f"插件 {local_id} 的 pages 字段格式不正确", 422)
        pages = []
        for p in raw_pages:
            if not isinstance(p, str) or p not in ALLOWED_PAGES:
                raise PackError(f"插件 {local_id} 包含不受支持的页面类型：{p}", 422)
            p_typed = cast(PageKind, p)
            if p_typed not in pages:
                pages.append(p_typed)

    raw_slot = manifest.get("slot")
    if raw_slot is None:
        slot = "body_end" if manifest.get("mount") is not None else "none"
    elif isinstance(raw_slot, str) and raw_slot in ALLOWED_SLOTS:
        slot = raw_slot
    else:
        raise PackError(f"插件 {local_id} 的挂载槽位不受支持", 422)

    mount = _validate_mount(manifest.get("mount"), slot)
    normalized_schema, _, _, _ = _parse_config_schema(manifest.get("config_schema"))
    normalized_tokens = _parse_pack_tokens(manifest.get("tokens"), local_id)
    normalized_icon_overrides = _parse_pack_icon_overrides(manifest.get("icon_overrides"), local_id)

    raw_assets = manifest.get("assets")
    if raw_assets is None:
        raw_assets = {}
    if not isinstance(raw_assets, dict):
        raise PackError(f"插件 {local_id} 的 assets 配置必须是对象", 422)
    css_rels: list[str] = []
    js_rels: list[str] = []
    for asset_kind, expected_ext, out_list in (("css", ".css", css_rels), ("js", ".js", js_rels)):
        items = raw_assets.get(asset_kind, [])
        if not isinstance(items, list) or len(items) > MAX_ASSETS_PER_KIND:
            raise PackError(f"插件 {local_id} 的 {asset_kind} 资源数量超过上限（{MAX_ASSETS_PER_KIND}）", 422)
        for entry in items:
            rel = _normalize_asset_rel(entry, expected_ext)
            if rel not in out_list:
                out_list.append(rel)

    src_assets_dir = src_plugin_dir / "assets"
    dst_assets_dir = dst_plugin_dir / "assets"
    copied_assets: dict[str, str] = {}
    if src_assets_dir.exists():
        if src_assets_dir.is_symlink() or not src_assets_dir.is_dir():
            raise PackError(f"插件 {local_id} 的 assets 目录无效", 422)
        src_assets_root = src_assets_dir.resolve()
        for candidate in sorted(src_assets_dir.rglob("*")):
            if candidate.is_symlink():
                raise PackError(f"插件 {local_id} 资源包含不允许的符号链接", 422)
            rel_path = candidate.relative_to(src_assets_dir)
            if any(part.startswith(".") for part in rel_path.parts):
                raise PackError(f"插件 {local_id} 资源包含隐藏文件", 422)
            if candidate.is_dir():
                continue
            if not candidate.resolve().is_relative_to(src_assets_root):
                raise PackError(f"插件 {local_id} 资源路径越界", 422)
            suffix = candidate.suffix.lower()
            if suffix not in ALLOWED_ASSET_EXTS:
                raise PackError(f"插件 {local_id} 包含不允许的资源文件类型：{suffix or candidate.name}", 422)
            raw_bytes = candidate.read_bytes()
            if len(raw_bytes) > MAX_ASSET_FILE_BYTES:
                raise PackError(f"插件 {local_id} 资源文件 {rel_path.as_posix()} 超过 256KB 限制", 422)
            if suffix == ".svg":
                try:
                    raw_bytes = sanitize_svg(raw_bytes)
                except InvalidUpload as exc:
                    raise PackError(f"插件 {local_id} 的 SVG 资源未通过安全校验：{exc}", 422) from exc
            dst_file = dst_assets_dir / rel_path
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            dst_file.write_bytes(raw_bytes)
            copied_assets[rel_path.as_posix()] = hashlib.sha256(raw_bytes).hexdigest()[:8]

    for rel in (*css_rels, *js_rels, *normalized_icon_overrides.values()):
        if rel not in copied_assets:
            raise PackError(f"插件 {local_id} 声明的资源文件不存在：assets/{rel}", 422)

    dst_plugin_dir.mkdir(parents=True, exist_ok=True)
    normalized_manifest: dict[str, Any] = {
        "schema_version": 1,
        "id": local_id,
        "name": name,
        "name_en": name_en,
        "description": description,
        "description_en": description_en,
        "version": version,
        "icon": icon,
        "targets": list(targets),
        "pages": list(pages),
        "slot": slot,
        "mount": mount,
        "assets": {"css": css_rels, "js": js_rels},
        "config_schema": normalized_schema,
    }
    if normalized_tokens:
        normalized_manifest["tokens"] = normalized_tokens
    if normalized_icon_overrides:
        normalized_manifest["icon_overrides"] = normalized_icon_overrides
    (dst_plugin_dir / "plugin.json").write_text(
        json.dumps(normalized_manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "id": f"{pack_id}.{local_id}",
        "local_id": local_id,
        "name": name,
        "name_en": name_en,
        "description": description,
        "description_en": description_en,
        "version": version,
        "icon": icon,
        "targets": list(targets),
    }


def _find_pack_root(extract_dir: Path) -> Path:
    if (extract_dir / "siteflow-pack.json").is_file():
        return extract_dir
    top_entries = [
        entry
        for entry in extract_dir.iterdir()
        if not entry.name.startswith(".") and entry.name != "__MACOSX"
    ]
    if len(top_entries) == 1 and top_entries[0].is_dir():
        candidate = top_entries[0]
        if (candidate / "siteflow-pack.json").is_file():
            return candidate
    raise PackError("插件包根目录缺少 siteflow-pack.json", 422)


def _stage_and_validate_pack(archive: bytes, tmp_root: Path) -> tuple[dict[str, Any], Path]:
    extract_dir = tmp_root / "extract"
    clean_dir = tmp_root / "clean"
    try:
        extract_zip_tree(
            archive,
            extract_dir,
            max_entries=MAX_PACK_ZIP_ENTRIES,
            max_extract_bytes=MAX_PACK_EXTRACT_BYTES,
            max_ratio=100,
        )
    except InvalidUpload as exc:
        raise PackError(str(exc), 422) from exc

    pack_root = _find_pack_root(extract_dir)
    manifest = _read_json_file(pack_root / "siteflow-pack.json", "siteflow-pack.json")
    schema_version = manifest.get("schema_version")
    if type(schema_version) is not int or schema_version != 1:
        raise PackError("siteflow-pack.json 的 schema_version 必须为 1", 422)

    pack_id = _validate_pack_id(_require_str(manifest, "id", "id", min_len=2, max_len=32, required=True))
    name = _require_str(manifest, "name", "name", min_len=1, max_len=80, required=True)
    name_en = _require_str(manifest, "name_en", "name_en", max_len=80)
    description = _require_str(manifest, "description", "description", max_len=300)
    description_en = _require_str(manifest, "description_en", "description_en", max_len=300)
    version = _require_str(manifest, "version", "version", min_len=1, max_len=40, required=True)
    if not _SEMVER_RE.match(version):
        raise PackError("插件包版本号格式不正确", 422)
    author = _require_str(manifest, "author", "author", max_len=80)
    homepage = _validate_homepage(manifest.get("homepage"))

    raw_plugins = manifest.get("plugins")
    if not isinstance(raw_plugins, list) or not (1 <= len(raw_plugins) <= MAX_PLUGINS_PER_PACK):
        raise PackError(f"插件包必须包含 1~{MAX_PLUGINS_PER_PACK} 个插件声明", 422)

    seen_plugins: set[str] = set()
    plugin_summaries: list[dict[str, Any]] = []
    plugin_paths: list[str] = []
    pack_root_resolved = pack_root.resolve()
    for rel in raw_plugins:
        if not isinstance(rel, str):
            raise PackError("plugins 列表项必须是字符串路径", 422)
        cleaned_rel = rel.strip().replace("\\", "/")
        match = _PLUGIN_PATH_RE.match(cleaned_rel)
        if not match:
            raise PackError(f"非法的插件目录路径：{rel}", 422)
        local_id = match.group(1)
        if local_id in seen_plugins:
            raise PackError(f"插件包内包含重复插件：{local_id}", 422)
        seen_plugins.add(local_id)
        src_plugin_dir = (pack_root / "plugins" / local_id).resolve()
        if not src_plugin_dir.is_relative_to(pack_root_resolved) or not src_plugin_dir.is_dir():
            raise PackError(f"插件目录不存在：{cleaned_rel}", 422)
        dst_plugin_dir = clean_dir / "plugins" / local_id
        summary = _validate_plugin_dir(pack_id, name, local_id, src_plugin_dir, dst_plugin_dir)
        plugin_summaries.append(summary)
        plugin_paths.append(cleaned_rel)

    clean_dir.mkdir(parents=True, exist_ok=True)
    normalized_pack = {
        "schema_version": 1,
        "id": pack_id,
        "name": name,
        "name_en": name_en,
        "description": description,
        "description_en": description_en,
        "version": version,
        "author": author,
        "homepage": homepage,
        "plugins": plugin_paths,
    }
    (clean_dir / "siteflow-pack.json").write_text(
        json.dumps(normalized_pack, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    meta = {
        "id": pack_id,
        "name": name,
        "name_en": name_en,
        "description": description,
        "description_en": description_en,
        "version": version,
        "author": author,
        "homepage": homepage,
        "plugin_count": len(plugin_summaries),
        "plugins": plugin_summaries,
    }
    return meta, clean_dir


def _swap_pack_dir(config: Config, pack_id: str, staged_dir: Path) -> None:
    packs_root = _packs_store_dir(config.data)
    packs_root.mkdir(parents=True, exist_ok=True)
    dest_dir = packs_root / pack_id
    backup_dir = config.data / "tmp" / f"pack_backup_{secrets.token_hex(6)}"
    backup_dir.parent.mkdir(parents=True, exist_ok=True)
    if dest_dir.exists():
        remove_tree(backup_dir)
        dest_dir.rename(backup_dir)
    try:
        staged_dir.rename(dest_dir)
    except Exception:
        if backup_dir.exists() and not dest_dir.exists():
            backup_dir.rename(dest_dir)
        raise
    finally:
        remove_tree(backup_dir)


def _resolve_pack_urls(raw_url: str) -> tuple[str, list[str]]:
    if not isinstance(raw_url, str) or not raw_url.strip():
        raise PackError("插件包地址不能为空", 400)
    if _CONTROL_RE.search(raw_url):
        raise PackError("插件包地址包含非法字符", 400)
    cleaned = raw_url.strip()
    if len(cleaned) > 500:
        raise PackError("插件包地址过长", 400)
    parsed = urlparse(cleaned)
    if parsed.scheme.lower() != "https":
        raise PackError("插件包订阅地址仅支持 HTTPS", 400)
    if parsed.username is not None or parsed.password is not None:
        raise PackError("插件包地址不允许包含认证信息", 400)
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise PackError("插件包地址缺少有效主机名", 400)
    parts = [seg for seg in parsed.path.split("/") if seg]
    if host == "github.com":
        if len(parts) == 2:
            owner = parts[0]
            repo = parts[1].removesuffix(".git")
            if (
                not _GH_SEGMENT_RE.match(owner)
                or not _GH_SEGMENT_RE.match(repo)
                or owner in (".", "..")
                or repo in (".", "..")
            ):
                raise PackError("无效的 GitHub 仓库地址", 400)
            canonical = f"https://github.com/{owner}/{repo}"
            return canonical, [
                f"https://github.com/{owner}/{repo}/archive/refs/heads/main.zip",
                f"https://github.com/{owner}/{repo}/archive/refs/heads/master.zip",
            ]
        if len(parts) >= 4 and parts[2] == "tree":
            owner = parts[0]
            repo = parts[1].removesuffix(".git")
            ref = "/".join(parts[3:])
            if (
                not _GH_SEGMENT_RE.match(owner)
                or not _GH_SEGMENT_RE.match(repo)
                or not _GH_REF_RE.match(ref)
                or ".." in ref.split("/")
            ):
                raise PackError("无效的 GitHub 分支或标签地址", 400)
            canonical = f"https://github.com/{owner}/{repo}/tree/{ref}"
            return canonical, [
                f"https://github.com/{owner}/{repo}/archive/refs/heads/{ref}.zip",
                f"https://github.com/{owner}/{repo}/archive/refs/tags/{ref}.zip",
            ]
        if parsed.path.lower().endswith(".zip"):
            return cleaned, [cleaned]
        raise PackError("不支持的 GitHub 地址格式，请填写仓库主页、/tree/分支 或 .zip 链接", 400)
    if parsed.path.lower().endswith(".zip"):
        return cleaned, [cleaned]
    raise PackError("仅支持 GitHub 仓库地址或 .zip 插件包直链", 400)


def _download_pack_archive(raw_url: str) -> tuple[str, bytes]:
    canonical_url, candidates = _resolve_pack_urls(raw_url)
    try:
        validate_public_host(candidates[0])
    except ValueError as exc:
        raise PackError(str(exc), 400) from exc

    last_error = "无法下载插件包"
    for idx, candidate in enumerate(candidates):
        try:
            archive = fetch_archive(candidate, max_bytes=MAX_PACK_ARCHIVE_BYTES, timeout=15.0)
            return canonical_url, archive
        except ValueError as exc:
            last_error = str(exc)
            if "HTTP 404" in last_error and idx + 1 < len(candidates):
                continue
            status = 413 if "超过大小限制" in last_error else 400
            raise PackError(last_error, status) from exc
    raise PackError(last_error, 400)


def _load_pack_extension_from_disk(
    pack_id: str, pack_name: str, local_id: str, plugin_dir: Path
) -> PackExtension | None:
    manifest_path = plugin_dir / "plugin.json"
    if not manifest_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(manifest, dict):
        return None
    try:
        _, schema_fields, defaults, int_fields = _parse_config_schema(manifest.get("config_schema"))
    except PackError:
        return None

    targets_raw = manifest.get("targets")
    if not isinstance(targets_raw, list):
        return None
    targets = tuple(
        cast(TargetType, t) for t in targets_raw if isinstance(t, str) and t in EXTENSIBLE_TARGETS
    )
    if not targets:
        return None
    pages_raw = manifest.get("pages")
    if isinstance(pages_raw, list) and pages_raw:
        pages = tuple(cast(PageKind, p) for p in pages_raw if isinstance(p, str) and p in ALLOWED_PAGES)
    else:
        pages = _default_pages_for_targets(targets)

    slot = str(manifest.get("slot", "none"))
    if slot not in ALLOWED_SLOTS:
        slot = "none"
    mount_raw = manifest.get("mount")
    mount = mount_raw if isinstance(mount_raw, dict) else {}
    assets_raw = manifest.get("assets") if isinstance(manifest.get("assets"), dict) else {}
    assets_dir = plugin_dir / "assets"

    def _build_asset_urls(key: str) -> tuple[str, ...]:
        items = assets_raw.get(key) if isinstance(assets_raw, dict) else None
        if not isinstance(items, list):
            return ()
        urls: list[str] = []
        for rel in items:
            if not isinstance(rel, str):
                continue
            file_path = assets_dir / rel
            if not file_path.is_file():
                continue
            try:
                digest = hashlib.sha256(file_path.read_bytes()).hexdigest()[:8]
            except OSError:
                continue
            urls.append(f"/media/plugins/{pack_id}/{local_id}/{rel}?v={digest}")
        return tuple(urls)

    def _build_icon_override_urls() -> dict[str, str]:
        raw_map = manifest.get("icon_overrides")
        if not isinstance(raw_map, dict) or not assets_dir.is_dir():
            return {}
        assets_root = assets_dir.resolve()
        resolved: dict[str, str] = {}
        for icon_name, rel in raw_map.items():
            if not isinstance(icon_name, str) or icon_name not in ALLOWED_OVERRIDE_ICONS:
                continue
            if not isinstance(rel, str):
                continue
            try:
                norm_rel = _normalize_asset_rel(rel, ".svg")
            except PackError:
                continue
            file_path = (assets_dir / norm_rel).resolve()
            if not file_path.is_relative_to(assets_root) or not file_path.is_file():
                continue
            try:
                digest = hashlib.sha256(file_path.read_bytes()).hexdigest()[:8]
            except OSError:
                continue
            resolved[icon_name] = f"/media/plugins/{pack_id}/{local_id}/{norm_rel}?v={digest}"
        return resolved

    return PackExtension(
        pack_id=pack_id,
        pack_name=pack_name,
        local_id=local_id,
        name=str(manifest.get("name", local_id)),
        name_en=str(manifest.get("name_en", "")),
        description=str(manifest.get("description", "")),
        description_en=str(manifest.get("description_en", "")),
        version=str(manifest.get("version", "1.0.0")),
        icon=str(manifest.get("icon", "puzzle")),
        targets=targets,
        pages=pages,
        slot=slot,
        mount={
            "tag": str(mount.get("tag", "div"))
            if str(mount.get("tag", "div")) in ALLOWED_MOUNT_TAGS
            else "div",
            "class": str(mount.get("class", "")),
            "aria_label": str(mount.get("aria_label", "")),
        },
        static_css=_build_asset_urls("css"),
        static_js=_build_asset_urls("js"),
        config_schema=schema_fields,
        defaults=defaults,
        int_fields=int_fields,
        tokens=sanitize_theme_tokens(manifest.get("tokens"), strict=False),
        icon_overrides=_build_icon_override_urls(),
    )


def load_pack_extensions(config: Config | None) -> list[PackExtension]:
    if config is None:
        return []
    data_root = config.data.resolve()
    index_path = _packs_index_path(data_root)
    try:
        st = index_path.stat()
        stat_key: tuple[int, int] | None = (st.st_mtime_ns, st.st_size)
    except OSError:
        stat_key = None

    cached = _PACK_CACHE.get(data_root)
    if cached is not None and cached[0] == stat_key:
        return list(cached[1])

    if stat_key is None:
        _PACK_CACHE[data_root] = (None, [])
        return []

    packs = _read_index(data_root)
    loaded: list[PackExtension] = []
    packs_dir = _packs_store_dir(data_root)
    for pack_entry in packs:
        pack_id = str(pack_entry.get("id", ""))
        pack_name = str(pack_entry.get("name", pack_id))
        if not PACK_ID_RE.match(pack_id) or pack_id == OFFICIAL_PACK_ID:
            continue
        pack_dir = packs_dir / pack_id
        plugins_meta = pack_entry.get("plugins")
        if not isinstance(plugins_meta, list):
            continue
        for pmeta in plugins_meta:
            if not isinstance(pmeta, dict):
                continue
            local_id = str(pmeta.get("local_id", ""))
            if not EXT_ID_RE.match(local_id):
                continue
            ext = _load_pack_extension_from_disk(
                pack_id, pack_name, local_id, pack_dir / "plugins" / local_id
            )
            if ext is not None:
                loaded.append(ext)

    _PACK_CACHE[data_root] = (stat_key, loaded)
    return list(loaded)


def list_packs(config: Config) -> list[dict[str, Any]]:
    from app.extensions.registry import builtin_extensions

    builtins = builtin_extensions()
    official_entry: dict[str, Any] = {
        "id": OFFICIAL_PACK_ID,
        "name": OFFICIAL_PACK_NAME,
        "name_en": "SiteFlow Official Plugins",
        "description": "SiteFlow 内置官方扩展插件集，覆盖博客、空间与简历。",
        "description_en": "Built-in official SiteFlow extensions for blogs, spaces, and resumes.",
        "version": "2.0.0",
        "author": "SiteFlow",
        "homepage": "",
        "builtin": True,
        "source_type": "builtin",
        "source_url": "",
        "installed_at": "",
        "updated_at": "",
        "plugin_count": len(builtins),
        "plugins": [
            {
                "id": ext.id,
                "local_id": ext.id,
                "name": ext.name,
                "name_key": ext.name_key,
                "description": ext.description,
                "description_key": ext.description_key,
                "version": ext.version,
                "icon": ext.icon,
                "targets": list(ext.targets),
            }
            for ext in builtins
        ],
    }
    out = [official_entry]
    for entry in _read_index(config.data):
        item = dict(entry)
        item["builtin"] = False
        out.append(item)
    return out


def install_pack_from_url(config: Config, url: str) -> dict[str, Any]:
    canonical_url, archive = _download_pack_archive(url)
    tmp_root = config.data / "tmp" / f"pack_url_{secrets.token_hex(8)}"
    tmp_root.mkdir(parents=True, exist_ok=True)
    try:
        meta, staged_dir = _stage_and_validate_pack(archive, tmp_root)
        pack_id = meta["id"]
        existing = _read_index(config.data)
        if any(item.get("id") == pack_id for item in existing):
            raise PackError(f"插件包 {pack_id} 已订阅，请使用同步功能更新", 409)
        if len(existing) >= MAX_PACKS:
            raise PackError(f"已达到插件包订阅数量上限（{MAX_PACKS}）", 400)
        now = datetime.now(UTC).isoformat()
        record = {
            **meta,
            "builtin": False,
            "source_type": "url",
            "source_url": canonical_url,
            "installed_at": now,
            "updated_at": now,
        }
        _swap_pack_dir(config, pack_id, staged_dir)
        existing.append(record)
        _write_index(config.data, existing)
        invalidate_pack_cache(config.data)
        return record
    finally:
        remove_tree(tmp_root)


def install_pack_from_zip(config: Config, raw: bytes, *, replace: bool = True) -> dict[str, Any]:
    if not raw:
        raise PackError("上传的插件包文件不能为空", 422)
    if len(raw) > MAX_PACK_ARCHIVE_BYTES:
        raise PackError("插件包文件不能超过 10MB", 413)
    tmp_root = config.data / "tmp" / f"pack_zip_{secrets.token_hex(8)}"
    tmp_root.mkdir(parents=True, exist_ok=True)
    try:
        meta, staged_dir = _stage_and_validate_pack(raw, tmp_root)
        pack_id = meta["id"]
        existing = _read_index(config.data)
        match_idx = next((i for i, item in enumerate(existing) if item.get("id") == pack_id), None)
        if match_idx is not None and not replace:
            raise PackError(f"插件包 {pack_id} 已存在", 409)
        if match_idx is None and len(existing) >= MAX_PACKS:
            raise PackError(f"已达到插件包订阅数量上限（{MAX_PACKS}）", 400)
        now = datetime.now(UTC).isoformat()
        installed_at = str(existing[match_idx].get("installed_at", now)) if match_idx is not None else now
        record = {
            **meta,
            "builtin": False,
            "source_type": "upload",
            "source_url": "",
            "installed_at": installed_at,
            "updated_at": now,
        }
        _swap_pack_dir(config, pack_id, staged_dir)
        if match_idx is not None:
            existing[match_idx] = record
        else:
            existing.append(record)
        _write_index(config.data, existing)
        invalidate_pack_cache(config.data)
        return record
    finally:
        remove_tree(tmp_root)


def sync_pack(config: Config, pack_id: str) -> dict[str, Any]:
    if pack_id == OFFICIAL_PACK_ID:
        raise PackError("官方内置插件包无需远程同步", 400)
    if not PACK_ID_RE.match(pack_id):
        raise PackError("无效的插件包标识", 400)
    existing = _read_index(config.data)
    match_idx = next((i for i, item in enumerate(existing) if item.get("id") == pack_id), None)
    if match_idx is None:
        raise PackError("插件包不存在", 404)
    current = existing[match_idx]
    source_url = str(current.get("source_url", ""))
    if current.get("source_type") != "url" or not source_url:
        raise PackError("本地上传的插件包不支持远程同步，请重新上传 ZIP", 400)

    canonical_url, archive = _download_pack_archive(source_url)
    tmp_root = config.data / "tmp" / f"pack_sync_{secrets.token_hex(8)}"
    tmp_root.mkdir(parents=True, exist_ok=True)
    try:
        meta, staged_dir = _stage_and_validate_pack(archive, tmp_root)
        if meta["id"] != pack_id:
            raise PackError("远程插件包标识与当前订阅不一致", 422)
        now = datetime.now(UTC).isoformat()
        record = {
            **meta,
            "builtin": False,
            "source_type": "url",
            "source_url": canonical_url,
            "installed_at": str(current.get("installed_at", now)),
            "updated_at": now,
        }
        _swap_pack_dir(config, pack_id, staged_dir)
        existing[match_idx] = record
        _write_index(config.data, existing)
        invalidate_pack_cache(config.data)
        return record
    finally:
        remove_tree(tmp_root)


def _extract_local_media_strings(value: object, out: set[str]) -> None:
    if isinstance(value, str):
        if value.startswith(("/media/blog/", "/media/ext/")):
            out.add(value)
    elif isinstance(value, dict):
        for item in value.values():
            _extract_local_media_strings(item, out)
    elif isinstance(value, list):
        for item in value:
            _extract_local_media_strings(item, out)


def delete_pack(config: Config, pack_id: str, db: Session) -> dict[str, Any]:
    if pack_id == OFFICIAL_PACK_ID:
        raise PackError("不能取消订阅官方内置插件包", 400)
    if not PACK_ID_RE.match(pack_id):
        raise PackError("无效的插件包标识", 400)
    existing = _read_index(config.data)
    remaining = [item for item in existing if item.get("id") != pack_id]
    if len(remaining) == len(existing):
        raise PackError("插件包不存在", 404)

    prefix = f"{pack_id}."
    cleaned_projects = 0
    stale_media: list[tuple[str, set[str], set[str]]] = []
    projects = list(db.execute(select(Project).where(Project.type.in_(EXTENSIBLE_TARGETS))).scalars())
    now = datetime.now(UTC).isoformat()
    for project in projects:
        try:
            parsed = json.loads(project.content or "{}")
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        ext_map = parsed.get("extensions")
        if not isinstance(ext_map, dict):
            continue
        removed_keys = [
            key for key in list(ext_map.keys()) if isinstance(key, str) and key.startswith(prefix)
        ]
        if not removed_keys:
            continue
        removed_urls: set[str] = set()
        for key in removed_keys:
            _extract_local_media_strings(ext_map.pop(key, None), removed_urls)
        if not ext_map:
            parsed.pop("extensions", None)
        remaining_urls: set[str] = set()
        if removed_urls:
            _extract_local_media_strings(parsed, remaining_urls)
            stale_media.append((project.slug, removed_urls, remaining_urls))
        project.content = json.dumps(parsed, ensure_ascii=False)
        project.updated_at = now
        cleaned_projects += 1

    if cleaned_projects:
        db.commit()
    for slug, removed_urls, remaining_urls in stale_media:
        for url in removed_urls - remaining_urls:
            delete_project_media_url(config, slug, url)

    remove_tree(_packs_store_dir(config.data) / pack_id)
    _write_index(config.data, remaining)
    invalidate_pack_cache(config.data)
    return {"pack_id": pack_id, "cleaned_projects": cleaned_projects}


def resolve_pack_asset_path(
    config: Config,
    pack_id: str,
    plugin_id: str,
    asset_path: str,
) -> Path | None:
    if pack_id == OFFICIAL_PACK_ID or "--" in pack_id or not PACK_ID_RE.match(pack_id):
        return None
    if not EXT_ID_RE.match(plugin_id):
        return None
    if not asset_path or "\\" in asset_path or "\x00" in asset_path or asset_path.startswith("/"):
        return None
    parts = PurePosixPath(asset_path).parts
    if not parts or any(part in ("", ".", "..") or part.startswith(".") for part in parts):
        return None
    assets_root = (_packs_store_dir(config.data) / pack_id / "plugins" / plugin_id / "assets").resolve()
    if not assets_root.is_dir():
        return None
    target = assets_root.joinpath(*parts).resolve()
    if not target.is_relative_to(assets_root) or not target.is_file():
        return None
    if target.suffix.lower() not in ALLOWED_ASSET_EXTS:
        return None
    return target
