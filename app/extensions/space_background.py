from typing import Any, ClassVar, Literal

from markupsafe import Markup

from app.extensions.base import (
    BaseExtension,
    ConfigField,
    ConfigOption,
    PageKind,
    TargetType,
    sanitize_bool,
    sanitize_choice,
    sanitize_float,
    sanitize_image_url,
)
from app.models import Project
from app.plugins.base import InvalidContent

PRESETS = ("none", "dots", "grid", "aurora", "mesh")
OPACITY_MIN = 0.05
OPACITY_MAX = 0.60
OPACITY_STEP = 0.05


def _opacity_step_label(value: float) -> str:
    percent = int(round(value / OPACITY_STEP) * 5)
    percent = min(max(percent, 5), 60)
    return f"{percent:02d}"


class SpaceBackgroundExtension(BaseExtension):
    id = "space_background"
    targets: tuple[TargetType, ...] = ("space",)
    name = "空间背景"
    name_key = "ext.space_background.name"
    description = "为空间画廊添加柔和纹理背景或自定义背景图，支持透明度调节与毛玻璃卡片质感。"
    description_key = "ext.space_background.description"
    version = "1.0.0"
    icon = "paintbrush"
    media_kinds = ("bg",)
    static_css = ("/static/css/ext_space_background.css",)
    static_js = ()
    body_start_template = "extensions/_space_background_layer.html"
    default_config: ClassVar[dict[str, Any]] = {
        "preset": "aurora",
        "image_url": "",
        "opacity": 0.20,
        "frosted_cards": True,
    }
    config_schema: tuple[ConfigField, ...] = (
        ConfigField(
            key="preset",
            kind="select",
            label_key="ext.space_background.preset",
            label_default="预设背景风格",
            options=(
                ConfigOption("none", "ext.space_background.preset_none", "无预设纹理（仅背景图）"),
                ConfigOption("dots", "ext.space_background.preset_dots", "极简点阵"),
                ConfigOption("grid", "ext.space_background.preset_grid", "工程网格"),
                ConfigOption("aurora", "ext.space_background.preset_aurora", "柔和极光"),
                ConfigOption("mesh", "ext.space_background.preset_mesh", "流光弥散"),
            ),
        ),
        ConfigField(
            key="image_url",
            kind="image_url",
            label_key="ext.space_background.image_url",
            label_default="自定义背景图",
            placeholder_key="ext.space_background.image_url_placeholder",
            placeholder_default="https://... 或点击上传背景图（可选）",
            max_length=500,
            upload_kind="bg",
        ),
        ConfigField(
            key="opacity",
            kind="range",
            label_key="ext.space_background.opacity",
            label_default="背景图透明度",
            min_value=OPACITY_MIN,
            max_value=OPACITY_MAX,
            step=OPACITY_STEP,
        ),
        ConfigField(
            key="frosted_cards",
            kind="boolean",
            label_key="ext.space_background.frosted_cards",
            label_default="作品卡片启用毛玻璃底板",
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
                raise InvalidContent("空间背景插件配置必须是对象")
            return dict(self.default_config)
        opacity = sanitize_float(
            raw.get("opacity"),
            0.20,
            low=OPACITY_MIN,
            high=OPACITY_MAX,
            step=OPACITY_STEP,
            strict=strict,
        )
        return {
            "preset": sanitize_choice(raw.get("preset"), PRESETS, "aurora", strict=strict),
            "image_url": sanitize_image_url(
                raw.get("image_url"),
                project_slug=project_slug,
                strict=strict,
            ),
            "opacity": round(opacity, 2),
            "frosted_cards": sanitize_bool(raw.get("frosted_cards"), True, strict=strict),
        }

    def body_classes(
        self,
        *,
        page: PageKind,
        config: dict[str, Any],
    ) -> list[str]:
        if page != "space":
            return []
        preset = str(config.get("preset", "aurora"))
        image_url = str(config.get("image_url", ""))
        if preset == "none" and not image_url:
            return []
        classes = ["has-space-bg", f"space-bg-preset-{preset}"]
        if config.get("frosted_cards", True):
            classes.append("has-space-bg-frosted")
        return classes

    def local_media_urls(self, config: dict[str, Any]) -> list[str]:
        image_url = config.get("image_url")
        return (
            [image_url]
            if isinstance(image_url, str) and image_url.startswith(("/media/blog/", "/media/ext/"))
            else []
        )

    def render_space_context(
        self,
        *,
        project: Project,
        content: dict[str, Any],
        config: dict[str, Any],
    ) -> dict[str, Any]:
        preset = str(config.get("preset", "aurora"))
        image_url = str(config.get("image_url", ""))
        active = preset != "none" or bool(image_url)
        opacity = sanitize_float(
            config.get("opacity"),
            0.20,
            low=OPACITY_MIN,
            high=OPACITY_MAX,
            step=OPACITY_STEP,
        )
        return {
            "active": active,
            "preset": preset,
            "image_url": image_url,
            "opacity_class": f"space-bg-op-{_opacity_step_label(opacity)}",
            "frosted_cards": bool(config.get("frosted_cards", True)),
        }

    def inject_body_html(
        self,
        *,
        slot: Literal["start", "end"],
        page: PageKind,
        project: Project,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> Markup:
        if slot != "start" or page != "space" or not context.get("active"):
            return Markup("")
        return super().inject_body_html(
            slot=slot,
            page=page,
            project=project,
            config=config,
            context=context,
        )
