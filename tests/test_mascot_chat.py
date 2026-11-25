import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, ClassVar, Self

import httpx
import pytest
from fastapi.testclient import TestClient

from app import store
from app.extensions import mascot_chat
from app.main import app
from tests.test_apps import create_app
from tests.test_flow import ORIGIN, auth_headers, login

DEFAULT_ANTHROPIC_SSE = [
    "event: content_block_start",
    'data: {"type":"content_block_start","index":0,"content_block":{"type":"thinking"}}',
    "event: content_block_delta",
    'data: {"type":"content_block_delta","index":0,"delta":{"type":"thinking_delta","thinking":"先看文章结构"}}',
    "event: content_block_stop",
    'data: {"type":"content_block_stop","index":0}',
    "event: content_block_start",
    (
        'data: {"type":"content_block_start","index":1,'
        '"content_block":{"type":"server_tool_use","id":"t1","name":"deepseek_web_search"}}'
    ),
    "event: content_block_start",
    (
        'data: {"type":"content_block_start","index":2,'
        '"content_block":{"type":"web_search_tool_result","tool_use_id":"t1"}}'
    ),
    "event: content_block_delta",
    'data: {"type":"content_block_delta","index":3,"delta":{"type":"text_delta","text":"你好，"}}',
    "event: content_block_delta",
    'data: {"type":"content_block_delta","index":3,"delta":{"type":"text_delta","text":"我是大肥鱼！"}}',
    "event: message_delta",
    'data: {"type":"message_delta","delta":{"stop_reason":"end_turn","title":"文章核心总结"}}',
    "event: message_stop",
    'data: {"type":"message_stop"}',
]


class _FakeStreamResponse:
    def __init__(self, status_code: int = 200, lines: list[str] | None = None) -> None:
        self.status_code = status_code
        self._lines = lines or []

    async def aiter_lines(self) -> AsyncIterator[str]:
        for line in self._lines:
            yield line


class _FakeAsyncClient:
    captured: ClassVar[list[dict[str, Any]]] = []
    status_code: ClassVar[int] = 200
    lines: ClassVar[list[str] | None] = None
    raise_exc: ClassVar[Exception | None] = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.kwargs = kwargs

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    @asynccontextmanager
    async def stream(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> AsyncIterator[_FakeStreamResponse]:
        self.captured.append({"method": method, "url": url, "headers": headers or {}, "json": json or {}})
        if self.raise_exc is not None:
            raise self.raise_exc
        if self.lines is not None or self.status_code != 200:
            yield _FakeStreamResponse(self.status_code, self.lines or [])
            return
        yield _FakeStreamResponse(200, list(DEFAULT_ANTHROPIC_SSE))


def _patch_upstream(
    monkeypatch: pytest.MonkeyPatch,
    *,
    status_code: int = 200,
    lines: list[str] | None = None,
    raise_exc: Exception | None = None,
) -> list[dict[str, Any]]:
    _FakeAsyncClient.captured = []
    _FakeAsyncClient.status_code = status_code
    _FakeAsyncClient.lines = lines
    _FakeAsyncClient.raise_exc = raise_exc
    monkeypatch.setattr(mascot_chat, "validate_public_host", lambda url: "api.deepseek.com")
    monkeypatch.setattr(mascot_chat.httpx, "AsyncClient", _FakeAsyncClient)
    return _FakeAsyncClient.captured


def _parse_sse_events(body: str) -> list[str]:
    events: list[str] = []
    for line in body.splitlines():
        if line.startswith("data: "):
            events.append(line[6:])
    return events


def test_mascot_chat_anthropic_endpoint_resolution_and_payload_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_key = "sk-deepseek-anthropic-secret"
    with TestClient(app) as client:
        csrf = login(client)
        blog = create_app(client, csrf, "blog", "协议选项博客").json()["project"]
        pid, slug = blog["id"], blog["slug"]
        chat_url = f"/api/projects/{slug}/mascot/chat"

        assert (
            client.post(
                f"/api/admin/projects/{pid}/extensions/mascot/install",
                json={
                    "enabled": True,
                    "config": {
                        "chat_access": "public",
                        "api_protocol": "anthropic",
                        "api_base_url": "https://api.deepseek.com",
                        "api_key": secret_key,
                        "model": "deepseek-flash",
                        "enable_thinking": True,
                        "enable_web_search": False,
                        "enable_read_url": False,
                        "safety_check": "high",
                        "enable_title": False,
                        "rate_limit_per_min": 60,
                    },
                },
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )

        for raw_base, expected_endpoint in (
            ("https://api.deepseek.com", "https://api.deepseek.com/anthropic/v1/messages"),
            ("https://api.deepseek.com/anthropic", "https://api.deepseek.com/anthropic/v1/messages"),
            ("https://api.deepseek.com/anthropic/v1", "https://api.deepseek.com/anthropic/v1/messages"),
            (
                "https://api.deepseek.com/anthropic/v1/messages",
                "https://api.deepseek.com/anthropic/v1/messages",
            ),
        ):
            assert (
                client.patch(
                    f"/api/admin/projects/{pid}/extensions/mascot",
                    json={"config": {"api_base_url": raw_base}},
                    headers=auth_headers(csrf),
                ).status_code
                == 200
            )
            captured = _patch_upstream(monkeypatch)
            resp = client.post(
                chat_url,
                json={"messages": [{"role": "user", "content": "测试端点拼接"}]},
                headers=ORIGIN,
            )
            assert resp.status_code == 200
            assert len(captured) == 1
            assert captured[0]["url"] == expected_endpoint
            headers = captured[0]["headers"]
            assert headers["x-api-key"] == secret_key
            assert headers["anthropic-version"] == "2023-06-01"
            assert "authorization" not in {k.lower() for k in headers}

        body_default = captured[0]["json"]
        assert body_default["model"] == "deepseek-flash"
        assert body_default["max_tokens"] == 4096
        assert body_default["stream"] is True
        assert body_default["thinking"] == {"type": "enabled"}
        assert "tools" not in body_default
        assert body_default["safety_check"] == {"level": "high"}
        assert "title" not in body_default

        cases: list[tuple[dict[str, Any], dict[str, Any]]] = [
            (
                {
                    "enable_thinking": False,
                    "enable_web_search": True,
                    "enable_read_url": False,
                    "safety_check": "low",
                    "enable_title": True,
                },
                {
                    "max_tokens": 1536,
                    "thinking": {"type": "disabled"},
                    "tools": [{"type": "deepseek_web_search", "name": "deepseek_web_search"}],
                    "safety_check": {"level": "low"},
                    "title": {"enabled": True},
                },
            ),
            (
                {
                    "enable_thinking": True,
                    "enable_web_search": False,
                    "enable_read_url": True,
                    "safety_check": "off",
                    "enable_title": False,
                },
                {
                    "max_tokens": 4096,
                    "thinking": {"type": "enabled"},
                    "tools": [{"type": "deepseek_read_url", "name": "deepseek_read_url"}],
                    "safety_check": None,
                    "title": None,
                },
            ),
            (
                {
                    "enable_thinking": True,
                    "enable_web_search": True,
                    "enable_read_url": True,
                    "safety_check": "high",
                    "enable_title": True,
                },
                {
                    "max_tokens": 4096,
                    "thinking": {"type": "enabled"},
                    "tools": [
                        {"type": "deepseek_web_search", "name": "deepseek_web_search"},
                        {"type": "deepseek_read_url", "name": "deepseek_read_url"},
                    ],
                    "safety_check": {"level": "high"},
                    "title": {"enabled": True},
                },
            ),
        ]
        for cfg_patch, expected in cases:
            assert (
                client.patch(
                    f"/api/admin/projects/{pid}/extensions/mascot",
                    json={"config": cfg_patch},
                    headers=auth_headers(csrf),
                ).status_code
                == 200
            )
            captured = _patch_upstream(monkeypatch)
            resp = client.post(
                chat_url,
                json={"messages": [{"role": "user", "content": "检查请求载荷"}]},
                headers=ORIGIN,
            )
            assert resp.status_code == 200
            req_body = captured[0]["json"]
            assert req_body["max_tokens"] == expected["max_tokens"]
            assert req_body["thinking"] == expected["thinking"]
            assert req_body["tools"] == expected["tools"]
            if expected["safety_check"] is None:
                assert "safety_check" not in req_body
            else:
                assert req_body["safety_check"] == expected["safety_check"]
            if expected["title"] is None:
                assert "title" not in req_body
            else:
                assert req_body["title"] == expected["title"]


def test_mascot_chat_anthropic_sse_streaming_page_context_and_error_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_key = "sk-deepseek-secret-never-leak"
    with TestClient(app) as client:
        csrf = login(client)
        blog = create_app(client, csrf, "blog", "系统架构博客").json()["project"]
        assert (
            client.post(
                f"/api/admin/projects/{blog['id']}/posts",
                json={
                    "title": "零信任静态托管实战",
                    "slug": "zero-trust-post",
                    "date": "2026-11-24",
                    "tags": ["安全", "架构"],
                    "summary": "介绍沙箱 CSP 与隔离策略",
                    "body": "这是文章正文的关键技术细节：使用 sandbox CSP 与独立路径。",
                },
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert (
            client.post(
                f"/api/admin/projects/{blog['id']}/extensions/mascot/install",
                json={
                    "enabled": True,
                    "config": {
                        "chat_access": "public",
                        "api_base_url": "https://api.deepseek.com",
                        "api_key": secret_key,
                        "model": "deepseek-flash",
                        "enable_thinking": True,
                        "enable_web_search": True,
                        "enable_title": True,
                        "include_page_context": True,
                        "rate_limit_per_min": 60,
                    },
                },
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )

        space = create_app(client, csrf, "space", "工程作品空间").json()["project"]
        visible_child = create_app(client, csrf, "blog", "公开子项目", parent_id=space["id"]).json()[
            "project"
        ]
        hidden_child = create_app(client, csrf, "blog", "隐藏子项目", parent_id=space["id"]).json()["project"]
        assert visible_child["parent_id"] == space["id"]
        assert (
            client.patch(
                f"/api/admin/projects/{hidden_child['id']}",
                json={"visible": False},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert (
            client.post(
                f"/api/admin/projects/{space['id']}/extensions/mascot/install",
                json={
                    "enabled": True,
                    "config": {
                        "chat_access": "public",
                        "api_base_url": "https://api.deepseek.com",
                        "api_key": secret_key,
                        "include_page_context": True,
                        "rate_limit_per_min": 60,
                    },
                },
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )

        captured = _patch_upstream(monkeypatch)
        resp = client.post(
            f"/api/projects/{blog['slug']}/mascot/chat",
            json={
                "messages": [{"role": "user", "content": "总结一下这篇文章"}],
                "post_slug": "zero-trust-post",
            },
            headers=ORIGIN,
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        assert resp.headers["x-accel-buffering"] == "no"
        events = _parse_sse_events(resp.text)
        assert events[-1] == "[DONE]"
        parsed_events = [json.loads(item) for item in events[:-1]]
        assert parsed_events == [
            {"thinking": "先看文章结构"},
            {"tool": "deepseek_web_search", "status": "running", "label": "正在联网搜索…"},
            {"tool": "web_search_tool_result", "status": "done", "label": ""},
            {"delta": "你好，"},
            {"delta": "我是大肥鱼！"},
            {"title": "文章核心总结"},
        ]
        assert len(captured) == 1
        assert captured[0]["url"] == "https://api.deepseek.com/anthropic/v1/messages"
        assert captured[0]["headers"]["x-api-key"] == secret_key
        assert captured[0]["headers"]["anthropic-version"] == "2023-06-01"
        assert "Authorization" not in captured[0]["headers"]
        sys_prompt = captured[0]["json"]["system"]
        assert "系统架构博客" in sys_prompt
        assert "零信任静态托管实战" in sys_prompt
        assert "sandbox CSP" in sys_prompt

        captured = _patch_upstream(monkeypatch)
        space_resp = client.post(
            f"/api/projects/{space['slug']}/mascot/chat",
            json={"messages": [{"role": "user", "content": "这个空间有什么作品？"}]},
            headers=ORIGIN,
        )
        assert space_resp.status_code == 200
        assert captured[0]["url"] == "https://api.deepseek.com/anthropic/v1/messages"
        space_sys = captured[0]["json"]["system"]
        assert "工程作品空间" in space_sys
        assert "公开子项目" in space_sys
        assert "隐藏子项目" not in space_sys

        _patch_upstream(
            monkeypatch,
            lines=[
                "event: content_block_start",
                (
                    'data: {"type":"content_block_start","index":0,'
                    '"content_block":{"type":"server_tool_use","id":"r1","name":"deepseek_read_url"}}'
                ),
                "event: content_block_start",
                (
                    'data: {"type":"content_block_start","index":1,'
                    '"content_block":{"type":"web_fetch_tool_result","tool_use_id":"r1"}}'
                ),
                "event: message_delta",
                'data: {"type":"message_delta","delta":{"stop_reason":"refusal"}}',
                "event: message_stop",
                'data: {"type":"message_stop"}',
            ],
        )
        refusal_resp = client.post(
            f"/api/projects/{blog['slug']}/mascot/chat",
            json={"messages": [{"role": "user", "content": "测试拒答"}]},
            headers=ORIGIN,
        )
        assert refusal_resp.status_code == 200
        refusal_events = _parse_sse_events(refusal_resp.text)
        assert refusal_events[-1] == "[DONE]"
        refusal_parsed = [json.loads(item) for item in refusal_events[:-1]]
        assert refusal_parsed[0] == {
            "tool": "deepseek_read_url",
            "status": "running",
            "label": "正在读取网页…",
        }
        assert refusal_parsed[1] == {"tool": "web_fetch_tool_result", "status": "done", "label": ""}
        assert "安全审查" in refusal_parsed[2]["error"]

        _patch_upstream(
            monkeypatch,
            lines=[
                "event: error",
                f'data: {{"type":"error","error":{{"message":"internal {secret_key}"}}}}',
            ],
        )
        stream_err_resp = client.post(
            f"/api/projects/{blog['slug']}/mascot/chat",
            json={"messages": [{"role": "user", "content": "测试流内错误"}]},
            headers=ORIGIN,
        )
        assert stream_err_resp.status_code == 200
        assert secret_key not in stream_err_resp.text
        stream_err_events = _parse_sse_events(stream_err_resp.text)
        assert stream_err_events[-1] == "[DONE]"
        assert "返回错误" in json.loads(stream_err_events[0])["error"]

        for upstream_status, expected_snippet in (
            (400, "未通过上游接口校验"),
            (401, "鉴权失败"),
            (429, "过于频繁"),
            (500, "暂时异常"),
        ):
            _patch_upstream(
                monkeypatch,
                status_code=upstream_status,
                lines=[f"raw upstream secret body {secret_key}"],
            )
            err_resp = client.post(
                f"/api/projects/{blog['slug']}/mascot/chat",
                json={"messages": [{"role": "user", "content": "测试错误"}]},
                headers=ORIGIN,
            )
            assert err_resp.status_code == 200
            assert secret_key not in err_resp.text
            assert "raw upstream" not in err_resp.text
            err_events = _parse_sse_events(err_resp.text)
            assert err_events[-1] == "[DONE]"
            err_payload = json.loads(err_events[0])
            assert expected_snippet in err_payload["error"]

        _patch_upstream(monkeypatch, raise_exc=httpx.ReadTimeout("timeout"))
        timeout_resp = client.post(
            f"/api/projects/{blog['slug']}/mascot/chat",
            json={"messages": [{"role": "user", "content": "测试超时"}]},
            headers=ORIGIN,
        )
        assert timeout_resp.status_code == 200
        assert secret_key not in timeout_resp.text
        timeout_events = _parse_sse_events(timeout_resp.text)
        assert "超时" in json.loads(timeout_events[0])["error"]
        assert timeout_events[-1] == "[DONE]"


def test_mascot_chat_openai_compat_and_legacy_v1_autofallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_key = "sk-openai-compat-secret"
    openai_lines = [
        'data: {"choices":[{"delta":{"reasoning_content":"梳理要点中"}}]}',
        'data: {"choices":[{"delta":{"content":"你好，"}}]}',
        'data: {"choices":[{"delta":{"content":"兼容模式正常！"}}]}',
        "data: [DONE]",
    ]
    with TestClient(app) as client:
        csrf = login(client)
        blog = create_app(client, csrf, "blog", "OpenAI兼容博客").json()["project"]
        pid, slug = blog["id"], blog["slug"]
        chat_url = f"/api/projects/{slug}/mascot/chat"

        assert (
            client.post(
                f"/api/admin/projects/{pid}/extensions/mascot/install",
                json={
                    "enabled": True,
                    "config": {
                        "chat_access": "public",
                        "api_protocol": "openai",
                        "api_base_url": "https://api.deepseek.com",
                        "api_key": secret_key,
                        "model": "deepseek-reasoner",
                        "rate_limit_per_min": 60,
                    },
                },
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )

        captured = _patch_upstream(monkeypatch, lines=openai_lines)
        resp = client.post(
            chat_url,
            json={"messages": [{"role": "user", "content": "测试 OpenAI 模式"}]},
            headers=ORIGIN,
        )
        assert resp.status_code == 200
        assert captured[0]["url"] == "https://api.deepseek.com/v1/chat/completions"
        assert captured[0]["headers"]["Authorization"] == f"Bearer {secret_key}"
        assert "x-api-key" not in captured[0]["headers"]
        assert captured[0]["json"]["messages"][0]["role"] == "system"
        events = _parse_sse_events(resp.text)
        assert events[-1] == "[DONE]"
        assert [json.loads(item) for item in events[:-1]] == [
            {"thinking": "梳理要点中"},
            {"delta": "你好，"},
            {"delta": "兼容模式正常！"},
        ]

        with store.session() as db:
            row = store.by_id(db, pid)
            assert row is not None
            parsed = json.loads(row.content)
            mascot_cfg = parsed["extensions"]["mascot"]["config"]
            mascot_cfg.pop("api_protocol", None)
            mascot_cfg["api_base_url"] = "https://api.deepseek.com/v1"
            row.content = json.dumps(parsed, ensure_ascii=False)
            db.commit()

        captured_legacy = _patch_upstream(monkeypatch, lines=openai_lines)
        legacy_resp = client.post(
            chat_url,
            json={"messages": [{"role": "user", "content": "测试旧版 /v1 自动回退"}]},
            headers=ORIGIN,
        )
        assert legacy_resp.status_code == 200
        assert captured_legacy[0]["url"] == "https://api.deepseek.com/v1/chat/completions"
        assert captured_legacy[0]["headers"]["Authorization"] == f"Bearer {secret_key}"
        legacy_events = _parse_sse_events(legacy_resp.text)
        assert [json.loads(item) for item in legacy_events[:-1]] == [
            {"thinking": "梳理要点中"},
            {"delta": "你好，"},
            {"delta": "兼容模式正常！"},
        ]

        with store.session() as db:
            row = store.by_id(db, pid)
            assert row is not None
            parsed = json.loads(row.content)
            mascot_cfg = parsed["extensions"]["mascot"]["config"]
            mascot_cfg.pop("api_protocol", None)
            mascot_cfg["api_base_url"] = "https://api.deepseek.com/anthropic/v1"
            row.content = json.dumps(parsed, ensure_ascii=False)
            db.commit()

        captured_anth = _patch_upstream(monkeypatch)
        anth_resp = client.post(
            chat_url,
            json={"messages": [{"role": "user", "content": "测试 /anthropic/v1 走 Messages"}]},
            headers=ORIGIN,
        )
        assert anth_resp.status_code == 200
        assert captured_anth[0]["url"] == "https://api.deepseek.com/anthropic/v1/messages"
        assert captured_anth[0]["headers"]["x-api-key"] == secret_key


def test_mascot_chat_access_gates_origin_ssrf_validation_and_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_key = "sk-gate-test-key"
    with TestClient(app) as admin_client, TestClient(app) as guest_client:
        csrf = login(admin_client)
        blog = create_app(admin_client, csrf, "blog", "门禁测试博客").json()["project"]
        pid, slug = blog["id"], blog["slug"]
        chat_url = f"/api/projects/{slug}/mascot/chat"
        valid_body = {"messages": [{"role": "user", "content": "你好"}]}

        assert (
            admin_client.post(
                f"/api/admin/projects/{pid}/extensions/mascot/install",
                json={
                    "enabled": True,
                    "config": {
                        "chat_access": "off",
                        "api_key": secret_key,
                        "rate_limit_per_min": 60,
                    },
                },
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        _patch_upstream(monkeypatch)
        assert guest_client.post(chat_url, json=valid_body, headers=ORIGIN).status_code == 403
        assert admin_client.post(chat_url, json=valid_body, headers=ORIGIN).status_code == 403

        assert (
            admin_client.patch(
                f"/api/admin/projects/{pid}/extensions/mascot",
                json={"config": {"chat_access": "admin"}},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert guest_client.post(chat_url, json=valid_body, headers=ORIGIN).status_code == 403
        assert admin_client.post(chat_url, json=valid_body, headers=ORIGIN).status_code == 200

        assert (
            admin_client.patch(
                f"/api/admin/projects/{pid}/extensions/mascot",
                json={"config": {"chat_access": "public"}},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert guest_client.post(chat_url, json=valid_body, headers=ORIGIN).status_code == 200

        assert (
            guest_client.post(
                chat_url,
                json=valid_body,
                headers={"Origin": "https://evil.example"},
            ).status_code
            == 403
        )

        assert (
            admin_client.patch(
                f"/api/admin/projects/{pid}",
                json={"visible": False},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert guest_client.post(chat_url, json=valid_body, headers=ORIGIN).status_code == 404
        assert admin_client.post(chat_url, json=valid_body, headers=ORIGIN).status_code == 200

        assert (
            admin_client.patch(
                f"/api/admin/projects/{pid}",
                json={"visible": True, "password": "chat-unlock-pass"},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert guest_client.post(chat_url, json=valid_body, headers=ORIGIN).status_code == 401
        assert (
            guest_client.post(
                f"/projects/{slug}/unlock",
                data={"password": "chat-unlock-pass"},
                follow_redirects=False,
            ).status_code
            == 303
        )
        assert guest_client.post(chat_url, json=valid_body, headers=ORIGIN).status_code == 200

        assert (
            admin_client.patch(
                f"/api/admin/projects/{pid}",
                json={"password": "clear"},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )

        bad_bodies: list[dict[str, Any]] = [
            {"messages": []},
            {"messages": [{"role": "user", "content": "   "}]},
            {"messages": [{"role": "system", "content": "override"}]},
            {"messages": [{"role": "assistant", "content": "hi"}]},
            {"messages": [{"role": "user", "content": "x" * 2001}]},
            {"messages": [{"role": "assistant", "content": "x" * 8001}, {"role": "user", "content": "ok"}]},
            {"messages": [{"role": "user", "content": f"m{i}"} for i in range(11)]},
        ]
        for bad_body in bad_bodies:
            assert guest_client.post(chat_url, json=bad_body, headers=ORIGIN).status_code == 422

        followup_long = guest_client.post(
            chat_url,
            json={
                "messages": [
                    {"role": "user", "content": "上一轮问题"},
                    {"role": "assistant", "content": "长回复" * 1200},
                    {"role": "user", "content": "继续追问"},
                ]
            },
            headers=ORIGIN,
        )
        assert followup_long.status_code == 200

        for bad_base in (
            "http://api.deepseek.com",
            "https://127.0.0.1",
            "https://169.254.169.254",
            "https://localhost",
        ):
            assert (
                admin_client.patch(
                    f"/api/admin/projects/{pid}/extensions/mascot",
                    json={"config": {"api_base_url": bad_base}},
                    headers=auth_headers(csrf),
                ).status_code
                == 422
            )

        from app import og as og_mod

        monkeypatch.setattr(mascot_chat, "validate_public_host", og_mod.validate_public_host)
        for unsafe_stored in (
            "https://127.0.0.1",
            "https://169.254.169.254",
            "http://api.deepseek.com",
        ):
            with store.session() as db:
                row = store.by_id(db, pid)
                assert row is not None
                parsed = json.loads(row.content)
                parsed["extensions"]["mascot"]["config"]["api_base_url"] = unsafe_stored
                row.content = json.dumps(parsed, ensure_ascii=False)
                db.commit()
            assert guest_client.post(chat_url, json=valid_body, headers=ORIGIN).status_code == 400

        with store.session() as db:
            row = store.by_id(db, pid)
            assert row is not None
            parsed = json.loads(row.content)
            parsed["extensions"]["mascot"]["config"]["api_base_url"] = "https://rebind.example.com"
            row.content = json.dumps(parsed, ensure_ascii=False)
            db.commit()
        monkeypatch.setattr(
            og_mod.socket,
            "getaddrinfo",
            lambda host, port: [(2, 1, 6, "", ("10.0.0.8", 0))],
        )
        assert guest_client.post(chat_url, json=valid_body, headers=ORIGIN).status_code == 400

        mascot_chat.reset_chat_rate_limits()
        assert (
            admin_client.patch(
                f"/api/admin/projects/{pid}/extensions/mascot",
                json={"config": {"api_base_url": "https://api.deepseek.com", "rate_limit_per_min": 2}},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        _patch_upstream(monkeypatch)
        assert guest_client.post(chat_url, json=valid_body, headers=ORIGIN).status_code == 200
        assert guest_client.post(chat_url, json=valid_body, headers=ORIGIN).status_code == 200
        limited = guest_client.post(chat_url, json=valid_body, headers=ORIGIN)
        assert limited.status_code == 429
        assert int(limited.headers["retry-after"]) >= 1
