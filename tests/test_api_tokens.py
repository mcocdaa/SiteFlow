import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import text

from app import store, tokens
from app.deps import (
    ApiAuth,
    ApiContext,
    DbSession,
    ServiceError,
    require_project_access,
    require_scope,
)
from app.main import app, create_app
from app.models import Project
from tests.test_flow import auth_headers, login


def test_create_list_verify_and_dedup_tokens() -> None:
    with store.session() as db:
        info1, raw1 = tokens.create_token(
            db,
            name="  写作 Agent  ",
            scopes=["posts:write", "read", "posts:write"],
            allowed_slugs=["my-blog", "my-space", "my-blog"],
        )
        assert raw1.startswith(tokens.TOKEN_PREFIX)
        assert info1["name"] == "写作 Agent"
        assert info1["prefix"] == raw1[:12]
        assert info1["scopes"] == ["posts:write", "read"]
        assert info1["allowed_slugs"] == ["my-blog", "my-space"]
        assert info1["last_used_at"] == ""
        assert info1["expires_at"] == ""
        assert "token_hash" not in info1
        assert "token" not in info1
        assert raw1 not in json.dumps(info1)

        future = (datetime.now(UTC) + timedelta(days=7)).replace(microsecond=0)
        info2, raw2 = tokens.create_token(
            db,
            name="全站管理员令牌",
            scopes=["admin"],
            allowed_slugs=None,
            expires_at=future.strftime("%Y-%m-%dT%H:%M:%S"),
        )
        assert info2["allowed_slugs"] == []
        assert info2["expires_at"] == future.isoformat()

        listed = tokens.list_tokens(db)
        assert [item["id"] for item in listed] == [info2["id"], info1["id"]]
        serialized = json.dumps(listed)
        assert "token_hash" not in serialized
        assert raw1 not in serialized
        assert raw2 not in serialized
        assert tokens.hash_token(raw1) not in serialized
        assert tokens.hash_token(raw2) not in serialized

        principal1 = tokens.verify_db_token(db, raw1)
        assert principal1 is not None
        assert principal1.kind == "db_token"
        assert principal1.is_admin is False
        assert principal1.scopes == frozenset({"posts:write", "read"})
        assert principal1.allowed_slugs == frozenset({"my-blog", "my-space"})
        assert principal1.token_id == info1["id"]
        assert principal1.name == "写作 Agent"
        assert principal1.prefix == raw1[:12]
        assert principal1.has_scope("posts:write") is True
        assert principal1.has_scope("deploy:write") is False
        assert principal1.can_access_slugs(["my-blog"]) is True
        assert principal1.can_access_slugs(["other"]) is False

        principal2 = tokens.verify_db_token(db, raw2)
        assert principal2 is not None
        assert principal2.is_admin is True
        assert principal2.allowed_slugs is None
        assert principal2.has_scope("deploy:write") is True
        assert principal2.can_access_slugs(["anything"]) is True


def test_token_validation_errors_and_max_limit() -> None:
    with store.session() as db:
        with pytest.raises(tokens.TokenError):
            tokens.create_token(db, name="", scopes=["read"])
        with pytest.raises(tokens.TokenError):
            tokens.create_token(db, name="   ", scopes=["read"])
        with pytest.raises(tokens.TokenError):
            tokens.create_token(db, name="a" * 81, scopes=["read"])
        with pytest.raises(tokens.TokenError):
            tokens.create_token(db, name="空权限", scopes=[])
        with pytest.raises(tokens.TokenError):
            tokens.create_token(db, name="非法权限", scopes=["unknown:write"])
        with pytest.raises(tokens.TokenError):
            tokens.normalize_scopes("read")
        with pytest.raises(tokens.TokenError):
            tokens.normalize_allowed_slugs("my-blog")

        for bad_slug in ("", "BadSlug", "-leading", "a/b", "../etc", "a" * 65, "valid\n"):
            with pytest.raises(tokens.TokenError):
                tokens.create_token(db, name="非法标识", scopes=["read"], allowed_slugs=[bad_slug])

        with pytest.raises(tokens.TokenError):
            tokens.normalize_expires_at("not-a-timestamp")
        past = (datetime.now(UTC) - timedelta(seconds=5)).isoformat()
        with pytest.raises(tokens.TokenError):
            tokens.normalize_expires_at(past)

        offset_future = (datetime.now(UTC) + timedelta(hours=2)).replace(microsecond=0)
        plus8 = (offset_future + timedelta(hours=8)).strftime("%Y-%m-%dT%H:%M:%S+08:00")
        assert tokens.normalize_expires_at(plus8) == offset_future.isoformat()
        assert tokens.normalize_expires_at("   ") == ""

        created_ids: list[int] = []
        for idx in range(tokens.MAX_TOKENS):
            info, _ = tokens.create_token(db, name=f"tok-{idx}", scopes=["read"])
            created_ids.append(info["id"])

        with pytest.raises(tokens.TokenError):
            tokens.create_token(db, name="overflow", scopes=["read"])

        assert tokens.revoke_token(db, created_ids[0]) is True
        assert tokens.revoke_token(db, created_ids[0]) is False
        replacement, _ = tokens.create_token(db, name="after-revoke", scopes=["read"])
        assert replacement["name"] == "after-revoke"


def test_token_expiry_revocation_and_last_used_throttle() -> None:
    with store.session() as db:
        assert tokens.verify_db_token(db, "") is None
        assert tokens.verify_db_token(db, "wrong_prefix_token") is None
        assert tokens.verify_db_token(db, f"{tokens.TOKEN_PREFIX}nonexistent") is None

        info, raw = tokens.create_token(db, name="节流测试", scopes=["read"])
        token_id = info["id"]

        assert tokens.verify_db_token(db, raw) is not None
        first_seen = tokens.list_tokens(db)[0]["last_used_at"]
        assert first_seen != ""

        recent = (datetime.now(UTC) - timedelta(seconds=30)).isoformat()
        db.execute(
            text("UPDATE api_tokens SET last_used_at = :ts WHERE id = :id"),
            {"ts": recent, "id": token_id},
        )
        db.commit()
        assert tokens.verify_db_token(db, raw) is not None
        assert tokens.list_tokens(db)[0]["last_used_at"] == recent

        stale = (datetime.now(UTC) - timedelta(seconds=65)).isoformat()
        db.execute(
            text("UPDATE api_tokens SET last_used_at = :ts WHERE id = :id"),
            {"ts": stale, "id": token_id},
        )
        db.commit()
        assert tokens.verify_db_token(db, raw) is not None
        refreshed = tokens.list_tokens(db)[0]["last_used_at"]
        assert refreshed != stale

        expired_ts = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        db.execute(
            text("UPDATE api_tokens SET expires_at = :ts WHERE id = :id"),
            {"ts": expired_ts, "id": token_id},
        )
        db.commit()
        assert tokens.verify_db_token(db, raw) is None

        db.execute(
            text("UPDATE api_tokens SET expires_at = 'corrupted-date' WHERE id = :id"),
            {"id": token_id},
        )
        db.commit()
        assert tokens.verify_db_token(db, raw) is None

        db.execute(
            text("UPDATE api_tokens SET expires_at = '' WHERE id = :id"),
            {"id": token_id},
        )
        db.commit()
        assert tokens.verify_db_token(db, raw) is not None

        assert tokens.revoke_token(db, token_id) is True
        assert tokens.verify_db_token(db, raw) is None


def test_scope_and_ancestor_project_access() -> None:
    with store.session() as db:
        root_space = Project(slug="root-space", type="space", title="根空间")
        db.add(root_space)
        db.flush()
        sub_space = Project(slug="sub-space", type="space", title="子空间", parent_id=root_space.id)
        db.add(sub_space)
        db.flush()
        leaf_blog = Project(slug="leaf-blog", type="blog", title="叶博客", parent_id=sub_space.id)
        other_proj = Project(slug="other-proj", type="blog", title="其他博客")
        db.add_all([leaf_blog, other_proj])
        db.commit()

        _, root_raw = tokens.create_token(
            db,
            name="根空间令牌",
            scopes=["posts:write"],
            allowed_slugs=["root-space"],
        )
        _, sub_raw = tokens.create_token(
            db,
            name="子空间管理令牌",
            scopes=["admin"],
            allowed_slugs=["sub-space"],
        )
        _, global_read_raw = tokens.create_token(
            db,
            name="全站只读",
            scopes=["read"],
            allowed_slugs=[],
        )

        root_principal = tokens.verify_db_token(db, root_raw)
        sub_principal = tokens.verify_db_token(db, sub_raw)
        global_read_principal = tokens.verify_db_token(db, global_read_raw)
        assert root_principal is not None
        assert sub_principal is not None
        assert global_read_principal is not None
        assert sub_principal.is_admin is False

        cfg = app.state.config
        root_ctx = ApiContext(config=cfg, principal=root_principal)
        sub_ctx = ApiContext(config=cfg, principal=sub_principal)
        read_ctx = ApiContext(config=cfg, principal=global_read_principal)

        require_scope(root_ctx, "posts:write")
        with pytest.raises(ServiceError) as exc_scope:
            require_scope(root_ctx, "projects:write")
        assert exc_scope.value.status_code == 403
        assert exc_scope.value.code == "forbidden_scope"
        assert "projects:write" in exc_scope.value.message
        assert "projects:write" in exc_scope.value.hint

        require_scope(sub_ctx, "deploy:write")

        require_project_access(root_ctx, db, root_space)
        require_project_access(root_ctx, db, sub_space)
        require_project_access(root_ctx, db, leaf_blog)
        with pytest.raises(ServiceError) as exc_proj:
            require_project_access(root_ctx, db, other_proj)
        assert exc_proj.value.status_code == 403
        assert exc_proj.value.code == "forbidden_project"
        assert exc_proj.value.hint != ""

        require_project_access(sub_ctx, db, sub_space)
        require_project_access(sub_ctx, db, leaf_blog)
        with pytest.raises(ServiceError):
            require_project_access(sub_ctx, db, root_space)
        with pytest.raises(ServiceError):
            require_project_access(sub_ctx, db, other_proj)

        require_project_access(read_ctx, db, other_proj)
        require_project_access(read_ctx, db, leaf_blog)


def test_admin_api_enforcement_for_db_tokens_env_token_and_session() -> None:
    with store.session() as db:
        _, low_raw = tokens.create_token(db, name="低权令牌", scopes=["read", "posts:write"])
        _, scoped_admin_raw = tokens.create_token(
            db,
            name="限定项目超管",
            scopes=["admin"],
            allowed_slugs=["only-one"],
        )
        full_info, full_admin_raw = tokens.create_token(db, name="全站超管", scopes=["admin"])

    env_token = app.state.config.api_token
    with TestClient(app) as client:
        unauth = client.get("/api/admin/projects")
        assert unauth.status_code == 401
        assert unauth.json()["detail"] == "需要登录"

        low_bearer = client.get("/api/admin/projects", headers={"Authorization": f"Bearer {low_raw}"})
        assert low_bearer.status_code == 403
        assert low_bearer.json()["detail"] == "当前 API 令牌无权访问管理接口"

        low_xkey = client.get("/api/admin/projects", headers={"X-API-Key": low_raw})
        assert low_xkey.status_code == 403
        assert low_xkey.json()["detail"] == "当前 API 令牌无权访问管理接口"

        scoped_resp = client.get(
            "/api/admin/projects",
            headers={"Authorization": f"Bearer {scoped_admin_raw}"},
        )
        assert scoped_resp.status_code == 403
        assert scoped_resp.json()["detail"] == "当前 API 令牌无权访问管理接口"

        full_bearer = client.get(
            "/api/admin/projects",
            headers={"Authorization": f"Bearer {full_admin_raw}"},
        )
        assert full_bearer.status_code == 200
        assert full_bearer.json() == {"ok": True, "projects": []}

        full_xkey = client.get("/api/admin/projects", headers={"X-API-Key": full_admin_raw})
        assert full_xkey.status_code == 200

        env_resp = client.get("/api/admin/projects", headers={"Authorization": f"Bearer {env_token}"})
        assert env_resp.status_code == 200

        bad_empty = client.get("/api/admin/projects", headers={"Authorization": "Bearer "})
        assert bad_empty.status_code == 401
        assert bad_empty.json()["detail"] == "无效的 API Token"

        with store.session() as db:
            assert tokens.revoke_token(db, full_info["id"]) is True
        revoked_resp = client.get(
            "/api/admin/projects",
            headers={"Authorization": f"Bearer {full_admin_raw}"},
        )
        assert revoked_resp.status_code == 401
        assert revoked_resp.json()["detail"] == "无效的 API Token"

        csrf = login(client)
        no_csrf = client.get("/api/admin/projects")
        assert no_csrf.status_code == 403
        assert no_csrf.json()["detail"] == "CSRF 校验失败"

        ok_session = client.get("/api/admin/projects", headers=auth_headers(csrf))
        assert ok_session.status_code == 200

        bad_token_with_session = client.get(
            "/api/admin/projects",
            headers={**auth_headers(csrf), "Authorization": "Bearer sft_invalid"},
        )
        assert bad_token_with_session.status_code == 401
        assert bad_token_with_session.json()["detail"] == "无效的 API Token"


def test_v1_error_handlers_validation_and_cache_headers() -> None:
    isolated = create_app(app.state.config)

    class SamplePayload(BaseModel):
        count: int

    @isolated.get("/api/v1/_test/whoami")
    def v1_whoami(ctx: ApiAuth) -> dict[str, object]:
        return {
            "ok": True,
            "kind": ctx.principal.kind,
            "is_admin": ctx.principal.is_admin,
            "scopes": sorted(ctx.principal.scopes),
            "allowed_slugs": (
                sorted(ctx.principal.allowed_slugs) if ctx.principal.allowed_slugs is not None else None
            ),
        }

    @isolated.get("/api/v1/_test/need-deploy/{slug}")
    def v1_need_deploy(slug: str, ctx: ApiAuth, db: DbSession) -> dict[str, object]:
        require_scope(ctx, "deploy:write")
        project = store.by_slug(db, slug)
        assert project is not None
        require_project_access(ctx, db, project)
        return {"ok": True, "slug": project.slug}

    @isolated.post("/api/v1/_test/validate")
    def v1_validate(payload: SamplePayload) -> dict[str, object]:
        return {"ok": True, "count": payload.count}

    @isolated.post("/api/other/_test/validate")
    def other_validate(payload: SamplePayload) -> dict[str, object]:
        return {"ok": True, "count": payload.count}

    @isolated.get("/api/other/_test/service-error")
    def other_service_error() -> dict[str, object]:
        raise ServiceError("普通接口错误", 409, code="conflict", hint="不会在非v1暴露")

    with store.session() as db:
        proj = Project(slug="demo-app", type="blog", title="演示应用")
        db.add(proj)
        db.commit()
        _, reader_raw = tokens.create_token(db, name="只读", scopes=["read"], allowed_slugs=["other-app"])
        _, deployer_raw = tokens.create_token(
            db, name="部署", scopes=["deploy:write"], allowed_slugs=["other-app"]
        )
        _, ok_raw = tokens.create_token(db, name="允许", scopes=["deploy:write"], allowed_slugs=["demo-app"])

    with TestClient(isolated) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/redoc").status_code == 404
        assert client.get("/openapi.json").status_code == 404

        who_env = client.get(
            "/api/v1/_test/whoami",
            headers={"Authorization": f"Bearer {app.state.config.api_token}"},
        )
        assert who_env.status_code == 200
        assert who_env.headers.get("cache-control") == "no-store"
        assert who_env.json()["kind"] == "env_token"
        assert who_env.json()["is_admin"] is True
        assert set(who_env.json()["scopes"]) == set(tokens.VALID_SCOPES)

        who_db = client.get("/api/v1/_test/whoami", headers={"X-API-Key": reader_raw})
        assert who_db.status_code == 200
        assert who_db.json()["kind"] == "db_token"
        assert who_db.json()["is_admin"] is False
        assert who_db.json()["allowed_slugs"] == ["other-app"]

        forbidden_scope = client.get(
            "/api/v1/_test/need-deploy/demo-app",
            headers={"Authorization": f"Bearer {reader_raw}"},
        )
        assert forbidden_scope.status_code == 403
        assert forbidden_scope.headers.get("cache-control") == "no-store"
        assert forbidden_scope.json() == {
            "ok": False,
            "code": "forbidden_scope",
            "error": "当前令牌缺少所需权限：deploy:write",
            "hint": "请使用具备 deploy:write 或 admin 权限的令牌",
        }

        forbidden_proj = client.get(
            "/api/v1/_test/need-deploy/demo-app",
            headers={"Authorization": f"Bearer {deployer_raw}"},
        )
        assert forbidden_proj.status_code == 403
        assert forbidden_proj.headers.get("cache-control") == "no-store"
        assert forbidden_proj.json() == {
            "ok": False,
            "code": "forbidden_project",
            "error": "当前 API 令牌无权访问该项目",
            "hint": "请在令牌允许的项目作用域内操作",
        }

        ok_deploy = client.get(
            "/api/v1/_test/need-deploy/demo-app",
            headers={"Authorization": f"Bearer {ok_raw}"},
        )
        assert ok_deploy.status_code == 200
        assert ok_deploy.json() == {"ok": True, "slug": "demo-app"}

        v1_bad = client.post("/api/v1/_test/validate", json={"count": "not-an-int"})
        assert v1_bad.status_code == 422
        assert v1_bad.headers.get("cache-control") == "no-store"
        v1_body = v1_bad.json()
        assert v1_body["ok"] is False
        assert v1_body["code"] == "validation_error"
        assert v1_body["error"] == "请求参数校验失败"
        assert isinstance(v1_body["details"], list) and len(v1_body["details"]) >= 1
        assert v1_body["hint"] == "请检查字段名与类型，或查看 GET /api/v1/openapi.json"

        other_bad = client.post("/api/other/_test/validate", json={"count": "not-an-int"})
        assert other_bad.status_code == 422
        other_body = other_bad.json()
        assert "detail" in other_body
        assert "ok" not in other_body

        other_srv = client.get("/api/other/_test/service-error")
        assert other_srv.status_code == 409
        assert other_srv.json() == {"ok": False, "error": "普通接口错误"}

        csrf = login(client)
        who_sess = client.get("/api/v1/_test/whoami", headers=auth_headers(csrf))
        assert who_sess.status_code == 200
        assert who_sess.json()["kind"] == "session"
        assert who_sess.json()["is_admin"] is True
