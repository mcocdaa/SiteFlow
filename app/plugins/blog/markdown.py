import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from markdown_it import MarkdownIt
from markdown_it.common.utils import escapeHtml
from markdown_it.renderer import RendererHTML
from markdown_it.rules_block import StateBlock
from markdown_it.rules_core import StateCore
from markdown_it.token import Token
from markdown_it.utils import EnvType, OptionsDict
from mdit_py_plugins.anchors import anchors_plugin
from mdit_py_plugins.dollarmath import dollarmath_plugin
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.tasklists import tasklists_plugin

BLOG_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' https: http: data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'self'"
)

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")
_SAFE_DATA_IMAGE_RE = re.compile(
    r"^data:image/(?:png|jpeg|gif|webp);base64,[a-z0-9+/=\s]+$",
    re.IGNORECASE,
)
_TOC_LINE_RE = re.compile(
    r"^(?:@\[toc\](?:\(([^)\r\n]*)\))?|\[toc\]|\[\[_toc_\]\])$",
    re.IGNORECASE,
)
_CSDN_TOC_PLACEHOLDERS = frozenset({"这里写目录标题", "文章目录标题"})
_SLUG_STRIP_RE = re.compile(r"[^\w\s-]")
_SLUG_DASH_RE = re.compile(r"[\s_-]+")
_TOC_MAX_LEVEL = 4
_TOC_TITLE_LIMIT = 100


@dataclass(frozen=True)
class TocItem:
    level: int
    depth: int
    text: str
    id: str


@dataclass(frozen=True)
class RenderedMarkdown:
    html: str
    toc: list[TocItem]
    toc_title: str
    has_math: bool


def _validate_url(url: str) -> bool:
    if _CONTROL_CHAR_RE.search(url):
        return False
    cleaned = url.strip()
    if not cleaned:
        return False
    scheme = urlsplit(cleaned).scheme.lower()
    if scheme in ("", "http", "https", "mailto"):
        return True
    if scheme == "data":
        return bool(_SAFE_DATA_IMAGE_RE.match(cleaned))
    return False


def _heading_slug(title: str) -> str:
    cleaned = _SLUG_STRIP_RE.sub("", title.strip().lower())
    return _SLUG_DASH_RE.sub("-", cleaned).strip("-") or "section"


def _toc_marker_block(state: StateBlock, startLine: int, endLine: int, silent: bool) -> bool:
    if state.sCount[startLine] - state.blkIndent >= 4:
        return False
    pos = state.bMarks[startLine] + state.tShift[startLine]
    maximum = state.eMarks[startLine]
    line = state.src[pos:maximum].strip()
    match = _TOC_LINE_RE.match(line)
    if not match:
        return False
    if silent:
        return True
    state.line = startLine + 1
    raw_title = (match.group(1) or "").strip()
    if raw_title and raw_title not in _CSDN_TOC_PLACEHOLDERS and not state.env.get("toc_title"):
        state.env["toc_title"] = raw_title[:_TOC_TITLE_LIMIT]
    token = state.push("toc_marker", "", 0)
    token.map = [startLine, state.line]
    return True


def _render_toc_marker(
    self: RendererHTML,
    tokens: Sequence[Token],
    idx: int,
    options: OptionsDict,
    env: EnvType,
) -> str:
    return ""


def _toc_marker_plugin(md: MarkdownIt) -> None:
    md.block.ruler.before("paragraph", "toc_marker", _toc_marker_block, {"alt": ["paragraph"]})
    md.add_render_rule("toc_marker", _render_toc_marker)


def _sanitize_inline_tokens(state: StateCore) -> None:
    for token in state.tokens:
        if token.type != "inline" or not token.children:
            continue
        cleaned: list[Token] = []
        drop_close_stack: list[bool] = []
        for child in token.children:
            if child.type == "link_open":
                href = str(child.attrGet("href") or "").strip()
                if href.lower().startswith("data:") or not _validate_url(href):
                    drop_close_stack.append(True)
                    continue
                drop_close_stack.append(False)
                cleaned.append(child)
            elif child.type == "link_close":
                if drop_close_stack and drop_close_stack.pop():
                    continue
                cleaned.append(child)
            elif child.type == "image":
                src = str(child.attrGet("src") or "").strip()
                if src.lower().startswith("mailto:") or not _validate_url(src):
                    if child.children:
                        alt_text = "".join(
                            part.content for part in child.children if part.type in ("text", "code_inline")
                        )
                        if alt_text:
                            cleaned.append(Token("text", "", 0, content=alt_text))
                    continue
                cleaned.append(child)
            else:
                cleaned.append(child)
        token.children = cleaned


def _collect_toc(state: StateCore) -> None:
    raw_items: list[tuple[int, str, str]] = []
    tokens = state.tokens
    for idx, token in enumerate(tokens):
        if token.type != "heading_open":
            continue
        level = int(token.tag[1])
        if not (1 <= level <= _TOC_MAX_LEVEL):
            continue
        anchor_id = str(token.attrGet("id") or "").strip()
        if not anchor_id or idx + 1 >= len(tokens):
            continue
        inline_token = tokens[idx + 1]
        parts: list[str] = []
        for child in inline_token.children or ():
            if child.type in ("text", "code_inline", "math_inline", "math_inline_double"):
                parts.append(child.content)
            elif child.type == "softbreak":
                parts.append(" ")
        heading_text = re.sub(r"\s+", " ", "".join(parts)).strip()
        if heading_text:
            raw_items.append((level, heading_text, anchor_id))
    if not raw_items:
        state.env["toc"] = []
        return
    min_level = min(level for level, _, _ in raw_items)
    state.env["toc"] = [
        TocItem(level=level, depth=level - min_level, text=text, id=anchor_id)
        for level, text, anchor_id in raw_items
    ]


def _render_link_open(
    self: RendererHTML,
    tokens: Sequence[Token],
    idx: int,
    options: OptionsDict,
    env: EnvType,
) -> str:
    token = tokens[idx]
    href = str(token.attrGet("href") or "").strip()
    if href.startswith(("http://", "https://", "//")):
        token.attrSet("target", "_blank")
        token.attrSet("rel", "noopener noreferrer")
    return self.renderToken(tokens, idx, options, env)


def _render_image(
    self: RendererHTML,
    tokens: Sequence[Token],
    idx: int,
    options: OptionsDict,
    env: EnvType,
) -> str:
    token = tokens[idx]
    token.attrSet("referrerpolicy", "no-referrer")
    token.attrSet("loading", "lazy")
    token.attrSet("decoding", "async")
    return self.image(tokens, idx, options, env)


def _render_table_open(
    self: RendererHTML,
    tokens: Sequence[Token],
    idx: int,
    options: OptionsDict,
    env: EnvType,
) -> str:
    return '<div class="table-wrap">' + self.renderToken(tokens, idx, options, env)


def _render_table_close(
    self: RendererHTML,
    tokens: Sequence[Token],
    idx: int,
    options: OptionsDict,
    env: EnvType,
) -> str:
    return self.renderToken(tokens, idx, options, env) + "</div>\n"


def _render_math_inline(
    self: RendererHTML,
    tokens: Sequence[Token],
    idx: int,
    options: OptionsDict,
    env: EnvType,
) -> str:
    env["has_math"] = True
    content = escapeHtml(str(tokens[idx].content).strip())
    return f'<span class="sf-math sf-math-inline" data-math-display="0">{content}</span>'


def _render_math_inline_double(
    self: RendererHTML,
    tokens: Sequence[Token],
    idx: int,
    options: OptionsDict,
    env: EnvType,
) -> str:
    env["has_math"] = True
    content = escapeHtml(str(tokens[idx].content).strip())
    return f'<div class="sf-math sf-math-display" data-math-display="1">{content}</div>'


def _render_math_block(
    self: RendererHTML,
    tokens: Sequence[Token],
    idx: int,
    options: OptionsDict,
    env: EnvType,
) -> str:
    env["has_math"] = True
    content = escapeHtml(str(tokens[idx].content).strip())
    return f'<div class="sf-math sf-math-display" data-math-display="1">{content}</div>\n'


def _render_math_block_label(
    self: RendererHTML,
    tokens: Sequence[Token],
    idx: int,
    options: OptionsDict,
    env: EnvType,
) -> str:
    env["has_math"] = True
    content = escapeHtml(str(tokens[idx].content).strip())
    label_id = escapeHtml(str(tokens[idx].info).strip())
    return (
        f'<div id="{label_id}" class="sf-math-labeled">'
        f'<div class="sf-math sf-math-display" data-math-display="1">{content}</div>'
        f'<a href="#{label_id}" class="sf-math-label">({label_id})</a>'
        "</div>\n"
    )


class _SafeMarkdownIt(MarkdownIt):
    def validateLink(self, url: str) -> bool:
        return _validate_url(url)


def _build_markdown_parser() -> MarkdownIt:
    md = _SafeMarkdownIt(
        "gfm-like",
        {
            "html": False,
            "linkify": True,
            "breaks": False,
            "typographer": False,
            "xhtmlOut": False,
        },
    )
    if md.linkify is not None:
        md.linkify.set({"fuzzy_link": False, "fuzzy_ip": False, "fuzzy_email": False})
    md.use(tasklists_plugin, enabled=False, label=True)
    md.use(footnote_plugin)
    md.use(
        dollarmath_plugin,
        allow_labels=True,
        allow_space=True,
        allow_digits=False,
        allow_blank_lines=True,
        double_inline=True,
    )
    md.use(_toc_marker_plugin)
    md.use(anchors_plugin, min_level=1, max_level=6, slug_func=_heading_slug, permalink=False)
    md.core.ruler.after("linkify", "sanitize_links", _sanitize_inline_tokens)
    md.core.ruler.push("collect_toc", _collect_toc)
    md.add_render_rule("link_open", _render_link_open)
    md.add_render_rule("image", _render_image)
    md.add_render_rule("table_open", _render_table_open)
    md.add_render_rule("table_close", _render_table_close)
    md.add_render_rule("math_inline", _render_math_inline)
    md.add_render_rule("math_inline_double", _render_math_inline_double)
    md.add_render_rule("math_block", _render_math_block)
    md.add_render_rule("math_block_label", _render_math_block_label)
    return md


def _build_inline_math_parser() -> MarkdownIt:
    md = MarkdownIt("zero", {"html": False, "xhtmlOut": False})
    md.enable(["escape", "fence"])
    md.use(
        dollarmath_plugin,
        allow_labels=False,
        allow_space=True,
        allow_digits=False,
        allow_blank_lines=False,
        double_inline=True,
    )
    md.add_render_rule("math_inline", _render_math_inline)
    md.add_render_rule("math_inline_double", _render_math_inline)
    return md


_markdown = _build_markdown_parser()
_inline_math = _build_inline_math_parser()


def render_markdown(body: str) -> RenderedMarkdown:
    env: dict[str, Any] = {}
    html = _markdown.render(body or "", env)
    toc: list[TocItem] = env.get("toc", [])
    toc_title = str(env.get("toc_title", ""))
    has_math = bool(env.get("has_math", False))
    return RenderedMarkdown(html=html, toc=toc, toc_title=toc_title, has_math=has_math)


def render_inline_math(text: str) -> tuple[str, bool]:
    if not text:
        return "", False
    env: dict[str, Any] = {}
    html = _inline_math.renderInline(text, env)
    return html, bool(env.get("has_math", False))
