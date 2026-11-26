import json
import re
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app import store, tokens
from app.deps import ApiAuth
from app.main import app, create_app
from app.models import Project
from tests.test_flow import auth_headers, login


def _app_with_whoami():
    if any(getattr(route, "path", None) == "/api/v1/whoami" for route in app.routes):
        return app
    isolated = create_app(app.state.config)

    @isolated.get("/api/v1/whoami")
    def _v1_whoami(ctx: ApiAuth) -> dict[str, object]:
        return {
            "ok": True,
            "api_version": "1",
            "site_title": ctx.config.site_title,
            "principal": {
                "kind": ctx.principal.kind,
                "is_admin": ctx.principal.is_admin,
                "scopes": sorted(ctx.principal.scopes),
                "allowed_slugs": (
                    sorted(ctx.principal.allowed_slugs) if ctx.principal.allowed_slugs is not None else None
                ),
                "token_id": ctx.principal.token_id,
                "name": ctx.principal.name,
                "prefix": ctx.principal.prefix,
            },
        }

    return isolated


def test_admin_page_renders_icon_only_token_button_dialog_and_script() -> None:
    with TestClient(app) as client:
        login(client)
        resp = client.get("/admin")
        assert resp.status_code == 200
        html = resp.text

        btn_match = re.search(
            r'<button\b[^>]*id="api-tokens-open-btn"[^>]*>(.*?)</button>',
            html,
            re.DOTALL,
        )
        assert btn_match is not None
        open_tag_match = re.search(r'<button\b[^>]*id="api-tokens-open-btn"[^>]*>', html)
        assert open_tag_match is not None
        open_tag = open_tag_match.group(0)
        assert 'class="header-icon-btn"' in open_tag
        assert 'aria-haspopup="dialog"' in open_tag
        assert 'aria-controls="api-tokens-dialog"' in open_tag
        assert 'data-hover-tip="API 令牌"' in open_tag
        assert 'data-i18n-hover-tip="admin.api_tokens"' in open_tag
        assert 'aria-label="API 令牌"' in open_tag
        assert 'data-i18n-aria-label="admin.api_tokens"' in open_tag

        inner_html = btn_match.group(1)
        assert "<svg" in inner_html
        visible_text = re.sub(r"<[^>]+>", "", inner_html).strip()
        assert visible_text == ""

        assert 'id="api-tokens-dialog"' in html
        assert 'class="site-ext-dialog api-tokens-dialog"' in html
        assert 'closedby="any"' in html
        assert "js/tokens_admin.js" in html
        assert 'data-token-preset="readonly"' in html
        assert 'data-token-preset="blog"' in html
        assert 'data-token-preset="admin"' in html
        for scope in tokens.VALID_SCOPES:
            assert f'value="{scope}"' in html


def test_admin_tokens_auth_csrf_and_low_priv_token_rejection() -> None:
    with store.session() as db:
        low_meta, low_raw = tokens.create_token(db, name="只读写作", scopes=["read", "posts:write"])
        _, scoped_admin_raw = tokens.create_token(
            db,
            name="限定空间超管",
            scopes=["admin"],
            allowed_slugs=["demo-space"],
        )

    with TestClient(app) as client:
        assert client.get("/api/admin/tokens").status_code == 401
        assert client.post("/api/admin/tokens", json={"name": "t", "scopes": ["read"]}).status_code == 401
        assert client.delete(f"/api/admin/tokens/{low_meta['id']}").status_code == 401

        for raw in (low_raw, scoped_admin_raw):
            headers = {"Authorization": f"Bearer {raw}"}
            r_get = client.get("/api/admin/tokens", headers=headers)
            assert r_get.status_code == 403
            assert r_get.json()["detail"] == "当前 API 令牌无权访问管理接口"

            r_post = client.post(
                "/api/admin/tokens",
                headers=headers,
                json={"name": "escalate", "scopes": ["admin"]},
            )
            assert r_post.status_code == 403

            r_del = client.delete(f"/api/admin/tokens/{low_meta['id']}", headers=headers)
            assert r_del.status_code == 403

            r_xkey = client.get("/api/admin/tokens", headers={"X-API-Key": raw})
            assert r_xkey.status_code == 403

        csrf = login(client)
        assert client.get("/api/admin/tokens").status_code == 403
        assert (
            client.post(
                "/api/admin/tokens",
                headers={"Origin": "http://testserver"},
                json={"name": "no-csrf", "scopes": ["read"]},
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/admin/tokens",
                headers={"Origin": "https://evil.example", "X-CSRF-Token": csrf},
                json={"name": "bad-origin", "scopes": ["read"]},
            ).status_code
            == 403
        )

        ok = client.get("/api/admin/tokens", headers=auth_headers(csrf))
        assert ok.status_code == 200
        assert ok.json()["ok"] is True


def test_admin_tokens_lifecycle_flat_projects_and_immediate_revocation() -> None:
    with store.session() as db:
        parent_space = Project(slug="tech-space", type="space", title="技术空间")
        db.add(parent_space)
        db.flush()
        child_blog = Project(
            slug="nested-blog",
            type="blog",
            title="子博客",
            parent_id=parent_space.id,
        )
        db.add(child_blog)
        db.commit()

    target_app = _app_with_whoami()
    with TestClient(target_app) as client:
        csrf = login(client)
        headers = auth_headers(csrf)

        future_iso = (datetime.now(UTC) + timedelta(days=30)).replace(microsecond=0).isoformat()
        create_resp = client.post(
            "/api/admin/tokens",
            headers=headers,
            json={
                "name": "博客写作 Agent",
                "scopes": ["read", "posts:write"],
                "allowed_slugs": ["tech-space", "nested-blog"],
                "expires_at": future_iso,
            },
        )
        assert create_resp.status_code == 201
        created_data = create_resp.json()
        assert created_data["ok"] is True
        plaintext = created_data["plaintext"]
        meta = created_data["token"]
        assert plaintext.startswith(tokens.TOKEN_PREFIX)
        assert meta["name"] == "博客写作 Agent"
        assert meta["prefix"] == plaintext[:12]
        assert meta["scopes"] == ["read", "posts:write"]
        assert meta["allowed_slugs"] == ["tech-space", "nested-blog"]
        assert meta["expires_at"] == future_iso
        assert "token_hash" not in meta
        assert plaintext not in json.dumps(meta)

        list_resp = client.get("/api/admin/tokens", headers=headers)
        assert list_resp.status_code == 200
        listed = list_resp.json()
        assert listed["ok"] is True
        assert listed["valid_scopes"] == list(tokens.VALID_SCOPES)
        assert len(listed["tokens"]) == 1
        assert listed["tokens"][0]["id"] == meta["id"]
        serialized_tokens = json.dumps(listed["tokens"])
        assert "token_hash" not in serialized_tokens
        assert plaintext not in serialized_tokens
        assert tokens.hash_token(plaintext) not in serialized_tokens

        project_slugs = {item["slug"]: item for item in listed["projects"]}
        assert "tech-space" in project_slugs
        assert "nested-blog" in project_slugs
        assert project_slugs["nested-blog"]["parent_slug"] == "tech-space"
        assert project_slugs["nested-blog"]["parent_id"] == project_slugs["tech-space"]["id"]

        who_before = client.get("/api/v1/whoami", headers={"Authorization": f"Bearer {plaintext}"})
        assert who_before.status_code == 200
        assert who_before.headers.get("cache-control") == "no-store"
        assert who_before.json()["principal"]["kind"] == "db_token"

        revoke_resp = client.delete(f"/api/admin/tokens/{meta['id']}", headers=headers)
        assert revoke_resp.status_code == 200
        assert revoke_resp.json() == {"ok": True, "revoked": True}

        who_after = client.get("/api/v1/whoami", headers={"Authorization": f"Bearer {plaintext}"})
        assert who_after.status_code == 401

        missing_resp = client.delete(f"/api/admin/tokens/{meta['id']}", headers=headers)
        assert missing_resp.status_code == 404
        assert missing_resp.json() == {"ok": False, "error": "令牌不存在"}

        admin_create = client.post(
            "/api/admin/tokens",
            headers=headers,
            json={"name": "全站管理令牌", "scopes": ["admin"], "allowed_slugs": []},
        )
        assert admin_create.status_code == 201
        admin_plain = admin_create.json()["plaintext"]
        admin_id = admin_create.json()["token"]["id"]

        assert (
            client.get("/api/admin/tokens", headers={"Authorization": f"Bearer {admin_plain}"}).status_code
            == 200
        )
        assert client.delete(f"/api/admin/tokens/{admin_id}", headers=headers).status_code == 200
        assert (
            client.get("/api/admin/tokens", headers={"Authorization": f"Bearer {admin_plain}"}).status_code
            == 401
        )


def test_admin_tokens_validation_errors_return_422() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        headers = auth_headers(csrf)
        past_iso = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()

        invalid_payloads = [
            {"name": "", "scopes": ["read"]},
            {"name": "   ", "scopes": ["read"]},
            {"name": "x" * 81, "scopes": ["read"]},
            {"name": "无权限", "scopes": []},
            {"name": "非法权限", "scopes": ["nonexistent:write"]},
            {"name": "非法项目标识", "scopes": ["read"], "allowed_slugs": ["BadSlug"]},
            {"name": "路径穿越", "scopes": ["read"], "allowed_slugs": ["../secret"]},
            {"name": "非法过期时间", "scopes": ["read"], "expires_at": "not-a-date"},
            {"name": "已过期时间", "scopes": ["read"], "expires_at": past_iso},
        ]
        for payload in invalid_payloads:
            resp = client.post("/api/admin/tokens", headers=headers, json=payload)
            assert resp.status_code == 422, f"payload={payload} got {resp.status_code}: {resp.text}"
            body = resp.json()
            assert body["ok"] is False
            assert isinstance(body["error"], str) and body["error"]
