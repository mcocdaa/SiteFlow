from typing import Any, ClassVar

from app.extensions.base import (
    BaseExtension,
    ConfigField,
    ConfigOption,
    PageKind,
    TargetType,
    sanitize_bool,
    sanitize_choice,
    sanitize_image_url,
    sanitize_text,
)
from app.models import Project
from app.plugins.base import InvalidContent
from app.surface import Capability

ASPECT_RATIOS: dict[str, str] = {
    "16/9": "ratio-16-9",
    "16/10": "ratio-16-10",
    "21/9": "ratio-21-9",
    "4/3": "ratio-4-3",
}


class PostCoverExtension(BaseExtension):
    id = "post_cover"
    requires: frozenset[Capability] = frozenset({"has_posts"})
    targets: tuple[TargetType, ...] = ("blog",)
    name = "文章封面"
    name_key = "blog.ext.post_cover.name"
    description = "为文章配置封面图（支持上传或外链），展示在文章列表卡片与文章顶部。"
    description_key = "blog.ext.post_cover.description"
    version = "1.0.0"
    icon = "image"
    media_kinds = ("cover",)
    static_css = ("/static/css/blog_ext_cover.css",)
    static_js = ()
    list_card_template = "extensions/_post_cover_card.html"
    post_header_template = "extensions/_post_cover_header.html"
    editor_fields_template = "extensions/_post_cover_editor.html"
    default_config: ClassVar[dict[str, Any]] = {
        "show_in_list": True,
        "show_in_post": True,
        "aspect_ratio": "16/9",
        "default_cover": "",
    }
    config_schema: tuple[ConfigField, ...] = (
        ConfigField(
            key="show_in_list",
            kind="boolean",
            label_key="blog.ext.post_cover.show_in_list",
            label_default="文章列表显示封面",
        ),
        ConfigField(
            key="show_in_post",
            kind="boolean",
            label_key="blog.ext.post_cover.show_in_post",
            label_default="文章详情顶部显示封面",
        ),
        ConfigField(
            key="aspect_ratio",
            kind="select",
            label_key="blog.ext.post_cover.aspect_ratio",
            label_default="封面纵横比",
            options=(
                ConfigOption("16/9", "blog.ext.post_cover.ratio_16_9", "宽屏 16:9"),
                ConfigOption("16/10", "blog.ext.post_cover.ratio_16_10", "画廊 16:10"),
                ConfigOption("21/9", "blog.ext.post_cover.ratio_21_9", "横幅 21:9"),
                ConfigOption("4/3", "blog.ext.post_cover.ratio_4_3", "经典 4:3"),
            ),
        ),
        ConfigField(
            key="default_cover",
            kind="image_url",
            label_key="blog.ext.post_cover.default_cover",
            label_default="默认兜底封面",
            placeholder_key="blog.ext.post_cover.default_cover_placeholder",
            placeholder_default="https://... 或点击右侧上传（留空不显示）",
            max_length=500,
            upload_kind="cover",
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
                raise InvalidContent("文章封面插件配置必须是对象")
            return dict(self.default_config)
        return {
            "show_in_list": sanitize_bool(raw.get("show_in_list"), True, strict=strict),
            "show_in_post": sanitize_bool(raw.get("show_in_post"), True, strict=strict),
            "aspect_ratio": sanitize_choice(
                raw.get("aspect_ratio"),
                ASPECT_RATIOS,
                "16/9",
                strict=strict,
            ),
            "default_cover": sanitize_image_url(
                raw.get("default_cover"),
                project_slug=project_slug,
                strict=strict,
            ),
        }

    def normalize_post_meta(
        self,
        raw_meta: dict[str, Any],
        *,
        strict: bool = False,
        project_slug: str | None = None,
    ) -> dict[str, Any]:
        cover = sanitize_image_url(raw_meta.get("cover"), project_slug=project_slug, strict=strict)
        if not cover:
            return {}
        out: dict[str, Any] = {"cover": cover}
        cover_alt = sanitize_text(raw_meta.get("cover_alt"), 200)
        if cover_alt:
            out["cover_alt"] = cover_alt
        return out

    def body_classes(
        self,
        *,
        page: PageKind,
        config: dict[str, Any],
    ) -> list[str]:
        if (page == "list" and config.get("show_in_list")) or (page == "post" and config.get("show_in_post")):
            return ["has-post-cover"]
        return []

    def local_media_urls(self, config: dict[str, Any]) -> list[str]:
        default_cover = config.get("default_cover")
        return (
            [default_cover]
            if isinstance(default_cover, str) and default_cover.startswith(("/media/blog/", "/media/ext/"))
            else []
        )

    def render_list_context(
        self,
        *,
        project: Project,
        blog: dict[str, Any],
        posts: list[dict[str, Any]],
        config: dict[str, Any],
    ) -> dict[str, Any]:
        aspect_class = ASPECT_RATIOS.get(str(config.get("aspect_ratio", "16/9")), "ratio-16-9")
        show = bool(config.get("show_in_list", True))
        default_cover = str(config.get("default_cover", ""))
        covers: dict[str, dict[str, str]] = {}
        if show:
            for post in posts:
                slug = str(post.get("slug", ""))
                raw_meta = post.get("meta")
                meta = raw_meta if isinstance(raw_meta, dict) else {}
                url = str(meta.get("cover", "")) or default_cover
                if url:
                    alt = str(meta.get("cover_alt", "")) or str(post.get("title", ""))
                    covers[slug] = {"url": url, "alt": alt}
        return {"enabled": show, "aspect_class": aspect_class, "covers": covers}

    def render_post_context(
        self,
        *,
        project: Project,
        blog: dict[str, Any],
        post: dict[str, Any],
        config: dict[str, Any],
    ) -> dict[str, Any]:
        aspect_class = ASPECT_RATIOS.get(str(config.get("aspect_ratio", "16/9")), "ratio-16-9")
        show = bool(config.get("show_in_post", True))
        raw_meta = post.get("meta")
        meta = raw_meta if isinstance(raw_meta, dict) else {}
        url = (str(meta.get("cover", "")) or str(config.get("default_cover", ""))) if show else ""
        alt = str(meta.get("cover_alt", "")) or str(post.get("title", ""))
        return {"enabled": show, "url": url, "alt": alt, "aspect_class": aspect_class}

    def render_editor_context(
        self,
        *,
        project: Project,
        post: dict[str, Any] | None,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        raw_meta = post.get("meta") if isinstance(post, dict) else None
        meta = raw_meta if isinstance(raw_meta, dict) else {}
        return {
            "cover": str(meta.get("cover", "")),
            "cover_alt": str(meta.get("cover_alt", "")),
            "default_cover": str(config.get("default_cover", "")),
        }
