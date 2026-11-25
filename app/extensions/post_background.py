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

PRESETS = ("none", "dots", "grid", "aurora", "paper")
APPLY_TO = ("all", "list", "post")
OPACITY_MIN = 0.05
OPACITY_MAX = 0.60
OPACITY_STEP = 0.05


def _opacity_step_label(value: float) -> str:
    percent = int(round(value / OPACITY_STEP) * 5)
    percent = min(max(percent, 5), 60)
    return f"{percent:02d}"


class PostBackgroundExtension(BaseExtension):
    id = "post_background"
    targets: tuple[TargetType, ...] = ("blog",)
    name = "文章与博客背景"
    name_key = "blog.ext.post_background.name"
    description = "为博客列表和文章页面添加柔和主题底纹或自定义背景图，支持透明度调节。"
    description_key = "blog.ext.post_background.description"
    version = "1.0.0"
    icon = "palette"
    media_kinds = ("bg",)
    static_css = ("/static/css/blog_ext_background.css",)
    static_js = ()
    body_start_template = "extensions/_post_background_layer.html"
    default_config: ClassVar[dict[str, Any]] = {
        "preset": "dots",
        "image_url": "",
        "opacity": 0.15,
        "apply_to": "all",
        "surface_card": True,
    }
    config_schema: tuple[ConfigField, ...] = (
        ConfigField(
            key="preset",
            kind="select",
            label_key="blog.ext.post_background.preset",
            label_default="预设底纹风格",
            options=(
                ConfigOption("none", "blog.ext.post_background.preset_none", "无预设底纹（仅背景图）"),
                ConfigOption("dots", "blog.ext.post_background.preset_dots", "极简点阵"),
                ConfigOption("grid", "blog.ext.post_background.preset_grid", "工程网格"),
                ConfigOption("aurora", "blog.ext.post_background.preset_aurora", "柔和极光"),
                ConfigOption("paper", "blog.ext.post_background.preset_paper", "暖纸阅读"),
            ),
        ),
        ConfigField(
            key="image_url",
            kind="image_url",
            label_key="blog.ext.post_background.image_url",
            label_default="自定义背景图",
            placeholder_key="blog.ext.post_background.image_url_placeholder",
            placeholder_default="https://... 或点击上传背景图（可选）",
            max_length=500,
            upload_kind="bg",
        ),
        ConfigField(
            key="opacity",
            kind="range",
            label_key="blog.ext.post_background.opacity",
            label_default="背景图透明度",
            min_value=OPACITY_MIN,
            max_value=OPACITY_MAX,
            step=OPACITY_STEP,
        ),
        ConfigField(
            key="apply_to",
            kind="select",
            label_key="blog.ext.post_background.apply_to",
            label_default="生效页面范围",
            options=(
                ConfigOption("all", "blog.ext.post_background.apply_all", "列表页与文章页"),
                ConfigOption("list", "blog.ext.post_background.apply_list", "仅文章列表页"),
                ConfigOption("post", "blog.ext.post_background.apply_post", "仅文章详情页"),
            ),
        ),
        ConfigField(
            key="surface_card",
            kind="boolean",
            label_key="blog.ext.post_background.surface_card",
            label_default="正文区启用半透明阅读底板",
        ),
    )

    def _applies(self, page: PageKind, config: dict[str, Any]) -> bool:
        if page not in ("list", "post"):
            return False
        target = config.get("apply_to", "all")
        return target == "all" or target == page

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
                raise InvalidContent("背景插件配置必须是对象")
            return dict(self.default_config)
        opacity = sanitize_float(
            raw.get("opacity"),
            0.15,
            low=OPACITY_MIN,
            high=OPACITY_MAX,
            step=OPACITY_STEP,
            strict=strict,
        )
        return {
            "preset": sanitize_choice(raw.get("preset"), PRESETS, "dots", strict=strict),
            "image_url": sanitize_image_url(
                raw.get("image_url"),
                project_slug=project_slug,
                strict=strict,
            ),
            "opacity": round(opacity, 2),
            "apply_to": sanitize_choice(raw.get("apply_to"), APPLY_TO, "all", strict=strict),
            "surface_card": sanitize_bool(raw.get("surface_card"), True, strict=strict),
        }

    def body_classes(
        self,
        *,
        page: PageKind,
        config: dict[str, Any],
    ) -> list[str]:
        if not self._applies(page, config):
            return []
        preset = str(config.get("preset", "dots"))
        image_url = str(config.get("image_url", ""))
        if preset == "none" and not image_url:
            return []
        classes = ["has-blog-bg", f"blog-bg-preset-{preset}"]
        if config.get("surface_card", True):
            classes.append("has-blog-bg-card")
        return classes

    def local_media_urls(self, config: dict[str, Any]) -> list[str]:
        image_url = config.get("image_url")
        return (
            [image_url]
            if isinstance(image_url, str) and image_url.startswith(("/media/blog/", "/media/ext/"))
            else []
        )

    def _build_context(self, page: PageKind, config: dict[str, Any]) -> dict[str, Any]:
        preset = str(config.get("preset", "dots"))
        image_url = str(config.get("image_url", ""))
        active = self._applies(page, config) and (preset != "none" or bool(image_url))
        opacity = sanitize_float(
            config.get("opacity"),
            0.15,
            low=OPACITY_MIN,
            high=OPACITY_MAX,
            step=OPACITY_STEP,
        )
        return {
            "active": active,
            "preset": preset,
            "image_url": image_url,
            "opacity_class": f"blog-bg-op-{_opacity_step_label(opacity)}",
            "surface_card": bool(config.get("surface_card", True)),
        }

    def render_list_context(
        self,
        *,
        project: Project,
        blog: dict[str, Any],
        posts: list[dict[str, Any]],
        config: dict[str, Any],
    ) -> dict[str, Any]:
        return self._build_context("list", config)

    def render_post_context(
        self,
        *,
        project: Project,
        blog: dict[str, Any],
        post: dict[str, Any],
        config: dict[str, Any],
    ) -> dict[str, Any]:
        return self._build_context("post", config)

    def inject_body_html(
        self,
        *,
        slot: Literal["start", "end"],
        page: PageKind,
        project: Project,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> Markup:
        if slot != "start" or not context.get("active"):
            return Markup("")
        return super().inject_body_html(
            slot=slot,
            page=page,
            project=project,
            config=config,
            context=context,
        )
