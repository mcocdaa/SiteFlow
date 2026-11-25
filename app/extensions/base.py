import math
import re
from collections.abc import Collection
from dataclasses import dataclass
from typing import Any, ClassVar, Literal, Protocol
from urllib.parse import urlparse

from markupsafe import Markup

from app.models import Project
from app.plugins.base import InvalidContent
from app.surface import Capability
from app.templating import templates

TargetType = Literal["blog", "space", "resume"]
PageKind = Literal["list", "post", "space", "resume", "bottle"]
SlotKind = Literal["start", "main_start", "end"]
StructuredSlotKind = Literal["header", "aside", "overlay", "footer", "title_deco", "icons"]

EXTENSIBLE_TARGETS: tuple[TargetType, ...] = ("blog", "space", "resume")
STRUCTURED_SLOTS: tuple[StructuredSlotKind, ...] = (
    "header",
    "aside",
    "overlay",
    "footer",
    "title_deco",
    "icons",
)
TARGET_CAPABILITIES: dict[TargetType, frozenset[Capability]] = {
    "blog": frozenset({"has_content", "has_posts", "has_items", "supports_layout"}),
    "space": frozenset({"has_children", "has_items", "supports_layout"}),
    "resume": frozenset({"has_content", "is_personal_profile", "has_items"}),
}
OFFICIAL_PACK_ID = "official"
OFFICIAL_PACK_NAME = "SiteFlow 官方插件包"


def capabilities_for_target(target: TargetType) -> frozenset[Capability]:
    return TARGET_CAPABILITIES.get(target, frozenset())


def infer_capabilities_from_targets(
    targets: Collection[TargetType],
) -> tuple[frozenset[Capability], frozenset[Capability]]:
    target_set = frozenset(t for t in targets if t in TARGET_CAPABILITIES)
    if not target_set or target_set == frozenset(EXTENSIBLE_TARGETS):
        return frozenset(), frozenset()
    if target_set == frozenset({"blog"}):
        return frozenset({"has_posts"}), frozenset()
    if target_set == frozenset({"space"}):
        return frozenset({"has_children"}), frozenset()
    if target_set == frozenset({"resume"}):
        return frozenset({"is_personal_profile"}), frozenset()
    if target_set == frozenset({"blog", "space"}):
        return frozenset({"supports_layout"}), frozenset()
    if target_set == frozenset({"blog", "resume"}):
        return frozenset({"has_content"}), frozenset()
    if target_set == frozenset({"space", "resume"}):
        return frozenset(), frozenset({"has_posts"})
    return frozenset(), frozenset()


PACK_ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
EXT_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
QUALIFIED_EXT_ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,31}\.[a-z][a-z0-9_]{1,31}$")
LAYOUT_MODE_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
BLOG_MEDIA_RE = re.compile(r"^/media/blog/([a-z0-9][a-z0-9_-]{0,63})/([a-z0-9][a-z0-9_-]{0,63}\.webp)$")
PROJECT_MEDIA_RE = re.compile(
    r"^/media/(blog|ext)/([a-z0-9][a-z0-9_-]{0,63})/([a-z0-9][a-z0-9_-]{0,63}\.webp)$"
)
PROJECT_MEDIA_SVG_RE = re.compile(
    r"^/media/(blog|ext)/([a-z0-9][a-z0-9_-]{0,63})/(avatar-[0-9a-f]{16}\.svg)$"
)
_UNSAFE_URL_RE = re.compile(r"[\x00-\x20\x7f\"'<>\\`]")
MAX_IMAGE_URL = 500
MAX_LINK_URL = 500
MAX_THEME_TOKEN_LEN = 160
MAX_ICON_URL_LEN = 300

_COLOR_THEME_TOKENS = frozenset(
    {
        "--accent",
        "--accent-soft",
        "--bg",
        "--surface",
        "--bg-card",
        "--bg-hover",
        "--text",
        "--text-muted",
        "--muted",
        "--border",
        "--border-hover",
    }
)
_LENGTH_THEME_TOKENS = frozenset({"--radius-card", "--radius-btn"})
_FONT_THEME_TOKENS = frozenset({"--font-family"})
_SHADOW_THEME_TOKENS = frozenset({"--shadow-hover"})
ALLOWED_THEME_TOKENS: frozenset[str] = (
    _COLOR_THEME_TOKENS | _LENGTH_THEME_TOKENS | _FONT_THEME_TOKENS | _SHADOW_THEME_TOKENS
)
ALLOWED_OVERRIDE_ICONS: frozenset[str] = frozenset(
    {
        "folder",
        "layers",
        "file-text",
        "book-open",
        "globe",
        "link",
        "external-link",
        "mail",
        "phone",
        "map-pin",
        "briefcase",
        "graduation-cap",
        "wrench",
        "search",
        "settings",
        "pin",
        "lock",
        "maximize",
        "printer",
        "arrow-left",
        "arrow-right",
        "notebook-pen",
    }
)

_CSS_FORBIDDEN_RE = re.compile(
    r"[\x00-\x1f\x7f;{}<>\\`@]|/\*|\*/|<!--|-->|"
    r"(?:url|expression|image-set|var)\s*\(|"
    r"(?:javascript|vbscript|data|behavior|-moz-binding)\s*:|@import",
    re.IGNORECASE,
)
_CSS_HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_CSS_FUNC_COLOR_RE = re.compile(
    r"^(?:rgb|rgba|hsl|hsla)\(\s*[0-9.]+%?(?:\s*[,/\s]\s*[0-9.]+%?){2,3}\s*\)$",
    re.IGNORECASE,
)
_CSS_NAMED_COLORS = frozenset({"transparent", "currentcolor", "white", "black"})
_CSS_LENGTH_RE = re.compile(r"^(?:0|[0-9]{1,3}(?:\.[0-9]{1,2})?(?:px|rem|em|%))$")
_CSS_FONT_PART_RE = re.compile(r"^[A-Za-z0-9_-]+(?:\s+[A-Za-z0-9_-]+)*$")
_CSS_SHADOW_RE = re.compile(
    r"^(?:inset\s+)?(?:-?[0-9]{1,3}(?:\.[0-9]{1,2})?(?:px)?\s+){2,4}"
    r"(?:#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})|"
    r"(?:rgb|rgba|hsl|hsla)\(\s*[0-9.]+%?(?:\s*[,/\s]\s*[0-9.]+%?){2,3}\s*\))$",
    re.IGNORECASE,
)
_SAFE_ICON_PLUGIN_RE = re.compile(
    r"^/media/plugins/[a-z][a-z0-9-]{1,31}/[a-z][a-z0-9_]{1,31}/[A-Za-z0-9_/-]+\.svg$"
)
_SAFE_ICON_STATIC_RE = re.compile(r"^/static/[A-Za-z0-9_/-]+\.svg$")
_SAFE_ICON_QUERY_RE = re.compile(r"^v=[0-9a-fA-F]{6,16}$")


@dataclass(frozen=True)
class ConfigOption:
    value: str
    label_key: str
    label_default: str

    def as_dict(self) -> dict[str, str]:
        return {
            "value": self.value,
            "label_key": self.label_key,
            "label_default": self.label_default,
        }


@dataclass(frozen=True)
class ConfigField:
    key: str
    kind: Literal[
        "select",
        "text",
        "textarea",
        "number",
        "range",
        "boolean",
        "image_url",
        "character_picker",
        "secret",
    ]
    label_key: str
    label_default: str
    help_key: str = ""
    help_default: str = ""
    placeholder_key: str = ""
    placeholder_default: str = ""
    options: tuple[ConfigOption, ...] = ()
    min_value: float | None = None
    max_value: float | None = None
    step: float | None = None
    max_length: int = 200
    upload_kind: str = ""
    group: str = ""
    group_key: str = ""
    group_default: str = ""
    accept: str = ""
    rows: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "kind": self.kind,
            "label_key": self.label_key,
            "label_default": self.label_default,
            "help_key": self.help_key,
            "help_default": self.help_default,
            "placeholder_key": self.placeholder_key,
            "placeholder_default": self.placeholder_default,
            "options": [opt.as_dict() for opt in self.options],
            "min_value": self.min_value,
            "max_value": self.max_value,
            "step": self.step,
            "max_length": self.max_length,
            "upload_kind": self.upload_kind,
            "group": self.group,
            "group_key": self.group_key,
            "group_default": self.group_default,
            "accept": self.accept,
            "rows": self.rows,
        }


def sanitize_text(value: object, limit: int) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def sanitize_bool(value: object, default: bool = False, *, strict: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "1", "yes", "on"):
            return True
        if lowered in ("false", "0", "no", "off", ""):
            return False
    if strict:
        raise InvalidContent("布尔配置值格式不正确")
    return default


def sanitize_float(
    value: object,
    default: float,
    *,
    low: float,
    high: float,
    step: float | None = None,
    strict: bool = False,
) -> float:
    if value is None:
        return default
    if isinstance(value, bool):
        if strict:
            raise InvalidContent("数值配置格式不正确")
        return default
    try:
        if isinstance(value, (int, float)):
            num = float(value)
        elif isinstance(value, str):
            text = value.strip()
            if not text:
                return default
            num = float(text)
        else:
            raise TypeError
    except (ValueError, TypeError) as exc:
        if strict:
            raise InvalidContent("数值配置格式不正确") from exc
        return default
    if not math.isfinite(num):
        if strict:
            raise InvalidContent("数值配置格式不正确")
        return default
    if num < low or num > high:
        if strict:
            raise InvalidContent(f"数值超出允许范围（{low} ~ {high}）")
        num = min(max(num, low), high)
    if step is not None and step > 0:
        snapped = round(round(num / step) * step, 4)
        num = min(max(snapped, low), high)
    return num


def sanitize_int(
    value: object,
    default: int,
    *,
    low: int,
    high: int,
    strict: bool = False,
) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        if strict:
            raise InvalidContent("整数配置格式不正确")
        return default
    num: int
    if isinstance(value, int):
        num = value
    elif isinstance(value, float):
        if not math.isfinite(value) or (strict and not value.is_integer()):
            if strict:
                raise InvalidContent("整数配置格式不正确")
            return default
        num = round(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return default
        try:
            num = int(text)
        except ValueError as exc:
            try:
                fval = float(text)
            except ValueError:
                if strict:
                    raise InvalidContent("整数配置格式不正确") from exc
                return default
            if not math.isfinite(fval) or (strict and not fval.is_integer()):
                if strict:
                    raise InvalidContent("整数配置格式不正确") from exc
                return default
            num = round(fval)
    else:
        if strict:
            raise InvalidContent("整数配置格式不正确")
        return default
    if num < low or num > high:
        if strict:
            raise InvalidContent(f"整数超出允许范围（{low} ~ {high}）")
        num = min(max(num, low), high)
    return num


def sanitize_choice(
    value: object,
    allowed: Collection[str],
    default: str,
    *,
    strict: bool = False,
) -> str:
    if value is None:
        return default
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned in allowed:
            return cleaned
    if strict:
        raise InvalidContent("选项值不受支持")
    return default


def sanitize_image_url(
    value: object,
    default: str = "",
    *,
    project_slug: str | None = None,
    strict: bool = False,
    allow_svg_media: bool = False,
) -> str:
    if value is None:
        return default
    if not isinstance(value, str):
        if strict:
            raise InvalidContent("图片链接格式不合法，仅支持 http(s):// 或已上传的站内图片")
        return default
    text = value.strip()
    if not text:
        return ""
    if len(text) > MAX_IMAGE_URL or _UNSAFE_URL_RE.search(text):
        if strict:
            raise InvalidContent("图片链接格式不合法，仅支持 http(s):// 或已上传的站内图片")
        return default
    if text.startswith("/"):
        match = PROJECT_MEDIA_RE.match(text)
        if match and (project_slug is None or match.group(2) == project_slug):
            return text
        if allow_svg_media:
            svg_match = PROJECT_MEDIA_SVG_RE.match(text)
            if svg_match and (project_slug is None or svg_match.group(2) == project_slug):
                return text
        if strict:
            raise InvalidContent("图片链接格式不合法，仅支持 http(s):// 或已上传的站内图片")
        return default
    parsed = urlparse(text)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
        if strict:
            raise InvalidContent("图片链接格式不合法，仅支持 http(s):// 或已上传的站内图片")
        return default
    return text


def sanitize_link_url(value: object, *, strict: bool = False) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        if strict:
            raise InvalidContent("链接格式不合法，仅支持 http(s):// 或站内相对路径")
        return ""
    text = value.strip()
    if not text:
        return ""
    if len(text) > MAX_LINK_URL or _UNSAFE_URL_RE.search(text):
        if strict:
            raise InvalidContent("链接格式不合法，仅支持 http(s):// 或站内相对路径")
        return ""
    if text.startswith("/"):
        if text.startswith("//") or ".." in text.split("/"):
            if strict:
                raise InvalidContent("链接格式不合法，仅支持 http(s):// 或站内相对路径")
            return ""
        return text
    parsed = urlparse(text)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
        if strict:
            raise InvalidContent("链接格式不合法，仅支持 http(s):// 或站内相对路径")
        return ""
    return text


def sanitize_lines(
    value: object,
    *,
    max_items: int = 10,
    item_limit: int = 120,
    default: list[str] | None = None,
    strict: bool = False,
) -> list[str]:
    if value is None:
        return list(default or [])
    raw_items: list[object]
    if isinstance(value, str):
        raw_items = list(value.splitlines())
    elif isinstance(value, list):
        raw_items = value
    else:
        if strict:
            raise InvalidContent("列表配置格式不正确")
        return list(default or [])
    cleaned: list[str] = []
    for entry in raw_items:
        if not isinstance(entry, str):
            if strict:
                raise InvalidContent("列表配置项必须是文本")
            continue
        item = entry.strip()[:item_limit]
        if item:
            cleaned.append(item)
            if len(cleaned) >= max_items:
                break
    return cleaned


def sanitize_theme_token_value(name: str, value: object, *, strict: bool = False) -> str:
    if name not in ALLOWED_THEME_TOKENS:
        if strict:
            raise InvalidContent(f"不支持的主题样式变量：{name}")
        return ""
    if not isinstance(value, str):
        if strict:
            raise InvalidContent(f"主题样式变量 {name} 的值必须是文本")
        return ""
    cleaned = value.strip()
    if not cleaned or len(cleaned) > MAX_THEME_TOKEN_LEN:
        if strict:
            raise InvalidContent(f"主题样式变量 {name} 的值不能为空或超长")
        return ""
    if _CSS_FORBIDDEN_RE.search(cleaned):
        if strict:
            raise InvalidContent(f"主题样式变量 {name} 包含不安全的 CSS 语法")
        return ""
    if name in _COLOR_THEME_TOKENS:
        if (
            _CSS_HEX_COLOR_RE.match(cleaned)
            or _CSS_FUNC_COLOR_RE.match(cleaned)
            or cleaned.lower() in _CSS_NAMED_COLORS
        ):
            return cleaned
    elif name in _LENGTH_THEME_TOKENS:
        if _CSS_LENGTH_RE.match(cleaned):
            return cleaned
    elif name in _FONT_THEME_TOKENS:
        parts = [part.strip() for part in cleaned.split(",")]
        if 1 <= len(parts) <= 8:
            normalized_parts: list[str] = []
            valid = True
            for part in parts:
                if len(part) >= 2 and part[0] == part[-1] and part[0] in ("'", '"'):
                    inner = part[1:-1].strip()
                else:
                    inner = part
                if not inner or len(inner) > 40 or not _CSS_FONT_PART_RE.match(inner):
                    valid = False
                    break
                normalized_parts.append(inner)
            if valid:
                return ", ".join(normalized_parts)
    elif name in _SHADOW_THEME_TOKENS:
        layers = [layer.strip() for layer in re.split(r",(?![^(]*\))", cleaned)]
        if 1 <= len(layers) <= 3 and all(_CSS_SHADOW_RE.match(layer) for layer in layers):
            return ", ".join(layers)
    if strict:
        raise InvalidContent(f"主题样式变量 {name} 的值格式不受支持")
    return ""


def sanitize_theme_tokens(raw: object, *, strict: bool = False) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        if strict:
            raise InvalidContent("主题样式变量必须是对象")
        return {}
    out: dict[str, str] = {}
    for key, val in raw.items():
        if not isinstance(key, str):
            if strict:
                raise InvalidContent("主题样式变量名必须是文本")
            continue
        cleaned_key = key.strip()
        cleaned_val = sanitize_theme_token_value(cleaned_key, val, strict=strict)
        if cleaned_val:
            out[cleaned_key] = cleaned_val
    return out


def sanitize_icon_override_url(value: object, *, strict: bool = False) -> str:
    if not isinstance(value, str):
        if strict:
            raise InvalidContent("图标覆盖地址必须是文本")
        return ""
    cleaned = value.strip()
    if not cleaned or len(cleaned) > MAX_ICON_URL_LEN or _UNSAFE_URL_RE.search(cleaned):
        if strict:
            raise InvalidContent("图标覆盖地址格式不合法")
        return ""
    path_part, sep, query_part = cleaned.partition("?")
    if sep and not _SAFE_ICON_QUERY_RE.match(query_part):
        if strict:
            raise InvalidContent("图标覆盖地址包含非法查询参数")
        return ""
    if "//" in path_part or "\\" in path_part:
        if strict:
            raise InvalidContent("图标覆盖地址路径不合法")
        return ""
    segments = [seg for seg in path_part.split("/") if seg]
    if any(seg in (".", "..") or seg.startswith(".") for seg in segments):
        if strict:
            raise InvalidContent("图标覆盖地址包含非法路径片段")
        return ""
    if not (_SAFE_ICON_PLUGIN_RE.match(path_part) or _SAFE_ICON_STATIC_RE.match(path_part)):
        if strict:
            raise InvalidContent("图标覆盖仅允许站内插件或静态 SVG 路径")
        return ""
    return cleaned


def sanitize_icon_overrides(raw: object, *, strict: bool = False) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        if strict:
            raise InvalidContent("图标覆盖配置必须是对象")
        return {}
    out: dict[str, str] = {}
    for key, val in raw.items():
        if not isinstance(key, str):
            if strict:
                raise InvalidContent("图标名称必须是文本")
            continue
        cleaned_key = key.strip()
        if cleaned_key not in ALLOWED_OVERRIDE_ICONS:
            if strict:
                raise InvalidContent(f"不支持覆盖的图标名称：{cleaned_key}")
            continue
        cleaned_url = sanitize_icon_override_url(val, strict=strict)
        if cleaned_url:
            out[cleaned_key] = cleaned_url
    return out


class Extension(Protocol):
    @property
    def id(self) -> str: ...
    @property
    def targets(self) -> tuple[TargetType, ...]: ...
    @property
    def requires(self) -> frozenset[Capability]: ...
    @property
    def excludes(self) -> frozenset[Capability]: ...
    @property
    def pack_id(self) -> str: ...
    @property
    def pack_name(self) -> str: ...
    @property
    def name(self) -> str: ...
    @property
    def name_key(self) -> str: ...
    @property
    def description(self) -> str: ...
    @property
    def description_key(self) -> str: ...
    @property
    def version(self) -> str: ...
    @property
    def icon(self) -> str: ...
    @property
    def default_config(self) -> dict[str, Any]: ...
    @property
    def config_schema(self) -> tuple[ConfigField, ...]: ...
    @property
    def media_kinds(self) -> tuple[str, ...]: ...
    @property
    def static_css(self) -> tuple[str, ...]: ...
    @property
    def static_js(self) -> tuple[str, ...]: ...
    @property
    def list_card_template(self) -> str | None: ...
    @property
    def post_header_template(self) -> str | None: ...
    @property
    def body_start_template(self) -> str | None: ...
    @property
    def main_start_template(self) -> str | None: ...
    @property
    def body_end_template(self) -> str | None: ...
    @property
    def editor_fields_template(self) -> str | None: ...

    def secret_fields(self) -> set[str]: ...

    def matches_capabilities(self, caps: frozenset[Capability]) -> bool: ...

    def merge_config(
        self,
        existing: dict[str, Any] | None,
        incoming: dict[str, Any] | None,
    ) -> dict[str, Any]: ...

    def redact_config(self, config: dict[str, Any]) -> tuple[dict[str, Any], dict[str, bool]]: ...

    def normalize_config(
        self,
        raw: object,
        *,
        strict: bool = False,
        project_slug: str | None = None,
    ) -> dict[str, Any]: ...

    def normalize_post_meta(
        self,
        raw_meta: dict[str, Any],
        *,
        strict: bool = False,
        project_slug: str | None = None,
    ) -> dict[str, Any]: ...

    def body_classes(
        self,
        *,
        page: PageKind,
        config: dict[str, Any],
    ) -> list[str]: ...

    def local_media_urls(self, config: dict[str, Any]) -> list[str]: ...

    def render_list_context(
        self,
        *,
        project: Project,
        blog: dict[str, Any],
        posts: list[dict[str, Any]],
        config: dict[str, Any],
    ) -> dict[str, Any]: ...

    def render_post_context(
        self,
        *,
        project: Project,
        blog: dict[str, Any],
        post: dict[str, Any],
        config: dict[str, Any],
    ) -> dict[str, Any]: ...

    def render_space_context(
        self,
        *,
        project: Project,
        content: dict[str, Any],
        config: dict[str, Any],
    ) -> dict[str, Any]: ...

    def render_resume_context(
        self,
        *,
        project: Project,
        content: dict[str, Any],
        config: dict[str, Any],
    ) -> dict[str, Any]: ...

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
    ) -> dict[str, Any]: ...

    def render_editor_context(
        self,
        *,
        project: Project,
        post: dict[str, Any] | None,
        config: dict[str, Any],
    ) -> dict[str, Any]: ...

    def inject_body_html(
        self,
        *,
        slot: Literal["start", "end"],
        page: PageKind,
        project: Project,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> Markup: ...

    def inject_html(
        self,
        *,
        slot: SlotKind,
        page: PageKind,
        project: Project,
        content: dict[str, Any],
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> Markup: ...

    def theme_tokens(
        self,
        page: PageKind,
        config: dict[str, Any],
    ) -> dict[str, str]: ...

    def icon_overrides(
        self,
        page: PageKind,
        config: dict[str, Any],
    ) -> dict[str, str]: ...

    def layout_mode(
        self,
        page: PageKind,
        config: dict[str, Any],
    ) -> str | None: ...

    def inject_slot(
        self,
        slot: StructuredSlotKind | SlotKind,
        page: PageKind,
        project: Project,
        content: dict[str, Any],
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> Markup: ...


class BaseExtension:
    id: str = ""
    targets: tuple[TargetType, ...] = ("blog",)
    requires: frozenset[Capability] = frozenset()
    excludes: frozenset[Capability] = frozenset()
    pack_id: str = OFFICIAL_PACK_ID
    pack_name: str = OFFICIAL_PACK_NAME
    name: str = ""
    name_key: str = ""
    description: str = ""
    description_key: str = ""
    version: str = "1.0.0"
    icon: str = "puzzle"
    default_config: ClassVar[dict[str, Any]] = {}
    config_schema: tuple[ConfigField, ...] = ()
    media_kinds: tuple[str, ...] = ()
    static_css: tuple[str, ...] = ()
    static_js: tuple[str, ...] = ()
    list_card_template: str | None = None
    post_header_template: str | None = None
    body_start_template: str | None = None
    main_start_template: str | None = None
    body_end_template: str | None = None
    editor_fields_template: str | None = None
    slot_templates: ClassVar[dict[str, str]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if "requires" not in cls.__dict__ and "excludes" not in cls.__dict__ and "targets" in cls.__dict__:
            cls.requires, cls.excludes = infer_capabilities_from_targets(cls.targets)

    def matches_capabilities(self, caps: frozenset[Capability]) -> bool:
        req = self.requires
        exc = self.excludes
        no_inst_caps = "requires" not in self.__dict__ and "excludes" not in self.__dict__
        if no_inst_caps and (
            type(self) is BaseExtension
            or (
                "targets" in self.__dict__
                and "requires" not in type(self).__dict__
                and "excludes" not in type(self).__dict__
            )
        ):
            req, exc = infer_capabilities_from_targets(self.targets)
        return req.issubset(caps) and exc.isdisjoint(caps)

    def secret_fields(self) -> set[str]:
        return {field.key for field in self.config_schema if field.kind == "secret"}

    def merge_config(
        self,
        existing: dict[str, Any] | None,
        incoming: dict[str, Any] | None,
    ) -> dict[str, Any]:
        base = dict(existing) if isinstance(existing, dict) else {}
        inc = dict(incoming) if isinstance(incoming, dict) else {}
        secret_keys = self.secret_fields()
        clear_keys = {f"clear_{key}" for key in secret_keys}
        merged: dict[str, Any] = {k: v for k, v in base.items() if k not in clear_keys}
        for key, value in inc.items():
            if key in secret_keys or key in clear_keys:
                continue
            merged[key] = value
        for key in secret_keys:
            clear_flag = sanitize_bool(inc.get(f"clear_{key}"), False)
            if clear_flag:
                merged[key] = ""
            elif key in inc and isinstance(inc[key], str) and inc[key].strip():
                merged[key] = inc[key].strip()
            else:
                merged[key] = base.get(key, "")
        return merged

    def redact_config(self, config: dict[str, Any]) -> tuple[dict[str, Any], dict[str, bool]]:
        redacted = dict(config)
        secrets_set: dict[str, bool] = {}
        for key in sorted(self.secret_fields()):
            raw_val = redacted.get(key)
            secrets_set[key] = bool(isinstance(raw_val, str) and raw_val.strip())
            redacted[key] = ""
        return redacted, secrets_set

    def normalize_config(
        self,
        raw: object,
        *,
        strict: bool = False,
        project_slug: str | None = None,
    ) -> dict[str, Any]:
        return dict(self.default_config)

    def normalize_post_meta(
        self,
        raw_meta: dict[str, Any],
        *,
        strict: bool = False,
        project_slug: str | None = None,
    ) -> dict[str, Any]:
        return {}

    def body_classes(
        self,
        *,
        page: PageKind,
        config: dict[str, Any],
    ) -> list[str]:
        return []

    def local_media_urls(self, config: dict[str, Any]) -> list[str]:
        return []

    def render_list_context(
        self,
        *,
        project: Project,
        blog: dict[str, Any],
        posts: list[dict[str, Any]],
        config: dict[str, Any],
    ) -> dict[str, Any]:
        return {}

    def render_post_context(
        self,
        *,
        project: Project,
        blog: dict[str, Any],
        post: dict[str, Any],
        config: dict[str, Any],
    ) -> dict[str, Any]:
        return {}

    def render_space_context(
        self,
        *,
        project: Project,
        content: dict[str, Any],
        config: dict[str, Any],
    ) -> dict[str, Any]:
        return {}

    def render_resume_context(
        self,
        *,
        project: Project,
        content: dict[str, Any],
        config: dict[str, Any],
    ) -> dict[str, Any]:
        return {}

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
        if page == "list":
            resolved_posts = posts if posts is not None else content.get("posts", [])
            return self.render_list_context(
                project=project,
                blog=content,
                posts=resolved_posts if isinstance(resolved_posts, list) else [],
                config=config,
            )
        if page == "post":
            return self.render_post_context(
                project=project,
                blog=content,
                post=post or {},
                config=config,
            )
        if page == "space":
            return self.render_space_context(project=project, content=content, config=config)
        if page == "resume":
            return self.render_resume_context(project=project, content=content, config=config)
        return {}

    def render_editor_context(
        self,
        *,
        project: Project,
        post: dict[str, Any] | None,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        return {}

    def render_fragment(self, template_name: str, context: dict[str, Any]) -> Markup:
        template = templates.env.get_template(template_name)
        return Markup(template.render(**context))

    def inject_body_html(
        self,
        *,
        slot: Literal["start", "end"],
        page: PageKind,
        project: Project,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> Markup:
        template_name = self.body_start_template if slot == "start" else self.body_end_template
        if not template_name:
            return Markup("")
        return self.render_fragment(
            template_name,
            {
                "page": page,
                "project": project,
                "config": config,
                "ext_ctx": context,
            },
        )

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
        if slot == "start":
            return self.inject_body_html(
                slot="start",
                page=page,
                project=project,
                config=config,
                context=context,
            )
        if slot == "end":
            return self.inject_body_html(
                slot="end",
                page=page,
                project=project,
                config=config,
                context=context,
            )
        if not self.main_start_template:
            return Markup("")
        return self.render_fragment(
            self.main_start_template,
            {
                "page": page,
                "project": project,
                "content": content,
                "config": config,
                "ext_ctx": context,
            },
        )

    def theme_tokens(
        self,
        page: PageKind,
        config: dict[str, Any],
    ) -> dict[str, str]:
        return {}

    def icon_overrides(
        self,
        page: PageKind,
        config: dict[str, Any],
    ) -> dict[str, str]:
        return {}

    def layout_mode(
        self,
        page: PageKind,
        config: dict[str, Any],
    ) -> str | None:
        return None

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
        template_name = self.slot_templates.get(slot)
        if not template_name:
            return Markup("")
        return self.render_fragment(
            template_name,
            {
                "slot": slot,
                "page": page,
                "project": project,
                "content": content,
                "config": config,
                "ext_ctx": context,
            },
        )
