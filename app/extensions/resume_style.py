from typing import Any, ClassVar

from app.extensions.base import (
    BaseExtension,
    ConfigField,
    ConfigOption,
    PageKind,
    TargetType,
    sanitize_bool,
    sanitize_choice,
)
from app.plugins.base import InvalidContent
from app.surface import Capability

ACCENTS = ("slate", "indigo", "emerald", "amber", "rose")
PAPERS = ("clean", "warm", "tint")
DENSITIES = ("comfortable", "compact")
FONT_STYLES = ("sans", "serif")


class ResumeStyleExtension(BaseExtension):
    id = "resume_style"
    requires: frozenset[Capability] = frozenset({"is_personal_profile"})
    targets: tuple[TargetType, ...] = ("resume",)
    name = "简历样式美化"
    name_key = "ext.resume_style.name"
    description = "自定义简历主题强调色、纸张色调、排版密度、字体风格与章节分隔线，打印导出 PDF 自动适配。"
    description_key = "ext.resume_style.description"
    version = "1.0.0"
    icon = "paintbrush"
    media_kinds = ()
    static_css = ("/static/css/ext_resume_style.css",)
    static_js = ()
    default_config: ClassVar[dict[str, Any]] = {
        "accent": "indigo",
        "paper": "clean",
        "density": "comfortable",
        "font_style": "sans",
        "show_section_dividers": True,
    }
    config_schema: tuple[ConfigField, ...] = (
        ConfigField(
            key="accent",
            kind="select",
            label_key="ext.resume_style.accent",
            label_default="强调色",
            options=(
                ConfigOption("indigo", "ext.resume_style.accent_indigo", "靛蓝"),
                ConfigOption("slate", "ext.resume_style.accent_slate", "石板灰"),
                ConfigOption("emerald", "ext.resume_style.accent_emerald", "翡翠绿"),
                ConfigOption("amber", "ext.resume_style.accent_amber", "暖琥珀"),
                ConfigOption("rose", "ext.resume_style.accent_rose", "玫瑰红"),
            ),
        ),
        ConfigField(
            key="paper",
            kind="select",
            label_key="ext.resume_style.paper",
            label_default="纸张色调",
            options=(
                ConfigOption("clean", "ext.resume_style.paper_clean", "纯净白纸"),
                ConfigOption("warm", "ext.resume_style.paper_warm", "暖色书纸"),
                ConfigOption("tint", "ext.resume_style.paper_tint", "冷调微灰"),
            ),
        ),
        ConfigField(
            key="density",
            kind="select",
            label_key="ext.resume_style.density",
            label_default="排版密度",
            options=(
                ConfigOption("comfortable", "ext.resume_style.density_comfortable", "舒适舒展"),
                ConfigOption("compact", "ext.resume_style.density_compact", "紧凑单页"),
            ),
        ),
        ConfigField(
            key="font_style",
            kind="select",
            label_key="ext.resume_style.font_style",
            label_default="字体风格",
            options=(
                ConfigOption("sans", "ext.resume_style.font_sans", "现代无衬线"),
                ConfigOption("serif", "ext.resume_style.font_serif", "经典衬线体"),
            ),
        ),
        ConfigField(
            key="show_section_dividers",
            kind="boolean",
            label_key="ext.resume_style.show_section_dividers",
            label_default="显示章节底部分隔线",
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
                raise InvalidContent("简历样式插件配置必须是对象")
            return dict(self.default_config)
        return {
            "accent": sanitize_choice(raw.get("accent"), ACCENTS, "indigo", strict=strict),
            "paper": sanitize_choice(raw.get("paper"), PAPERS, "clean", strict=strict),
            "density": sanitize_choice(raw.get("density"), DENSITIES, "comfortable", strict=strict),
            "font_style": sanitize_choice(raw.get("font_style"), FONT_STYLES, "sans", strict=strict),
            "show_section_dividers": sanitize_bool(raw.get("show_section_dividers"), True, strict=strict),
        }

    def body_classes(
        self,
        *,
        page: PageKind,
        config: dict[str, Any],
    ) -> list[str]:
        if page != "resume":
            return []
        accent = str(config.get("accent", "indigo"))
        paper = str(config.get("paper", "clean"))
        density = str(config.get("density", "comfortable"))
        font_style = str(config.get("font_style", "sans"))
        dividers = bool(config.get("show_section_dividers", True))
        return [
            "has-resume-style",
            f"resume-accent-{accent}",
            f"resume-paper-{paper}",
            f"resume-density-{density}",
            f"resume-font-{font_style}",
            "resume-section-dividers" if dividers else "resume-no-dividers",
        ]
