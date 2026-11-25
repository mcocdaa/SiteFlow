import hashlib
from typing import Any, ClassVar

from markupsafe import Markup

from app.extensions.base import (
    BaseExtension,
    ConfigField,
    ConfigOption,
    PageKind,
    SlotKind,
    TargetType,
    sanitize_bool,
    sanitize_choice,
    sanitize_link_url,
    sanitize_text,
)
from app.models import Project
from app.plugins.base import InvalidContent
from app.surface import Capability

TONES = ("info", "accent", "success", "warm")


class SpaceBannerExtension(BaseExtension):
    id = "space_banner"
    requires: frozenset[Capability] = frozenset({"has_children"})
    targets: tuple[TargetType, ...] = ("space",)
    name = "空间公告栏"
    name_key = "ext.space_banner.name"
    description = "在空间画廊顶部展示简洁的公告或欢迎横幅，支持色调切换、外链按钮与访客关闭。"
    description_key = "ext.space_banner.description"
    version = "1.0.0"
    icon = "megaphone"
    media_kinds = ()
    static_css = ("/static/css/ext_space_banner.css",)
    static_js = ("/static/js/ext_space_banner.js",)
    main_start_template = "extensions/_space_banner.html"
    default_config: ClassVar[dict[str, Any]] = {
        "title": "欢迎来到我的空间",
        "message": "",
        "tone": "accent",
        "link_label": "",
        "link_url": "",
        "dismissible": True,
    }
    config_schema: tuple[ConfigField, ...] = (
        ConfigField(
            key="title",
            kind="text",
            label_key="ext.space_banner.title",
            label_default="公告标题",
            placeholder_key="ext.space_banner.title_placeholder",
            placeholder_default="例如：欢迎浏览本空间作品",
            max_length=120,
        ),
        ConfigField(
            key="message",
            kind="textarea",
            label_key="ext.space_banner.message",
            label_default="公告内容",
            placeholder_key="ext.space_banner.message_placeholder",
            placeholder_default="输入简短说明或更新动态",
            max_length=500,
        ),
        ConfigField(
            key="tone",
            kind="select",
            label_key="ext.space_banner.tone",
            label_default="横幅色调",
            options=(
                ConfigOption("accent", "ext.space_banner.tone_accent", "主题强调"),
                ConfigOption("info", "ext.space_banner.tone_info", "信息蓝"),
                ConfigOption("success", "ext.space_banner.tone_success", "清新绿"),
                ConfigOption("warm", "ext.space_banner.tone_warm", "暖阳琥珀"),
            ),
        ),
        ConfigField(
            key="link_label",
            kind="text",
            label_key="ext.space_banner.link_label",
            label_default="按钮文案",
            help_key="ext.space_banner.link_label_help",
            help_default="配置下方跳转链接后，按钮才会显示在公告栏中。",
            placeholder_key="ext.space_banner.link_label_placeholder",
            placeholder_default="例如：查看详情",
            max_length=40,
        ),
        ConfigField(
            key="link_url",
            kind="text",
            label_key="ext.space_banner.link_url",
            label_default="跳转链接",
            placeholder_key="ext.space_banner.link_url_placeholder",
            placeholder_default="https://... 或站内路径 /projects/...",
            max_length=500,
        ),
        ConfigField(
            key="dismissible",
            kind="boolean",
            label_key="ext.space_banner.dismissible",
            label_default="允许访客关闭公告",
        ),
    )

    def normalize_config(
        self,
        raw: object,
        *,
        strict: bool = False,
        project_slug: str | None = None,
    ) -> dict[str, Any]:
        if raw is None:
            return dict(self.default_config)
        if not isinstance(raw, dict):
            if strict:
                raise InvalidContent("空间公告栏插件配置必须是对象")
            return dict(self.default_config)
        for field_name, label in (
            ("title", "公告标题"),
            ("message", "公告内容"),
            ("link_label", "按钮文案"),
        ):
            val = raw.get(field_name)
            if val is not None and not isinstance(val, str) and strict:
                raise InvalidContent(f"{label}必须是文本")
        title = sanitize_text(raw.get("title"), 120) if "title" in raw else str(self.default_config["title"])
        return {
            "title": title,
            "message": sanitize_text(raw.get("message"), 500),
            "tone": sanitize_choice(raw.get("tone"), TONES, "accent", strict=strict),
            "link_label": sanitize_text(raw.get("link_label"), 40),
            "link_url": sanitize_link_url(raw.get("link_url"), strict=strict),
            "dismissible": sanitize_bool(raw.get("dismissible"), True, strict=strict),
        }

    def render_space_context(
        self,
        *,
        project: Project,
        content: dict[str, Any],
        config: dict[str, Any],
    ) -> dict[str, Any]:
        title = str(config.get("title", ""))
        message = str(config.get("message", ""))
        tone = str(config.get("tone", "accent"))
        link_url = str(config.get("link_url", ""))
        link_label = str(config.get("link_label", "")) or ("查看详情" if link_url else "")
        dismissible = bool(config.get("dismissible", True))
        active = bool(title or message)
        digest = hashlib.sha256(f"{title}|{message}|{link_url}".encode()).hexdigest()[:8]
        return {
            "active": active,
            "title": title,
            "message": message,
            "tone": tone if tone in TONES else "accent",
            "link_label": link_label,
            "link_url": link_url,
            "is_external": link_url.startswith(("http://", "https://")),
            "dismissible": dismissible,
            "storage_key": f"sf_space_banner_{project.slug}_{digest}",
        }

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
        if slot != "main_start" or page != "space" or not context.get("active"):
            return Markup("")
        return super().inject_html(
            slot=slot,
            page=page,
            project=project,
            content=content,
            config=config,
            context=context,
        )
