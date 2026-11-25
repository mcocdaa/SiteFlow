import ipaddress
import re
from dataclasses import dataclass
from typing import Any, ClassVar, Literal
from urllib.parse import urlparse

from markupsafe import Markup

from app.extensions.base import (
    BaseExtension,
    ConfigField,
    ConfigOption,
    PageKind,
    TargetType,
    sanitize_bool,
    sanitize_choice,
    sanitize_image_url,
    sanitize_int,
    sanitize_lines,
    sanitize_text,
)
from app.models import Project
from app.plugins.base import InvalidContent
from app.templating import static_url


@dataclass(frozen=True)
class MascotCharacterSpec:
    id: str
    label_key: str
    label_default: str
    kind: Literal["inline_svg", "pose_svg"] = "inline_svg"
    poses: tuple[tuple[str, str], ...] = ()

    def pose_map(self) -> dict[str, str]:
        return dict(self.poses)


MASCOT_CHARACTER_SPECS: tuple[MascotCharacterSpec, ...] = (
    MascotCharacterSpec("cat", "blog.ext.mascot.char_cat", "星光小猫"),
    MascotCharacterSpec("dog", "blog.ext.mascot.char_dog", "元气柴犬"),
    MascotCharacterSpec("whale", "blog.ext.mascot.char_whale", "深蓝小鲸鱼"),
    MascotCharacterSpec("gemini_cat", "blog.ext.mascot.char_gemini_cat", "星尘双子猫"),
    MascotCharacterSpec("slime", "blog.ext.mascot.char_slime", "水滴史莱姆"),
    MascotCharacterSpec("vocaloid", "blog.ext.mascot.char_vocaloid", "银发歌姬 Q版"),
    MascotCharacterSpec(
        "dafeiyu",
        "blog.ext.mascot.char_dafeiyu",
        "DeepSeek 大肥鱼",
        kind="pose_svg",
        poses=(
            ("idle", "img/mascot/dafeiyu/idle.svg"),
            ("thinking", "img/mascot/dafeiyu/thinking.svg"),
            ("speaking", "img/mascot/dafeiyu/speaking.svg"),
            ("tap", "img/mascot/dafeiyu/tap.svg"),
        ),
    ),
)
MASCOT_CHARACTERS: tuple[str, ...] = tuple(spec.id for spec in MASCOT_CHARACTER_SPECS)
MASCOT_CHARACTER_MAP: dict[str, MascotCharacterSpec] = {spec.id: spec for spec in MASCOT_CHARACTER_SPECS}


def get_character_spec(character: str) -> MascotCharacterSpec:
    return MASCOT_CHARACTER_MAP.get(character, MASCOT_CHARACTER_MAP["cat"])


POSITIONS = ("right", "left")
THEMES = ("indigo", "sakura", "mint", "mono")
CHAT_ACCESS_MODES = ("off", "admin", "public")
API_PROTOCOLS = ("anthropic", "openai")
SAFETY_CHECK_LEVELS = ("off", "low", "high")
DEFAULT_API_PROTOCOL = "anthropic"
MODEL_PRESETS = ("deepseek-flash", "deepseek-v4-pro", "deepseek-chat", "deepseek-reasoner")
DEFAULT_API_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-flash"
DEFAULT_GREETING = "欢迎来逛逛～点我可以换一句悄悄话！"
DEFAULT_TIPS = [
    "# 每行一条点击提示语；以 # 开头的行为注释，不会展示给访客",
    "# 可用变量：{progress} 阅读进度(%)，{heading} 当前章节，{title} 标题，{site} 站点名，{words} 字数，{time} 时段问候",
    "好文章值得慢慢读，累了就歇一会儿～",
    "当前已阅读 {progress}%，继续加油～",
    "正在看「{heading}」这一节，有疑问可以在下面直接问我～",
    "{time}好！按 Ctrl / Cmd + F 可以快速查找关键词哦",
    "看完记得回到顶部逛逛其他文章呀！",
]
LEGACY_DEFAULT_TIPS = [
    "好文章值得慢慢读，累了就歇一会儿～",
    "按 Ctrl / Cmd + F 可以快速查找关键词哦",
    "看完记得回到顶部逛逛其他文章呀！",
]
_LEGACY_V3_DEFAULT_TIPS = [
    "# 每行一条点击提示语；以 # 开头的行为注释，不会展示给访客",
    "# 可用变量：{progress} 或 <%n> 阅读进度(%)，{heading} 当前章节，{title} 标题，{site} 站点名，{words} 字数，{time} 时段问候",
    "好文章值得慢慢读，累了就歇一会儿～",
    "当前已阅读 {progress}%，继续加油～",
    "正在看「{heading}」这一节，有疑问可以在下面直接问我～",
    "{time}好！按 Ctrl / Cmd + F 可以快速查找关键词哦",
    "看完记得回到顶部逛逛其他文章呀！",
]
DEFAULT_SYSTEM_PROMPT = (
    "你是站点的看板娘助手，请使用友好、简洁、准确的对应用户语言回答访客的问题。"
    "若提供了当前页面上下文，请优先结合页面内容作答。"
)
LEGACY_DEFAULT_SYSTEM_PROMPTS = frozenset(
    {
        (
            "你是站点的看板娘助手，性格友好亲切。请务必保持回复简短精炼："
            "一般问答控制在 2～4 句话或简短要点内，直奔主题，不要长篇大论，除非访客明确要求详细展开。"
            "若提供了当前页面上下文，请优先结合页面内容作答。"
        ),
        (
            "你是站点的看板娘助手，请使用友好、简洁、准确的中文回答访客的问题。"
            "若提供了当前页面上下文，请优先结合页面内容作答。"
        ),
        (
            "你是站点的看板娘助手，请用友好、简洁、准确的中文回答访客的问题。"
            "若提供了当前页面上下文，请优先结合页面内容作答。"
        ),
    }
)

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x20\x7f]")
_SECRET_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")
_MODEL_RE = re.compile(r"^[A-Za-z0-9._:/-]{1,80}$")
_LOCAL_SUFFIXES = (".localhost", ".local", ".internal")
_ACTIVE_PAGES = ("list", "post", "space")


def _sanitize_api_base_url(value: object, *, strict: bool = False) -> str:
    if value is None:
        return DEFAULT_API_BASE_URL
    if not isinstance(value, str):
        if strict:
            raise InvalidContent("API 接口地址必须是文本")
        return DEFAULT_API_BASE_URL
    cleaned = value.strip()
    if not cleaned:
        return DEFAULT_API_BASE_URL
    if len(cleaned) > 300 or _CONTROL_CHAR_RE.search(cleaned):
        if strict:
            raise InvalidContent("API 接口地址格式不正确")
        return DEFAULT_API_BASE_URL
    parsed = urlparse(cleaned)
    try:
        _ = parsed.port
    except ValueError as exc:
        if strict:
            raise InvalidContent("API 接口地址端口不合法") from exc
        return DEFAULT_API_BASE_URL
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        if strict:
            raise InvalidContent("API 接口地址仅支持公网 https:// 地址，不允许凭据、查询参数或片段")
        return DEFAULT_API_BASE_URL
    host = parsed.hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith(_LOCAL_SUFFIXES):
        if strict:
            raise InvalidContent("API 接口地址不允许指向本地或内网域名")
        return DEFAULT_API_BASE_URL
    try:
        ip_obj = ipaddress.ip_address(host)
    except ValueError:
        ip_obj = None
    if ip_obj is not None and not ip_obj.is_global:
        if strict:
            raise InvalidContent("API 接口地址不允许指向私网或回环 IP")
        return DEFAULT_API_BASE_URL
    return cleaned.rstrip("/")


def _sanitize_api_key(value: object, *, strict: bool = False) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        if strict:
            raise InvalidContent("API 密钥必须是文本")
        return ""
    if _SECRET_CTRL_RE.search(value):
        if strict:
            raise InvalidContent("API 密钥包含非法控制字符")
        return ""
    cleaned = value.strip()
    if len(cleaned) > 256:
        if strict:
            raise InvalidContent("API 密钥长度不能超过 256 个字符")
        return cleaned[:256]
    return cleaned


def _sanitize_model(value: object, *, strict: bool = False) -> str:
    if value is None:
        return DEFAULT_MODEL
    if not isinstance(value, str):
        if strict:
            raise InvalidContent("模型名称必须是文本")
        return DEFAULT_MODEL
    cleaned = value.strip()
    if not cleaned:
        return DEFAULT_MODEL
    if not _MODEL_RE.match(cleaned):
        if strict:
            raise InvalidContent("模型名称格式不正确")
        return DEFAULT_MODEL
    return cleaned


class MascotExtension(BaseExtension):
    id = "mascot"
    targets: tuple[TargetType, ...] = ("blog", "space")
    name = "看板娘"
    name_key = "blog.ext.mascot.name"
    description = "纯本地多角色 SVG 看板娘，支持自由拖拽、自定义头像与 DeepSeek AI 流式对话（零外链 CDN）。"
    description_key = "blog.ext.mascot.description"
    version = "2.0.0"
    icon = "sparkles"
    media_kinds = ("avatar",)
    static_css = ("/static/css/blog_ext_mascot.css",)
    static_js = ("/static/js/blog_ext_mascot.js",)
    body_end_template = "extensions/_mascot_widget.html"
    default_config: ClassVar[dict[str, Any]] = {
        "character": "cat",
        "theme": "indigo",
        "custom_avatar": "",
        "position": "right",
        "show_on_mobile": False,
        "draggable": True,
        "greeting": DEFAULT_GREETING,
        "tips": list(DEFAULT_TIPS),
        "chat_access": "admin",
        "api_protocol": DEFAULT_API_PROTOCOL,
        "api_base_url": DEFAULT_API_BASE_URL,
        "api_key": "",
        "model": DEFAULT_MODEL,
        "enable_thinking": True,
        "enable_web_search": False,
        "enable_read_url": False,
        "safety_check": "high",
        "enable_title": False,
        "system_prompt": DEFAULT_SYSTEM_PROMPT,
        "include_page_context": True,
        "rate_limit_per_min": 10,
    }
    config_schema: tuple[ConfigField, ...] = (
        ConfigField(
            key="character",
            kind="character_picker",
            label_key="blog.ext.mascot.character",
            label_default="角色形象",
            group="appearance",
            group_key="blog.ext.mascot.group_appearance",
            group_default="外观与角色",
            options=tuple(
                ConfigOption(spec.id, spec.label_key, spec.label_default) for spec in MASCOT_CHARACTER_SPECS
            ),
        ),
        ConfigField(
            key="theme",
            kind="select",
            label_key="blog.ext.mascot.theme",
            label_default="外观配色",
            group="appearance",
            group_key="blog.ext.mascot.group_appearance",
            group_default="外观与角色",
            options=(
                ConfigOption("indigo", "blog.ext.mascot.theme_indigo", "靛蓝流光"),
                ConfigOption("sakura", "blog.ext.mascot.theme_sakura", "樱花粉"),
                ConfigOption("mint", "blog.ext.mascot.theme_mint", "青柠薄荷"),
                ConfigOption("mono", "blog.ext.mascot.theme_mono", "极简黑白"),
            ),
        ),
        ConfigField(
            key="custom_avatar",
            kind="image_url",
            label_key="blog.ext.mascot.custom_avatar",
            label_default="自定义头像（可选）",
            help_key="blog.ext.mascot.custom_avatar_help",
            help_default="上传 PNG/WebP 保留透明背景，上传 SVG 自动执行严格安全净化。",
            placeholder_key="blog.ext.mascot.custom_avatar_placeholder",
            placeholder_default="留空使用内置角色，或输入图片链接 / 上传图片或 SVG",
            max_length=500,
            upload_kind="avatar",
            accept="image/png,image/jpeg,image/webp,image/svg+xml",
            group="appearance",
            group_key="blog.ext.mascot.group_appearance",
            group_default="外观与角色",
        ),
        ConfigField(
            key="position",
            kind="select",
            label_key="blog.ext.mascot.position",
            label_default="显示位置",
            group="appearance",
            group_key="blog.ext.mascot.group_appearance",
            group_default="外观与角色",
            options=(
                ConfigOption("right", "blog.ext.mascot.pos_right", "右下角"),
                ConfigOption("left", "blog.ext.mascot.pos_left", "左下角"),
            ),
        ),
        ConfigField(
            key="show_on_mobile",
            kind="boolean",
            label_key="blog.ext.mascot.show_on_mobile",
            label_default="移动端屏幕显示",
            group="appearance",
            group_key="blog.ext.mascot.group_appearance",
            group_default="外观与角色",
        ),
        ConfigField(
            key="draggable",
            kind="boolean",
            label_key="blog.ext.mascot.draggable",
            label_default="允许自由拖拽定位",
            group="interaction",
            group_key="blog.ext.mascot.group_interaction",
            group_default="互动与拖拽",
        ),
        ConfigField(
            key="greeting",
            kind="text",
            label_key="blog.ext.mascot.greeting",
            label_default="初始欢迎语",
            placeholder_key="blog.ext.mascot.greeting_placeholder",
            placeholder_default=DEFAULT_GREETING,
            max_length=120,
            group="interaction",
            group_key="blog.ext.mascot.group_interaction",
            group_default="互动与拖拽",
        ),
        ConfigField(
            key="tips",
            kind="textarea",
            label_key="blog.ext.mascot.tips",
            label_default="点击轮播提示语（每行一条）",
            help_key="blog.ext.mascot.tips_help",
            help_default=(
                "支持 # 开头注释行；变量：{progress} 进度、{heading} 章节、"
                "{title} 标题、{site} 站点、{words} 字数、{time} 时段。"
            ),
            placeholder_key="blog.ext.mascot.tips_placeholder",
            placeholder_default="每行一条提示语，# 开头为注释，最多 30 行",
            max_length=3000,
            rows=9,
            group="interaction",
            group_key="blog.ext.mascot.group_interaction",
            group_default="互动与拖拽",
        ),
        ConfigField(
            key="chat_access",
            kind="select",
            label_key="blog.ext.mascot.chat_access",
            label_default="AI 对话访问权限",
            group="ai_chat",
            group_key="blog.ext.mascot.group_ai_chat",
            group_default="AI 对话",
            options=(
                ConfigOption("off", "blog.ext.mascot.chat_access_off", "关闭"),
                ConfigOption("admin", "blog.ext.mascot.chat_access_admin", "仅管理员"),
                ConfigOption("public", "blog.ext.mascot.chat_access_public", "公开访客"),
            ),
        ),
        ConfigField(
            key="api_protocol",
            kind="select",
            label_key="blog.ext.mascot.api_protocol",
            label_default="API 协议",
            group="ai_chat",
            group_key="blog.ext.mascot.group_ai_chat",
            group_default="AI 对话",
            options=(
                ConfigOption(
                    "anthropic",
                    "blog.ext.mascot.protocol_anthropic",
                    "DeepSeek / Anthropic Messages（支持思考与联网工具）",
                ),
                ConfigOption(
                    "openai",
                    "blog.ext.mascot.protocol_openai",
                    "OpenAI 兼容接口（/v1/chat/completions）",
                ),
            ),
        ),
        ConfigField(
            key="api_base_url",
            kind="text",
            label_key="blog.ext.mascot.api_base_url",
            label_default="API 接口地址",
            help_key="blog.ext.mascot.api_base_url_help",
            help_default="仅支持公网 HTTPS 地址（默认 https://api.deepseek.com，自动按所选协议拼接路径）。",
            placeholder_key="blog.ext.mascot.api_base_url_placeholder",
            placeholder_default=DEFAULT_API_BASE_URL,
            max_length=300,
            group="ai_chat",
            group_key="blog.ext.mascot.group_ai_chat",
            group_default="AI 对话",
        ),
        ConfigField(
            key="api_key",
            kind="secret",
            label_key="blog.ext.mascot.api_key",
            label_default="API 密钥",
            help_key="blog.ext.mascot.api_key_help",
            help_default="密钥仅保存在服务端，绝不会下发至公开页面或浏览器。",
            placeholder_key="blog.ext.mascot.api_key_placeholder",
            placeholder_default="输入新的 API 密钥（留空保持不变）",
            max_length=256,
            group="ai_chat",
            group_key="blog.ext.mascot.group_ai_chat",
            group_default="AI 对话",
        ),
        ConfigField(
            key="model",
            kind="text",
            label_key="blog.ext.mascot.model",
            label_default="模型名称",
            placeholder_key="blog.ext.mascot.model_placeholder",
            placeholder_default=DEFAULT_MODEL,
            max_length=80,
            options=(
                ConfigOption("deepseek-flash", "blog.ext.mascot.model_deepseek_flash", "deepseek-flash"),
                ConfigOption("deepseek-v4-pro", "blog.ext.mascot.model_deepseek_v4_pro", "deepseek-v4-pro"),
                ConfigOption("deepseek-chat", "blog.ext.mascot.model_deepseek_chat", "deepseek-chat"),
                ConfigOption(
                    "deepseek-reasoner", "blog.ext.mascot.model_deepseek_reasoner", "deepseek-reasoner"
                ),
            ),
            group="ai_chat",
            group_key="blog.ext.mascot.group_ai_chat",
            group_default="AI 对话",
        ),
        ConfigField(
            key="enable_thinking",
            kind="boolean",
            label_key="blog.ext.mascot.enable_thinking",
            label_default="启用深度思考（Thinking）",
            help_key="blog.ext.mascot.enable_thinking_help",
            help_default="开启后流式展示灰色思考过程，正文输出后自动折叠。",
            group="ai_chat",
            group_key="blog.ext.mascot.group_ai_chat",
            group_default="AI 对话",
        ),
        ConfigField(
            key="enable_web_search",
            kind="boolean",
            label_key="blog.ext.mascot.enable_web_search",
            label_default="启用联网搜索（deepseek_web_search）",
            group="ai_chat",
            group_key="blog.ext.mascot.group_ai_chat",
            group_default="AI 对话",
        ),
        ConfigField(
            key="enable_read_url",
            kind="boolean",
            label_key="blog.ext.mascot.enable_read_url",
            label_default="启用网页阅读（deepseek_read_url）",
            group="ai_chat",
            group_key="blog.ext.mascot.group_ai_chat",
            group_default="AI 对话",
        ),
        ConfigField(
            key="safety_check",
            kind="select",
            label_key="blog.ext.mascot.safety_check",
            label_default="内容安全审查（safety_check）",
            help_key="blog.ext.mascot.safety_check_help",
            help_default="公开站点建议设为严格（high），仅在 DeepSeek Messages 协议下生效。",
            group="ai_chat",
            group_key="blog.ext.mascot.group_ai_chat",
            group_default="AI 对话",
            options=(
                ConfigOption("high", "blog.ext.mascot.safety_high", "严格（high，公开推荐）"),
                ConfigOption("low", "blog.ext.mascot.safety_low", "基础（low）"),
                ConfigOption("off", "blog.ext.mascot.safety_off", "不额外指定"),
            ),
        ),
        ConfigField(
            key="enable_title",
            kind="boolean",
            label_key="blog.ext.mascot.enable_title",
            label_default="自动生成对话标题（title）",
            group="ai_chat",
            group_key="blog.ext.mascot.group_ai_chat",
            group_default="AI 对话",
        ),
        ConfigField(
            key="system_prompt",
            kind="textarea",
            label_key="blog.ext.mascot.system_prompt",
            label_default="系统提示词（人设）",
            placeholder_key="blog.ext.mascot.system_prompt_placeholder",
            placeholder_default=DEFAULT_SYSTEM_PROMPT,
            max_length=2000,
            rows=5,
            group="ai_chat",
            group_key="blog.ext.mascot.group_ai_chat",
            group_default="AI 对话",
        ),
        ConfigField(
            key="include_page_context",
            kind="boolean",
            label_key="blog.ext.mascot.include_page_context",
            label_default="自动注入当前页面上下文",
            group="ai_chat",
            group_key="blog.ext.mascot.group_ai_chat",
            group_default="AI 对话",
        ),
        ConfigField(
            key="rate_limit_per_min",
            kind="number",
            label_key="blog.ext.mascot.rate_limit_per_min",
            label_default="单 IP 每分钟对话次数上限",
            min_value=1,
            max_value=60,
            step=1,
            group="ai_chat",
            group_key="blog.ext.mascot.group_ai_chat",
            group_default="AI 对话",
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
            return {**self.default_config, "tips": list(DEFAULT_TIPS)}
        if not isinstance(raw, dict):
            if strict:
                raise InvalidContent("看板娘插件配置必须是对象")
            return {**self.default_config, "tips": list(DEFAULT_TIPS)}
        if "greeting" in raw:
            greeting_raw = raw.get("greeting")
            if greeting_raw is not None and not isinstance(greeting_raw, str):
                if strict:
                    raise InvalidContent("欢迎语必须是文本")
                greeting = DEFAULT_GREETING
            else:
                greeting = sanitize_text(greeting_raw, 120)
        else:
            greeting = DEFAULT_GREETING
        if "system_prompt" in raw:
            prompt_raw = raw.get("system_prompt")
            if prompt_raw is None:
                system_prompt = DEFAULT_SYSTEM_PROMPT
            elif not isinstance(prompt_raw, str):
                if strict:
                    raise InvalidContent("系统提示词必须是文本")
                system_prompt = DEFAULT_SYSTEM_PROMPT
            else:
                system_prompt = sanitize_text(prompt_raw, 2000)
        else:
            system_prompt = DEFAULT_SYSTEM_PROMPT
        tips = sanitize_lines(
            raw.get("tips"),
            max_items=30,
            item_limit=160,
            default=DEFAULT_TIPS,
            strict=strict,
        )
        if not strict:
            if tips in (LEGACY_DEFAULT_TIPS, _LEGACY_V3_DEFAULT_TIPS):
                tips = list(DEFAULT_TIPS)
            if system_prompt in LEGACY_DEFAULT_SYSTEM_PROMPTS:
                system_prompt = DEFAULT_SYSTEM_PROMPT
        return {
            "character": sanitize_choice(raw.get("character"), MASCOT_CHARACTERS, "cat", strict=strict),
            "theme": sanitize_choice(raw.get("theme"), THEMES, "indigo", strict=strict),
            "custom_avatar": sanitize_image_url(
                raw.get("custom_avatar"),
                project_slug=project_slug,
                strict=strict,
                allow_svg_media=True,
            ),
            "position": sanitize_choice(raw.get("position"), POSITIONS, "right", strict=strict),
            "show_on_mobile": sanitize_bool(raw.get("show_on_mobile"), False, strict=strict),
            "draggable": sanitize_bool(raw.get("draggable"), True, strict=strict),
            "greeting": greeting,
            "tips": tips,
            "chat_access": sanitize_choice(raw.get("chat_access"), CHAT_ACCESS_MODES, "admin", strict=strict),
            "api_protocol": sanitize_choice(
                raw.get("api_protocol"), API_PROTOCOLS, DEFAULT_API_PROTOCOL, strict=strict
            ),
            "api_base_url": _sanitize_api_base_url(raw.get("api_base_url"), strict=strict),
            "api_key": _sanitize_api_key(raw.get("api_key"), strict=strict),
            "model": _sanitize_model(raw.get("model"), strict=strict),
            "enable_thinking": sanitize_bool(raw.get("enable_thinking"), True, strict=strict),
            "enable_web_search": sanitize_bool(raw.get("enable_web_search"), False, strict=strict),
            "enable_read_url": sanitize_bool(raw.get("enable_read_url"), False, strict=strict),
            "safety_check": sanitize_choice(
                raw.get("safety_check"), SAFETY_CHECK_LEVELS, "high", strict=strict
            ),
            "enable_title": sanitize_bool(raw.get("enable_title"), False, strict=strict),
            "system_prompt": system_prompt,
            "include_page_context": sanitize_bool(raw.get("include_page_context"), True, strict=strict),
            "rate_limit_per_min": sanitize_int(
                raw.get("rate_limit_per_min"), 10, low=1, high=60, strict=strict
            ),
        }

    def local_media_urls(self, config: dict[str, Any]) -> list[str]:
        url = config.get("custom_avatar")
        if isinstance(url, str) and url.startswith(("/media/blog/", "/media/ext/")):
            return [url]
        return []

    def body_classes(
        self,
        *,
        page: PageKind,
        config: dict[str, Any],
    ) -> list[str]:
        if page not in _ACTIVE_PAGES:
            return []
        pos = str(config.get("position", "right"))
        classes = ["has-mascot", f"mascot-{pos}"]
        if bool(config.get("show_on_mobile", False)):
            classes.append("mascot-mobile-visible")
        return classes

    def _build_context(
        self,
        *,
        page: PageKind,
        project: Project,
        config: dict[str, Any],
        content: dict[str, Any] | None = None,
        post: dict[str, Any] | None = None,
        is_admin: bool = False,
    ) -> dict[str, Any]:
        spec = get_character_spec(str(config.get("character", "cat")))
        character = spec.id
        position = str(config.get("position", "right"))
        theme = str(config.get("theme", "indigo"))
        custom_avatar = str(config.get("custom_avatar", ""))
        character_kind = "custom" if custom_avatar else spec.kind
        resolved_poses = {} if custom_avatar else {k: static_url(v) for k, v in spec.poses}
        greeting = str(config.get("greeting", ""))
        raw_tips = config.get("tips")
        tips = (
            [text for item in raw_tips if (text := str(item).strip()) and not text.startswith("#")]
            if isinstance(raw_tips, list)
            else []
        )
        show_on_mobile = bool(config.get("show_on_mobile", False))
        draggable = bool(config.get("draggable", True))
        chat_access = str(config.get("chat_access", "admin"))
        has_api_key = bool(str(config.get("api_key", "")).strip())
        chat_enabled = has_api_key and (chat_access == "public" or (chat_access == "admin" and is_admin))
        content_dict = content if isinstance(content, dict) else {}
        project_title = str(content_dict.get("title") or project.title or "").strip()
        is_post = page == "post" and isinstance(post, dict)
        post_slug = str(post.get("slug", "")) if is_post and post is not None else ""
        post_title = str(post.get("title", "")).strip() if is_post and post is not None else ""
        post_words = len(str(post.get("body", ""))) if is_post and post is not None else 0
        payload: dict[str, Any] = {
            "slug": project.slug,
            "page": page,
            "post_slug": post_slug,
            "project_title": project_title,
            "post_title": post_title,
            "post_words": post_words,
            "draggable": draggable,
            "greeting": greeting,
            "tips": tips,
            "chat_enabled": chat_enabled,
            "chat_url": f"/api/projects/{project.slug}/mascot/chat",
            "character": character,
            "character_kind": character_kind,
            "poses": resolved_poses,
        }
        return {
            "character": character,
            "character_kind": character_kind,
            "position": position,
            "theme": theme,
            "custom_avatar": custom_avatar,
            "greeting": greeting,
            "tips": tips,
            "show_on_mobile": show_on_mobile,
            "draggable": draggable,
            "chat_enabled": chat_enabled,
            "payload": payload,
        }

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
        if page not in _ACTIVE_PAGES:
            return {}
        return self._build_context(
            page=page,
            project=project,
            config=config,
            content=content,
            post=post,
            is_admin=is_admin,
        )

    def render_list_context(
        self,
        *,
        project: Project,
        blog: dict[str, Any],
        posts: list[dict[str, Any]],
        config: dict[str, Any],
    ) -> dict[str, Any]:
        return self._build_context(page="list", project=project, config=config, content=blog)

    def render_post_context(
        self,
        *,
        project: Project,
        blog: dict[str, Any],
        post: dict[str, Any],
        config: dict[str, Any],
    ) -> dict[str, Any]:
        return self._build_context(page="post", project=project, config=config, content=blog, post=post)

    def render_space_context(
        self,
        *,
        project: Project,
        content: dict[str, Any],
        config: dict[str, Any],
    ) -> dict[str, Any]:
        return self._build_context(page="space", project=project, config=config, content=content)

    def inject_body_html(
        self,
        *,
        slot: Literal["start", "end"],
        page: PageKind,
        project: Project,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> Markup:
        if slot != "end" or page not in _ACTIVE_PAGES:
            return Markup("")
        return super().inject_body_html(
            slot=slot,
            page=page,
            project=project,
            config=config,
            context=context,
        )

    def inject_html(
        self,
        *,
        slot: Literal["start", "main_start", "end"],
        page: PageKind,
        project: Project,
        content: dict[str, Any] | None = None,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> Markup:
        if slot != "end" or page not in _ACTIVE_PAGES:
            return Markup("")
        return self.inject_body_html(
            slot="end",
            page=page,
            project=project,
            config=config,
            context=context,
        )
