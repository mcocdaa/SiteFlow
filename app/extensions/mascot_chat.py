import json
import math
import re
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, field_validator, model_validator
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app import store
from app.auth import (
    client_ip,
    project_cookie_name,
    read_session,
    require_same_origin,
    verify_project_token,
)
from app.config import Config
from app.deps import DbSession, api_error, get_config
from app.extensions.inheritance import ResolvedExtension, resolve_project_extension
from app.extensions.mascot import (
    DEFAULT_API_BASE_URL,
    DEFAULT_API_PROTOCOL,
    DEFAULT_MODEL,
    DEFAULT_SYSTEM_PROMPT,
    resolve_effective_config,
)
from app.models import Project
from app.og import validate_public_host
from app.plugins import registry as plugins_registry
from app.surface import PageSurface

router = APIRouter()

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x20\x7f]")
_MAX_MESSAGES = 10
_MAX_MESSAGE_CHARS = 2000
_MAX_ASSISTANT_MESSAGE_CHARS = 8000
_MAX_POST_SLUG = 120
_MAX_PAGE_CONTEXT_CHARS = 3000
_MAX_CONTEXT_SCALAR_CHARS = 1500
_MAX_CONTEXT_LIST_ITEMS = 20
_MAX_CONTEXT_DEPTH = 4
_MAX_REPLY_CHARS = 16_000
_MAX_THINKING_CHARS = 16_000
_MAX_CHAT_KEYS = 10_000
_RATE_WINDOW_SECONDS = 60.0

_FIELD_LABELS: dict[str, str] = {
    "title": "标题",
    "description": "简介",
    "summary": "摘要",
    "name": "名称",
    "label": "头衔",
    "position": "职位",
    "institution": "学校",
    "area": "专业",
    "studyType": "学历",
    "startDate": "开始时间",
    "endDate": "结束时间",
    "date": "日期",
    "tags": "标签",
    "keywords": "关键词",
    "highlights": "要点",
    "body": "正文节选",
    "children": "可见子项",
    "work": "工作经历",
    "education": "教育经历",
    "projects": "项目经历",
    "skills": "技能",
    "basics": "基本信息",
    "post": "当前条目",
    "location": "所在地",
    "city": "城市",
    "region": "地区",
    "countryCode": "国家",
    "profiles": "社交链接",
    "network": "平台",
    "username": "用户名",
    "url": "链接",
    "email": "邮箱",
    "phone": "电话",
}

_chat_buckets: dict[tuple[str, str], deque[float]] = defaultdict(deque)


def reset_chat_rate_limits() -> None:
    _chat_buckets.clear()


def _check_rate_limit(key: tuple[str, str], limit: int) -> int | None:
    now = time.monotonic()
    bucket = _chat_buckets.get(key)
    if bucket is not None:
        while bucket and now - bucket[0] >= _RATE_WINDOW_SECONDS:
            bucket.popleft()
        if not bucket:
            _chat_buckets.pop(key, None)
            bucket = None
    if bucket is not None and len(bucket) >= limit:
        retry_after = max(1, math.ceil(_RATE_WINDOW_SECONDS - (now - bucket[0])))
        return retry_after
    if key not in _chat_buckets and len(_chat_buckets) >= _MAX_CHAT_KEYS:
        _chat_buckets.pop(next(iter(_chat_buckets)), None)
    _chat_buckets[key].append(now)
    return None


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("消息内容不能为空")
        return cleaned

    @model_validator(mode="after")
    def validate_content_length(self) -> "ChatMessage":
        limit = _MAX_ASSISTANT_MESSAGE_CHARS if self.role == "assistant" else _MAX_MESSAGE_CHARS
        if len(self.content) > limit:
            raise ValueError(f"单条消息长度不能超过 {limit} 字符")
        return self


class MascotChatRequest(BaseModel):
    messages: list[ChatMessage]
    post_slug: str | None = ""

    @field_validator("messages")
    @classmethod
    def validate_messages(cls, value: list[ChatMessage]) -> list[ChatMessage]:
        if not value or len(value) > _MAX_MESSAGES:
            raise ValueError("消息数量必须在 1 到 10 条之间")
        if value[-1].role != "user":
            raise ValueError("最后一条消息必须来自用户")
        return value

    @field_validator("post_slug")
    @classmethod
    def validate_post_slug(cls, value: str | None) -> str:
        if value is None:
            return ""
        cleaned = value.strip()
        if len(cleaned) > _MAX_POST_SLUG:
            raise ValueError("文章标识长度超出限制")
        return cleaned


@dataclass(frozen=True)
class _LoadedProject:
    project: Project
    raw_content: dict[str, object]
    surface: PageSurface
    mascot_resolved: ResolvedExtension | None = None


@dataclass(frozen=True)
class _PreparedChat:
    chat_access: str
    api_protocol: str
    raw_api_base_url: str
    api_key: str
    model: str
    enable_thinking: bool
    enable_web_search: bool
    enable_read_url: bool
    safety_check: str
    enable_title: bool
    system_prompt: str
    rate_limit_per_min: int


def _has_project_access(request: Request, config: Config, project: Project, is_admin: bool) -> bool:
    if not project.password_hash or is_admin:
        return True
    token = request.cookies.get(project_cookie_name(project.slug))
    return bool(token and verify_project_token(config, project.slug, token))


def _load_project_sync(
    db: Session,
    config: Config,
    request: Request,
    slug: str,
    post_slug: str,
    is_admin: bool,
) -> tuple[_LoadedProject | None, int, str]:
    project = store.by_slug(db, slug)
    if project is None:
        return None, 404, "项目不存在"
    plugin = plugins_registry.get(project.type)
    surface_fn = getattr(plugin, "surface", None)
    if plugin is None or not callable(surface_fn):
        return None, 404, "项目不存在"
    if not is_admin:
        if not store.is_visible(db, project):
            return None, 404, "项目不存在"
        if not _has_project_access(request, config, project, is_admin):
            return None, 401, "需要访问密码"
    try:
        parsed = json.loads(project.content or "{}")
    except json.JSONDecodeError:
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    surface = cast(PageSurface, surface_fn(request, project, db, sub=post_slug))
    mascot_resolved = resolve_project_extension(
        db,
        project,
        "mascot",
        capabilities=surface.capabilities,
        config=config,
        content=parsed,
    )
    return (
        _LoadedProject(
            project=project,
            raw_content=parsed,
            surface=surface,
            mascot_resolved=mascot_resolved,
        ),
        200,
        "",
    )


def _format_scalar(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value.strip()[:_MAX_CONTEXT_SCALAR_CHARS]
    return ""


def _is_container(value: object) -> bool:
    return isinstance(value, Mapping) or (
        isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))
    )


def _serialize_sequence(items: Sequence[Any], *, indent: int, depth: int) -> list[str]:
    if depth > _MAX_CONTEXT_DEPTH:
        return []
    trimmed = list(items)[:_MAX_CONTEXT_LIST_ITEMS]
    if not trimmed:
        return []
    if all(not _is_container(item) for item in trimmed):
        vals = [scalar for item in trimmed if (scalar := _format_scalar(item))]
        if not vals:
            return []
        if len(vals) <= 12 and all(len(v) <= 24 and "\n" not in v for v in vals):
            return ["、".join(vals)]
        prefix = "  " * indent
        return [f"{prefix}- {v}" for v in vals]
    prefix = "  " * indent
    out: list[str] = []
    for item in trimmed:
        if isinstance(item, Mapping):
            item_lines: list[str] = []
            _serialize_mapping(item, indent=indent + 1, depth=depth + 1, lines=item_lines)
            if item_lines:
                out.append(f"{prefix}- {item_lines[0].lstrip()}")
                out.extend(item_lines[1:])
        elif isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
            out.extend(_serialize_sequence(item, indent=indent + 1, depth=depth + 1))
        else:
            scalar = _format_scalar(item)
            if scalar:
                out.append(f"{prefix}- {scalar}")
    return out


def _serialize_mapping(
    data: Mapping[str, Any],
    *,
    indent: int,
    depth: int,
    lines: list[str],
    skip_exact: Mapping[str, str] | None = None,
) -> None:
    if depth > _MAX_CONTEXT_DEPTH:
        return
    prefix = "  " * indent
    for raw_key, value in data.items():
        key = str(raw_key).strip()
        if not key or value is None:
            continue
        label = _FIELD_LABELS.get(key, key)
        if isinstance(value, Mapping):
            sub_lines: list[str] = []
            _serialize_mapping(value, indent=indent + 1, depth=depth + 1, lines=sub_lines)
            if sub_lines:
                lines.append(f"{prefix}{label}：")
                lines.extend(sub_lines)
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            sub_lines = _serialize_sequence(value, indent=indent + 1, depth=depth + 1)
            if sub_lines:
                if len(sub_lines) == 1 and not sub_lines[0].startswith((" ", "-")):
                    lines.append(f"{prefix}{label}：{sub_lines[0]}")
                else:
                    lines.append(f"{prefix}{label}：")
                    lines.extend(sub_lines)
        else:
            scalar = _format_scalar(value)
            if not scalar:
                continue
            if skip_exact and skip_exact.get(key) == scalar:
                continue
            if "\n" in scalar:
                lines.append(f"{prefix}{label}：\n{scalar}")
            else:
                lines.append(f"{prefix}{label}：{scalar}")


def _build_page_context(surface: PageSurface) -> str:
    lines: list[str] = []
    meta_title = surface.meta.title.strip()[:200]
    meta_desc = surface.meta.description.strip()[:500]
    skip_exact: dict[str, str] = {}
    if meta_title:
        lines.append(f"标题：{meta_title}")
        skip_exact["title"] = meta_title
    if meta_desc:
        lines.append(f"简介：{meta_desc}")
        skip_exact["description"] = meta_desc
    ai_ctx = surface.context("ai")
    if isinstance(ai_ctx, Mapping):
        _serialize_mapping(ai_ctx, indent=0, depth=0, lines=lines, skip_exact=skip_exact)
    text = "\n".join(lines).strip()
    if len(text) > _MAX_PAGE_CONTEXT_CHARS:
        return text[: _MAX_PAGE_CONTEXT_CHARS - 1].rstrip() + "…"
    return text


def _prepare_chat(loaded: _LoadedProject) -> _PreparedChat | None:
    resolved = loaded.mascot_resolved
    if resolved is None or not resolved.effective_enabled:
        return None
    raw_cfg_dict = resolved.raw_merged_config
    normalized = resolved.effective_config
    explicit_base = raw_cfg_dict.get("api_base_url")
    if isinstance(explicit_base, str) and explicit_base.strip():
        raw_api_base_url = explicit_base.strip()
    else:
        raw_api_base_url = DEFAULT_API_BASE_URL
    trimmed_base = raw_api_base_url.rstrip("/")
    if (
        "api_protocol" not in raw_cfg_dict
        and trimmed_base.endswith("/v1")
        and not trimmed_base.endswith("/anthropic/v1")
    ):
        api_protocol = "openai"
    else:
        api_protocol = str(normalized.get("api_protocol", DEFAULT_API_PROTOCOL))
    effective = resolve_effective_config(loaded.surface.meta.type, normalized)
    base_prompt = str(effective.get("system_prompt") or "").strip() or DEFAULT_SYSTEM_PROMPT
    if bool(normalized.get("include_page_context", True)):
        page_context = _build_page_context(loaded.surface)
        if page_context:
            full_prompt = f"{base_prompt}\n\n[当前页面上下文]\n{page_context}"
        else:
            full_prompt = base_prompt
    else:
        full_prompt = base_prompt
    return _PreparedChat(
        chat_access=str(normalized.get("chat_access", "admin")),
        api_protocol=api_protocol,
        raw_api_base_url=raw_api_base_url,
        api_key=str(normalized.get("api_key", "")).strip(),
        model=str(normalized.get("model", DEFAULT_MODEL)),
        enable_thinking=bool(normalized.get("enable_thinking", True)),
        enable_web_search=bool(normalized.get("enable_web_search", False)),
        enable_read_url=bool(normalized.get("enable_read_url", False)),
        safety_check=str(normalized.get("safety_check", "high")),
        enable_title=bool(normalized.get("enable_title", False)),
        system_prompt=full_prompt,
        rate_limit_per_min=int(normalized.get("rate_limit_per_min", 10)),
    )


def _build_and_validate_endpoint(raw_base: str, protocol: str = DEFAULT_API_PROTOCOL) -> str:
    cleaned = raw_base.strip()
    if not cleaned or len(cleaned) > 300 or _CONTROL_CHAR_RE.search(cleaned):
        raise ValueError("API 接口地址格式不正确")
    parsed = urlparse(cleaned)
    _ = parsed.port
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("API 接口地址仅支持公网 https:// 地址")
    base = cleaned.rstrip("/")
    if protocol == "openai":
        endpoint = f"{base}/chat/completions" if base.endswith("/v1") else f"{base}/v1/chat/completions"
    elif base.endswith(("/anthropic/v1/messages", "/v1/messages")):
        endpoint = base
    elif base.endswith(("/anthropic/v1", "/v1")):
        endpoint = f"{base}/messages"
    elif base.endswith("/anthropic"):
        endpoint = f"{base}/v1/messages"
    else:
        endpoint = f"{base}/anthropic/v1/messages"
    validate_public_host(endpoint)
    return endpoint


def _extract_openai_deltas(chunk: object) -> tuple[str, str]:
    if not isinstance(chunk, dict):
        return "", ""
    choices = chunk.get("choices")
    if not isinstance(choices, list) or not choices:
        return "", ""
    first = choices[0]
    if not isinstance(first, dict):
        return "", ""
    delta = first.get("delta")
    if not isinstance(delta, dict):
        return "", ""
    reasoning = delta.get("reasoning_content")
    content = delta.get("content")
    return (
        reasoning if isinstance(reasoning, str) else "",
        content if isinstance(content, str) else "",
    )


def _tool_label(name: str) -> str:
    if name == "deepseek_web_search":
        return "正在联网搜索…"
    if name == "deepseek_read_url":
        return "正在读取网页…"
    return "正在调用工具…"


def _build_upstream_request(
    prepared: _PreparedChat,
    payload: MascotChatRequest,
) -> tuple[dict[str, str], dict[str, Any]]:
    if prepared.api_protocol == "openai":
        upstream_messages = [{"role": "system", "content": prepared.system_prompt}]
        for msg in payload.messages:
            upstream_messages.append({"role": msg.role, "content": msg.content})
        return (
            {
                "Authorization": f"Bearer {prepared.api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
            {
                "model": prepared.model,
                "messages": upstream_messages,
                "stream": True,
            },
        )
    body: dict[str, Any] = {
        "model": prepared.model,
        "max_tokens": 4096 if prepared.enable_thinking else 1536,
        "system": prepared.system_prompt,
        "messages": [{"role": msg.role, "content": msg.content} for msg in payload.messages],
        "stream": True,
        "thinking": {"type": "enabled" if prepared.enable_thinking else "disabled"},
    }
    tools: list[dict[str, str]] = []
    if prepared.enable_web_search:
        tools.append({"type": "deepseek_web_search", "name": "deepseek_web_search"})
    if prepared.enable_read_url:
        tools.append({"type": "deepseek_read_url", "name": "deepseek_read_url"})
    if tools:
        body["tools"] = tools
    if prepared.safety_check in ("low", "high"):
        body["safety_check"] = {"level": prepared.safety_check}
    if prepared.enable_title:
        body["title"] = {"enabled": True}
    return (
        {
            "x-api-key": prepared.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
        body,
    )


def _map_upstream_status(status_code: int) -> str:
    if status_code == 400:
        return "请求参数或内容未通过上游接口校验，请检查配置或换个提问"
    if status_code == 401:
        return "AI 接口鉴权失败，请检查密钥配置"
    if status_code == 402:
        return "AI 接口余额不足，请联系站点管理员"
    if status_code == 403:
        return "AI 接口拒绝访问，请检查密钥权限"
    if status_code == 404:
        return "AI 模型或接口地址不可用，请检查配置"
    if status_code == 429:
        return "AI 服务请求过于频繁，请稍后重试"
    if 300 <= status_code < 400:
        return "AI 接口返回了不受支持的重定向"
    if 500 <= status_code < 600:
        return "AI 上游服务暂时异常，请稍后重试"
    return "AI 对话服务暂时不可用，请稍后重试"


def _sse_data(payload: dict[str, str]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _iter_openai_sse(response: httpx.Response, request: Request) -> AsyncIterator[str]:
    thinking_chars = 0
    reply_chars = 0
    async for line in response.aiter_lines():
        if await request.is_disconnected():
            return
        trimmed = line.strip()
        if not trimmed or not trimmed.startswith("data:"):
            continue
        raw_data = trimmed[5:].strip()
        if not raw_data:
            continue
        if raw_data == "[DONE]":
            break
        try:
            chunk = json.loads(raw_data)
        except json.JSONDecodeError:
            continue
        reasoning, delta = _extract_openai_deltas(chunk)
        if reasoning:
            remaining_t = _MAX_THINKING_CHARS - thinking_chars
            if remaining_t > 0:
                piece = reasoning[:remaining_t]
                thinking_chars += len(piece)
                yield _sse_data({"thinking": piece})
        if delta:
            remaining_r = _MAX_REPLY_CHARS - reply_chars
            if remaining_r <= 0:
                break
            piece = delta[:remaining_r]
            reply_chars += len(piece)
            yield _sse_data({"delta": piece})
            if reply_chars >= _MAX_REPLY_CHARS:
                break


async def _iter_anthropic_sse(response: httpx.Response, request: Request) -> AsyncIterator[str]:
    block_types: dict[int, str] = {}
    current_event = ""
    thinking_chars = 0
    reply_chars = 0
    async for line in response.aiter_lines():
        if await request.is_disconnected():
            return
        trimmed = line.strip()
        if not trimmed:
            current_event = ""
            continue
        if trimmed.startswith("event:"):
            current_event = trimmed[6:].strip()
            continue
        if not trimmed.startswith("data:"):
            continue
        raw_data = trimmed[5:].strip()
        if not raw_data:
            continue
        if raw_data == "[DONE]":
            break
        try:
            chunk = json.loads(raw_data)
        except json.JSONDecodeError:
            current_event = ""
            continue
        if not isinstance(chunk, dict):
            current_event = ""
            continue
        raw_type = chunk.get("type")
        event_type = raw_type if isinstance(raw_type, str) and raw_type else current_event
        current_event = ""
        if event_type == "content_block_start":
            block = chunk.get("content_block")
            if isinstance(block, dict):
                block_type = str(block.get("type") or "")
                idx = chunk.get("index")
                if isinstance(idx, int):
                    block_types[idx] = block_type
                if block_type == "server_tool_use":
                    name = str(block.get("name") or "")
                    yield _sse_data({"tool": name, "status": "running", "label": _tool_label(name)})
                elif block_type in ("web_search_tool_result", "web_fetch_tool_result"):
                    yield _sse_data({"tool": block_type, "status": "done", "label": ""})
        elif event_type == "content_block_stop":
            idx = chunk.get("index")
            if isinstance(idx, int):
                block_types.pop(idx, None)
        elif event_type == "content_block_delta":
            delta = chunk.get("delta")
            if isinstance(delta, dict):
                delta_type = delta.get("type")
                if delta_type == "thinking_delta":
                    thinking = delta.get("thinking")
                    if isinstance(thinking, str) and thinking:
                        remaining_t = _MAX_THINKING_CHARS - thinking_chars
                        if remaining_t > 0:
                            piece = thinking[:remaining_t]
                            thinking_chars += len(piece)
                            yield _sse_data({"thinking": piece})
                elif delta_type == "text_delta":
                    text = delta.get("text")
                    if isinstance(text, str) and text:
                        remaining_r = _MAX_REPLY_CHARS - reply_chars
                        if remaining_r <= 0:
                            break
                        piece = text[:remaining_r]
                        reply_chars += len(piece)
                        yield _sse_data({"delta": piece})
                        if reply_chars >= _MAX_REPLY_CHARS:
                            break
        elif event_type == "message_delta":
            delta = chunk.get("delta")
            if isinstance(delta, dict):
                title = delta.get("title")
                if isinstance(title, str) and title.strip():
                    yield _sse_data({"title": title.strip()[:80]})
                if delta.get("stop_reason") == "refusal":
                    yield _sse_data({"error": "该内容未通过安全审查，请换个方式提问"})
        elif event_type == "error":
            yield _sse_data({"error": "AI 对话服务返回错误，请稍后重试"})
            break
        elif event_type == "message_stop":
            break


@router.post("/api/projects/{slug}/mascot/chat")
async def mascot_chat(
    request: Request,
    slug: str,
    payload: MascotChatRequest,
    db: DbSession,
) -> Response:
    if not _SLUG_RE.match(slug):
        return api_error("项目不存在", 404)
    config = get_config(request)
    session = read_session(config, request)
    is_admin = bool(session and session.get("admin") is True)
    loaded, status_code, error_msg = await run_in_threadpool(
        _load_project_sync, db, config, request, slug, payload.post_slug or "", is_admin
    )
    if loaded is None:
        return api_error(error_msg, status_code)
    require_same_origin(request)
    prepared = _prepare_chat(loaded)
    if prepared is None:
        return api_error("看板娘插件未启用", 404)
    if prepared.chat_access == "off":
        return api_error("AI 对话功能已关闭", 403)
    if prepared.chat_access == "admin" and not is_admin:
        return api_error("仅管理员可使用 AI 对话", 403)
    if not prepared.api_key:
        return api_error("AI 对话尚未配置 API 密钥", 503)
    retry_after = _check_rate_limit((client_ip(request), slug), prepared.rate_limit_per_min)
    if retry_after is not None:
        return JSONResponse(
            {"ok": False, "error": "对话请求过于频繁，请稍后再试"},
            status_code=429,
            headers={"Retry-After": str(retry_after)},
        )
    try:
        endpoint_url = await run_in_threadpool(
            _build_and_validate_endpoint,
            prepared.raw_api_base_url,
            prepared.api_protocol,
        )
    except (ValueError, OSError):
        return api_error("API 接口地址不安全或无法访问", 400)

    upstream_headers, upstream_body = _build_upstream_request(prepared, payload)

    async def _stream_reply() -> AsyncIterator[str]:
        try:
            async with (
                httpx.AsyncClient(
                    timeout=httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0),
                    follow_redirects=False,
                ) as client,
                client.stream(
                    "POST",
                    endpoint_url,
                    headers=upstream_headers,
                    json=upstream_body,
                ) as response,
            ):
                if response.status_code != 200:
                    yield _sse_data({"error": _map_upstream_status(response.status_code)})
                    yield "data: [DONE]\n\n"
                    return
                stream_iter = (
                    _iter_openai_sse(response, request)
                    if prepared.api_protocol == "openai"
                    else _iter_anthropic_sse(response, request)
                )
                async for event_str in stream_iter:
                    yield event_str
            if not await request.is_disconnected():
                yield "data: [DONE]\n\n"
        except httpx.TimeoutException:
            yield _sse_data({"error": "AI 服务响应超时，请稍后重试"})
            yield "data: [DONE]\n\n"
        except (httpx.HTTPError, OSError):
            yield _sse_data({"error": "无法连接到 AI 服务，请稍后重试"})
            yield "data: [DONE]\n\n"
        except (RuntimeError, ValueError):
            yield _sse_data({"error": "AI 对话服务暂时异常，请稍后重试"})
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        _stream_reply(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "X-Accel-Buffering": "no",
        },
    )
