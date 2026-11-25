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
)
from app.models import Project
from app.plugins.base import InvalidContent
from app.surface import Capability

LAYOUT_MODES = ("grid", "masonry", "polaroid", "desk")
CARD_TILTS = ("none", "subtle", "medium", "playful")


class SpaceLayoutExtension(BaseExtension):
    id = "space_layout"
    targets: tuple[TargetType, ...] = ("space",)
    requires: frozenset[Capability] = frozenset({"has_items", "supports_layout"})
    excludes: frozenset[Capability] = frozenset({"has_posts"})
    name = "空间排布模式"
    name_key = "ext.space_layout.name"
    description = "切换空间作品画廊排布风格：标准网格、瀑布流、拍立得相片或可自由拖拽的拼贴桌面。"
    description_key = "ext.space_layout.description"
    version = "1.0.0"
    icon = "layout-grid"
    media_kinds = ()
    static_css = ("/static/css/ext_space_layout.css",)
    static_js = ("/static/js/ext_space_layout.js",)
    main_start_template = "extensions/_space_layout_controls.html"
    default_config: ClassVar[dict[str, Any]] = {
        "mode": "grid",
        "card_tilt": "medium",
        "show_desk_controls": True,
    }
    config_schema: tuple[ConfigField, ...] = (
        ConfigField(
            key="mode",
            kind="select",
            label_key="ext.space_layout.mode",
            label_default="排布模式",
            options=(
                ConfigOption("grid", "ext.space_layout.mode_grid", "标准网格"),
                ConfigOption("masonry", "ext.space_layout.mode_masonry", "瀑布流"),
                ConfigOption("polaroid", "ext.space_layout.mode_polaroid", "拍立得相片"),
                ConfigOption("desk", "ext.space_layout.mode_desk", "自由拼贴桌面"),
            ),
        ),
        ConfigField(
            key="card_tilt",
            kind="select",
            label_key="ext.space_layout.card_tilt",
            label_default="卡片倾角强度",
            help_key="ext.space_layout.card_tilt_help",
            help_default="控制拍立得与桌面模式中作品卡片的旋转倾角幅度。",
            options=(
                ConfigOption("none", "ext.space_layout.tilt_none", "无倾角"),
                ConfigOption("subtle", "ext.space_layout.tilt_subtle", "轻微倾斜"),
                ConfigOption("medium", "ext.space_layout.tilt_medium", "柔和倾斜"),
                ConfigOption("playful", "ext.space_layout.tilt_playful", "俏皮倾斜"),
            ),
        ),
        ConfigField(
            key="show_desk_controls",
            kind="boolean",
            label_key="ext.space_layout.show_desk_controls",
            label_default="桌面模式显示打乱与归位按钮",
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
                raise InvalidContent("空间排布模式插件配置必须是对象")
            return dict(self.default_config)
        return {
            "mode": sanitize_choice(raw.get("mode"), LAYOUT_MODES, "grid", strict=strict),
            "card_tilt": sanitize_choice(raw.get("card_tilt"), CARD_TILTS, "medium", strict=strict),
            "show_desk_controls": sanitize_bool(raw.get("show_desk_controls"), True, strict=strict),
        }

    def layout_mode(
        self,
        page: PageKind,
        config: dict[str, Any],
    ) -> str | None:
        if page != "space":
            return None
        return sanitize_choice(config.get("mode"), LAYOUT_MODES, "grid")

    def body_classes(
        self,
        *,
        page: PageKind,
        config: dict[str, Any],
    ) -> list[str]:
        if page != "space":
            return []
        mode = sanitize_choice(config.get("mode"), LAYOUT_MODES, "grid")
        tilt = sanitize_choice(config.get("card_tilt"), CARD_TILTS, "medium")
        classes = ["has-space-layout", f"space-layout-{mode}", f"space-tilt-{tilt}"]
        if mode == "desk" and bool(config.get("show_desk_controls", True)):
            classes.append("has-desk-controls")
        return classes

    def render_space_context(
        self,
        *,
        project: Project,
        content: dict[str, Any],
        config: dict[str, Any],
    ) -> dict[str, Any]:
        mode = sanitize_choice(config.get("mode"), LAYOUT_MODES, "grid")
        tilt = sanitize_choice(config.get("card_tilt"), CARD_TILTS, "medium")
        show_controls = bool(config.get("show_desk_controls", True))
        return {
            "active": mode == "desk",
            "mode": mode,
            "card_tilt": tilt,
            "show_desk_controls": show_controls,
            "project_slug": project.slug,
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
