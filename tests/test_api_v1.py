import io
import json
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app import og, store, tokens
from app.main import app
from app.og import OpenGraph
from app.views import SANDBOX_CSP
from tests.test_flow import auth_headers, login


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _png_bytes(color: tuple[int, int, int] = (30, 140, 210)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), color).save(buf, format="PNG")
    return buf.getvalue()


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _media_path(url: str) -> Path:
    return Path(app.state.config.data) / url.lstrip("/")


def _create_db_token(
    name: str,
    scopes: list[str],
    allowed_slugs: list[str] | None = None,
    expires_at: str = "",
) -> tuple[dict, str]:
    with store.session() as db:
        return tokens.create_token(
            db,
            name=name,
            scopes=scopes,
            allowed_slugs=allowed_slugs,
            expires_at=expires_at,
        )


def test_auth_whoami_and_openapi_discovery() -> None:
    env_token = app.state.config.api_token
    writer_meta, writer_token = _create_db_token(
        "仅写作令牌",
        ["posts:write"],
        allowed_slugs=["demo-blog"],
    )
    reader_meta, reader_token = _create_db_token("全站只读令牌", ["read"])

    with TestClient(app) as client:
        unauth_who = client.get("/api/v1/whoami")
        assert unauth_who.status_code == 401
        assert unauth_who.headers.get("cache-control") == "no-store"

        unauth_schema = client.get("/api/v1/openapi.json")
        assert unauth_schema.status_code == 401
        assert unauth_schema.headers.get("cache-control") == "no-store"

        bad_tok = client.get("/api/v1/whoami", headers=_bearer("sft_does_not_exist"))
        assert bad_tok.status_code == 401

        who_env = client.get("/api/v1/whoami", headers=_bearer(env_token))
        assert who_env.status_code == 200
        assert who_env.headers.get("cache-control") == "no-store"
        env_body = who_env.json()
        assert env_body["ok"] is True
        assert env_body["api_version"] == "1"
        assert env_body["site_title"] == app.state.config.site_title
        assert env_body["principal"]["kind"] == "env_token"
        assert env_body["principal"]["is_admin"] is True
        assert env_body["principal"]["allowed_slugs"] is None
        assert set(env_body["principal"]["scopes"]) == set(tokens.VALID_SCOPES)

        who_writer = client.get("/api/v1/whoami", headers={"X-API-Key": writer_token})
        assert who_writer.status_code == 200
        writer_p = who_writer.json()["principal"]
        assert writer_p["kind"] == "db_token"
        assert writer_p["is_admin"] is False
        assert writer_p["scopes"] == ["posts:write"]
        assert writer_p["allowed_slugs"] == ["demo-blog"]
        assert writer_p["token_id"] == writer_meta["id"]
        assert writer_p["name"] == "仅写作令牌"
        assert writer_p["prefix"] == writer_meta["prefix"]

        forbidden_schema = client.get("/api/v1/openapi.json", headers=_bearer(writer_token))
        assert forbidden_schema.status_code == 403
        assert forbidden_schema.json()["code"] == "forbidden_scope"
        assert forbidden_schema.headers.get("cache-control") == "no-store"

        ok_schema = client.get("/api/v1/openapi.json", headers=_bearer(reader_token))
        assert ok_schema.status_code == 200
        assert ok_schema.headers.get("cache-control") == "no-store"
        schema = ok_schema.json()
        assert schema["openapi"].startswith("3.1")
        paths = list(schema["paths"].keys())
        assert len(paths) >= 15
        assert all(path.startswith("/api/v1/") for path in paths)
        assert "/api/v1/whoami" in schema["paths"]
        assert "/api/v1/projects" in schema["paths"]
        assert "/api/v1/blogs/{slug}/posts" in schema["paths"]
        assert "/api/v1/tokens" in schema["paths"]
        schemes = schema["components"]["securitySchemes"]
        assert schemes["BearerAuth"]["type"] == "http"
        assert schemes["BearerAuth"]["scheme"] == "bearer"
        assert schemes["ApiKeyAuth"]["type"] == "apiKey"
        assert schemes["ApiKeyAuth"]["in"] == "header"
        assert schemes["ApiKeyAuth"]["name"] == "X-API-Key"
        assert {"BearerAuth": []} in schema["security"]
        assert {"ApiKeyAuth": []} in schema["security"]

        bad_query = client.get("/api/v1/projects?view=invalid", headers=_bearer(reader_token))
        assert bad_query.status_code == 422
        assert bad_query.headers.get("cache-control") == "no-store"
        assert bad_query.json()["ok"] is False
        assert bad_query.json()["code"] == "validation_error"
        assert reader_meta["id"] > 0

        csrf = login(client)
        who_session = client.get("/api/v1/whoami", headers=auth_headers(csrf))
        assert who_session.status_code == 200
        assert who_session.json()["principal"]["kind"] == "session"
        assert who_session.json()["principal"]["is_admin"] is True


def test_security_matrix_scopes_slugs_inheritance_and_escape_prevention(monkeypatch) -> None:
    monkeypatch.setattr(og, "fetch_og", lambda url: None)
    monkeypatch.setattr(og, "fetch_image", lambda url: None)

    admin_hdr = _bearer(app.state.config.api_token)
    with TestClient(app) as client:
        assert (
            client.post(
                "/api/v1/projects/app",
                headers=admin_hdr,
                json={"type": "space", "title": "空间 A", "slug": "space-a"},
            ).status_code
            == 201
        )
        assert (
            client.post(
                "/api/v1/projects/app",
                headers=admin_hdr,
                json={"type": "space", "title": "子空间 A1", "slug": "sub-a1", "parent_slug": "space-a"},
            ).status_code
            == 201
        )
        assert (
            client.post(
                "/api/v1/projects/app",
                headers=admin_hdr,
                json={"type": "blog", "title": "子博客", "slug": "child-blog", "parent_slug": "sub-a1"},
            ).status_code
            == 201
        )
        assert (
            client.post(
                "/api/v1/projects/app",
                headers=admin_hdr,
                json={"type": "space", "title": "空间 B", "slug": "space-b"},
            ).status_code
            == 201
        )
        assert (
            client.post(
                "/api/v1/projects/app",
                headers=admin_hdr,
                json={"type": "blog", "title": "外部博客", "slug": "other-blog", "parent_slug": "space-b"},
            ).status_code
            == 201
        )

        _, scoped_raw = _create_db_token(
            "空间 A 协作者",
            ["read", "projects:write", "posts:write", "deploy:write"],
            allowed_slugs=["space-a"],
        )
        _, readonly_raw = _create_db_token("空间 A 只读", ["read"], allowed_slugs=["space-a"])
        _, root_slug_raw = _create_db_token(
            "定向根项目令牌",
            ["read", "projects:write", "deploy:write"],
            allowed_slugs=["allowed-root"],
        )
        scoped_hdr = _bearer(scoped_raw)
        readonly_hdr = _bearer(readonly_raw)
        root_slug_hdr = _bearer(root_slug_raw)

        tree_resp = client.get("/api/v1/projects?view=tree", headers=scoped_hdr)
        assert tree_resp.status_code == 200
        assert [p["slug"] for p in tree_resp.json()["projects"]] == ["space-a"]

        flat_resp = client.get("/api/v1/projects?view=flat", headers=scoped_hdr)
        assert {p["slug"] for p in flat_resp.json()["projects"]} == {"space-a", "sub-a1", "child-blog"}

        assert client.get("/api/v1/projects/other-blog", headers=scoped_hdr).status_code == 403
        assert client.get("/api/v1/projects/other-blog", headers=scoped_hdr).json()["code"] == (
            "forbidden_project"
        )

        write_child_post = client.post(
            "/api/v1/blogs/child-blog/posts",
            headers=scoped_hdr,
            json={"title": "祖先作用域继承写作", "slug": "inherited-post", "body": "正文"},
        )
        assert write_child_post.status_code == 201
        assert write_child_post.json()["post"]["slug"] == "inherited-post"

        write_other_post = client.post(
            "/api/v1/blogs/other-blog/posts",
            headers=scoped_hdr,
            json={"title": "越权文章", "body": "x"},
        )
        assert write_other_post.status_code == 403
        assert write_other_post.json()["code"] == "forbidden_project"

        no_scope_create = client.post(
            "/api/v1/projects/app",
            headers=readonly_hdr,
            json={"type": "blog", "title": "无写权限", "parent_slug": "space-a"},
        )
        assert no_scope_create.status_code == 403
        assert no_scope_create.json()["code"] == "forbidden_scope"

        for bad_payload in (
            {"type": "blog", "title": "根目录逃逸无标识"},
            {"type": "blog", "title": "根目录逃逸自定义标识", "slug": "escape-root"},
            {"type": "blog", "title": "跨空间创建", "parent_slug": "space-b"},
        ):
            res = client.post("/api/v1/projects/app", headers=scoped_hdr, json=bad_payload)
            assert res.status_code == 403
            assert res.json()["code"] == "forbidden_project"

        ok_child_app = client.post(
            "/api/v1/projects/app",
            headers=scoped_hdr,
            json={
                "type": "resume",
                "title": "空间内简历",
                "slug": "in-space-resume",
                "parent_slug": "space-a",
            },
        )
        assert ok_child_app.status_code == 201
        assert ok_child_app.json()["project"]["parent_slug"] == "space-a"

        bad_link = client.post(
            "/api/v1/projects/link",
            headers=scoped_hdr,
            json={"url": "https://example.com", "slug": "escape-link"},
        )
        assert bad_link.status_code == 403
        assert bad_link.json()["code"] == "forbidden_project"

        ok_link = client.post(
            "/api/v1/projects/link",
            headers=scoped_hdr,
            json={"url": "https://example.com/ok", "slug": "scoped-link", "parent_slug": "space-a"},
        )
        assert ok_link.status_code == 201

        ok_root_app = client.post(
            "/api/v1/projects/app",
            headers=root_slug_hdr,
            json={"type": "blog", "title": "允许的根博客", "slug": "allowed-root"},
        )
        assert ok_root_app.status_code == 201
        bad_root_app = client.post(
            "/api/v1/projects/app",
            headers=root_slug_hdr,
            json={"type": "blog", "title": "不允许的根博客", "slug": "disallowed-root"},
        )
        assert bad_root_app.status_code == 403

        html_file = ("index.html", b"<h1>hello</h1>", "text/html")
        dep_escape = client.put(
            "/api/v1/projects/escape-static/deploy",
            headers=scoped_hdr,
            files={"file": html_file},
        )
        assert dep_escape.status_code == 403
        assert dep_escape.json()["code"] == "forbidden_project"

        dep_wrong_parent = client.put(
            "/api/v1/projects/bad-parent-static/deploy",
            headers=scoped_hdr,
            files={"file": html_file},
            data={"parent_slug": "space-b"},
        )
        assert dep_wrong_parent.status_code == 403
        assert dep_wrong_parent.json()["code"] == "forbidden_project"

        dep_hijack = client.put(
            "/api/v1/projects/other-blog/deploy",
            headers=scoped_hdr,
            files={"file": html_file},
            data={"parent_slug": "space-a"},
        )
        assert dep_hijack.status_code == 403
        assert dep_hijack.json()["code"] == "forbidden_project"

        dep_ok = client.put(
            "/api/v1/projects/scoped-static/deploy",
            headers=scoped_hdr,
            files={"file": html_file},
            data={"parent_slug": "space-a", "title": "空间内静态页"},
        )
        assert dep_ok.status_code == 201
        assert dep_ok.json()["project"]["parent_slug"] == "space-a"

        escape_root_null = client.patch(
            "/api/v1/projects/child-blog",
            headers=scoped_hdr,
            json={"parent_slug": None},
        )
        assert escape_root_null.status_code == 403
        assert escape_root_null.json()["code"] == "forbidden_project"

        escape_root_empty = client.patch(
            "/api/v1/projects/child-blog",
            headers=scoped_hdr,
            json={"parent_slug": ""},
        )
        assert escape_root_empty.status_code == 403
        assert escape_root_empty.json()["code"] == "forbidden_project"

        escape_other_parent = client.patch(
            "/api/v1/projects/child-blog",
            headers=scoped_hdr,
            json={"parent_slug": "space-b"},
        )
        assert escape_other_parent.status_code == 403
        assert escape_other_parent.json()["code"] == "forbidden_project"

        move_within_scope = client.patch(
            "/api/v1/projects/child-blog",
            headers=scoped_hdr,
            json={"parent_slug": "space-a"},
        )
        assert move_within_scope.status_code == 200
        assert move_within_scope.json()["project"]["parent_slug"] == "space-a"

        pwd_no_admin = client.patch(
            "/api/v1/projects/child-blog",
            headers=scoped_hdr,
            json={"password": "NewPassword!9"},
        )
        assert pwd_no_admin.status_code == 403
        assert pwd_no_admin.json()["code"] == "forbidden_scope"

        pwd_clear_no_admin = client.patch(
            "/api/v1/projects/child-blog",
            headers=scoped_hdr,
            json={"password": None},
        )
        assert pwd_clear_no_admin.status_code == 403
        assert pwd_clear_no_admin.json()["code"] == "forbidden_scope"

        pwd_set = client.patch(
            "/api/v1/projects/child-blog",
            headers=admin_hdr,
            json={"password": "LockedPass!1"},
        )
        assert pwd_set.status_code == 200
        assert pwd_set.json()["project"]["has_password"] is True

        title_only = client.patch(
            "/api/v1/projects/child-blog",
            headers=scoped_hdr,
            json={"title": "改名不清除密码"},
        )
        assert title_only.status_code == 200
        assert title_only.json()["project"]["has_password"] is True
        assert title_only.json()["project"]["parent_slug"] == "space-a"

        pwd_clear = client.patch(
            "/api/v1/projects/child-blog",
            headers=admin_hdr,
            json={"password": None},
        )
        assert pwd_clear.status_code == 200
        assert pwd_clear.json()["project"]["has_password"] is False


def test_projects_crud_cover_and_link_flow(monkeypatch) -> None:
    monkeypatch.setattr(
        og,
        "fetch_og",
        lambda url: OpenGraph(title="外部文档", description="自动抓取简介", image_url="https://ex.com/a.png"),
    )
    monkeypatch.setattr(og, "fetch_image", lambda url: _png_bytes((200, 60, 40)))

    hdr = _bearer(app.state.config.api_token)
    with TestClient(app) as client:
        sp = client.post(
            "/api/v1/projects/app",
            headers=hdr,
            json={"type": "space", "title": "工作区", "slug": "work-hub"},
        )
        assert sp.status_code == 201

        lk = client.post(
            "/api/v1/projects/link",
            headers=hdr,
            json={"url": "https://example.com/guide", "parent_slug": "work-hub", "slug": "ext-guide"},
        )
        assert lk.status_code == 201
        lk_proj = lk.json()["project"]
        assert lk_proj["title"] == "外部文档"
        assert lk_proj["description"] == "自动抓取简介"
        assert lk_proj["cover"] == "ext-guide.webp"
        assert lk_proj["parent_slug"] == "work-hub"

        filtered = client.get("/api/v1/projects?view=flat&type=link&parent_slug=work-hub", headers=hdr)
        assert filtered.status_code == 200
        assert [p["slug"] for p in filtered.json()["projects"]] == ["ext-guide"]

        detail = client.get("/api/v1/projects/work-hub", headers=hdr)
        assert detail.status_code == 200
        d_body = detail.json()
        assert d_body["ok"] is True
        assert d_body["project"]["slug"] == "work-hub"
        assert [c["slug"] for c in d_body["children"]] == ["ext-guide"]
        assert "today_pv" in d_body["stats"]

        cov1 = client.post(
            "/api/v1/projects/work-hub/cover",
            headers=hdr,
            files={"file": ("cover.png", _png_bytes((10, 180, 120)), "image/png")},
        )
        assert cov1.status_code == 200
        cover_name_1 = cov1.json()["project"]["cover"]
        assert cover_name_1.startswith("work-hub-") and cover_name_1.endswith(".webp")
        assert (Path(app.state.config.data) / "media" / "covers" / cover_name_1).is_file()

        cov2 = client.post(
            "/api/v1/projects/work-hub/cover",
            headers=hdr,
            files={"file": ("cover2.png", _png_bytes((180, 10, 120)), "image/png")},
        )
        assert cov2.status_code == 200
        cover_name_2 = cov2.json()["project"]["cover"]
        assert cover_name_2 != cover_name_1
        assert not (Path(app.state.config.data) / "media" / "covers" / cover_name_1).exists()
        assert (Path(app.state.config.data) / "media" / "covers" / cover_name_2).is_file()

        del_cov = client.delete("/api/v1/projects/work-hub/cover", headers=hdr)
        assert del_cov.status_code == 200
        assert del_cov.json()["project"]["cover"] == ""
        assert not (Path(app.state.config.data) / "media" / "covers" / cover_name_2).exists()

        del_proj = client.delete("/api/v1/projects/work-hub", headers=hdr)
        assert del_proj.status_code == 200
        assert del_proj.json() == {"ok": True, "deleted": True, "slug": "work-hub"}
        assert client.get("/api/v1/projects/ext-guide", headers=hdr).status_code == 404


def test_blog_posts_full_lifecycle_and_media_gc() -> None:
    hdr = _bearer(app.state.config.api_token)
    with TestClient(app) as client:
        assert (
            client.post(
                "/api/v1/projects/app",
                headers=hdr,
                json={"type": "blog", "title": "工程博客", "slug": "eng-blog"},
            ).status_code
            == 201
        )
        assert (
            client.post(
                "/api/v1/projects/app",
                headers=hdr,
                json={"type": "space", "title": "普通空间", "slug": "not-a-blog"},
            ).status_code
            == 201
        )

        not_blog = client.get("/api/v1/blogs/not-a-blog/posts", headers=hdr)
        assert not_blog.status_code == 400
        assert not_blog.json()["code"] == "not_a_blog"

        img1_res = client.post(
            "/api/v1/blogs/eng-blog/media",
            headers=hdr,
            files={"file": ("diagram.png", _png_bytes((20, 80, 220)), "image/png")},
            data={"kind": "image"},
        )
        assert img1_res.status_code == 200
        img1 = img1_res.json()
        assert img1["ok"] is True
        assert img1["url"].startswith("/media/blog/eng-blog/image-")
        assert img1["url"].endswith(".webp")
        assert img1["markdown"] == f"![]({img1['url']})"

        public_img = client.get(img1["url"])
        assert public_img.status_code == 200
        assert public_img.headers.get("content-type", "").startswith("image/webp")

        img2_res = client.post(
            "/api/v1/blogs/eng-blog/media",
            headers=hdr,
            files={"file": ("extra.png", _png_bytes((220, 80, 20)), "image/png")},
            data={"kind": "image"},
        )
        assert img2_res.status_code == 200
        img2_url = img2_res.json()["url"]

        cover_res = client.post(
            "/api/v1/blogs/eng-blog/media",
            headers=hdr,
            files={"file": ("cov.png", _png_bytes((80, 220, 20)), "image/png")},
            data={"kind": "cover"},
        )
        assert cover_res.status_code == 200
        cover_url = cover_res.json()["url"]

        created = client.post(
            "/api/v1/blogs/eng-blog/posts",
            headers=hdr,
            json={
                "slug": "architecture-notes",
                "title": "架构手记",
                "tags": ["Python", "API"],
                "summary": "关于 Agent-Ready API 的设计记录",
                "body": f"正文配图：{img1['markdown']}\n配图二：![]({img2_url})",
                "meta": {"cover": cover_url, "cover_alt": "封面图"},
            },
        )
        assert created.status_code == 201
        post_data = created.json()["post"]
        assert post_data["slug"] == "architecture-notes"
        assert post_data["url"] == "/projects/eng-blog/posts/architecture-notes"
        assert "draft" not in post_data

        dup = client.post(
            "/api/v1/blogs/eng-blog/posts",
            headers=hdr,
            json={"slug": "architecture-notes", "title": "冲突文章", "body": "重复"},
        )
        assert dup.status_code == 409
        assert dup.json()["code"] == "post_slug_exists"

        list_no_body = client.get("/api/v1/blogs/eng-blog/posts", headers=hdr)
        assert list_no_body.status_code == 200
        assert list_no_body.json()["total"] == 1
        assert "body" not in list_no_body.json()["posts"][0]

        list_filtered = client.get(
            "/api/v1/blogs/eng-blog/posts?tag=python&q=Agent-Ready&include_body=true",
            headers=hdr,
        )
        assert list_filtered.status_code == 200
        assert list_filtered.json()["total"] == 1
        assert img1["url"] in list_filtered.json()["posts"][0]["body"]

        list_miss = client.get("/api/v1/blogs/eng-blog/posts?tag=rust", headers=hdr)
        assert list_miss.status_code == 200
        assert list_miss.json()["total"] == 0

        patched = client.patch(
            "/api/v1/blogs/eng-blog/posts/architecture-notes",
            headers=hdr,
            json={"title": "架构手记（修订版）"},
        )
        assert patched.status_code == 200
        patched_post = patched.json()["post"]
        assert patched_post["title"] == "架构手记（修订版）"
        assert patched_post["tags"] == ["Python", "API"]
        assert patched_post["summary"] == "关于 Agent-Ready API 的设计记录"
        assert img1["url"] in patched_post["body"]
        assert img2_url in patched_post["body"]
        assert patched_post["meta"] == {"cover": cover_url, "cover_alt": "封面图"}

        put_create = client.put(
            "/api/v1/blogs/eng-blog/posts/weekly-digest",
            headers=hdr,
            json={
                "title": "周刊第 1 期",
                "tags": ["周刊"],
                "summary": "第一版摘要",
                "body": "第一版正文",
                "meta": {"cover": cover_url},
            },
        )
        assert put_create.status_code == 201
        assert put_create.json()["created"] is True
        assert put_create.json()["post"]["slug"] == "weekly-digest"

        put_update = client.put(
            "/api/v1/blogs/eng-blog/posts/weekly-digest",
            headers=hdr,
            json={
                "title": "周刊第 1 期（终稿）",
                "tags": ["周刊", "归档"],
                "summary": "终稿摘要",
                "body": "终稿正文",
            },
        )
        assert put_update.status_code == 200
        assert put_update.json()["created"] is False
        assert put_update.json()["post"]["title"] == "周刊第 1 期（终稿）"
        assert put_update.json()["post"]["meta"] == {"cover": cover_url}

        after_upsert = client.get("/api/v1/blogs/eng-blog/posts", headers=hdr)
        assert after_upsert.json()["total"] == 2

        single = client.get("/api/v1/blogs/eng-blog/posts/weekly-digest", headers=hdr)
        assert single.status_code == 200
        assert single.json()["post"]["body"] == "终稿正文"

        rename_conflict = client.patch(
            "/api/v1/blogs/eng-blog/posts/weekly-digest",
            headers=hdr,
            json={"new_slug": "architecture-notes"},
        )
        assert rename_conflict.status_code == 409
        assert rename_conflict.json()["code"] == "post_slug_exists"

        drop_img2 = client.patch(
            "/api/v1/blogs/eng-blog/posts/architecture-notes",
            headers=hdr,
            json={"body": f"只保留第一张：{img1['markdown']}"},
        )
        assert drop_img2.status_code == 200
        assert _media_path(img1["url"]).is_file()
        assert not _media_path(img2_url).exists()

        del_post = client.delete("/api/v1/blogs/eng-blog/posts/architecture-notes", headers=hdr)
        assert del_post.status_code == 200
        assert del_post.json() == {"ok": True, "deleted": True, "slug": "architecture-notes"}
        assert not _media_path(img1["url"]).exists()
        assert _media_path(cover_url).is_file()


def test_structured_content_patch_preserves_extensions_and_redacts_secrets() -> None:
    hdr = _bearer(app.state.config.api_token)
    secret_val = "sk-live-agent-secret-998877"

    with TestClient(app) as client:
        assert (
            client.post(
                "/api/v1/projects/app",
                headers=hdr,
                json={"type": "resume", "title": "林深简历", "slug": "dev-resume"},
            ).status_code
            == 201
        )
        assert (
            client.post(
                "/api/v1/projects/app",
                headers=hdr,
                json={"type": "space", "title": "主题空间", "slug": "theme-space"},
            ).status_code
            == 201
        )

        ext_put = client.put(
            "/api/v1/projects/dev-resume/extensions/mascot",
            headers=hdr,
            json={
                "mode": "override",
                "config": {
                    "character": "dafeiyu",
                    "greeting": "你好，欢迎了解我的简历",
                    "api_key": secret_val,
                },
            },
        )
        assert ext_put.status_code == 200
        assert secret_val not in ext_put.text
        assert ext_put.json()["extension"]["secrets_set"]["api_key"] is True

        init_resume = client.patch(
            "/api/v1/projects/dev-resume/content",
            headers=hdr,
            json={
                "basics": {
                    "name": "林深",
                    "label": "后端工程师",
                    "email": "lin@example.com",
                    "location": {"city": "上海", "region": "浦东"},
                }
            },
        )
        assert init_resume.status_code == 200
        assert secret_val not in init_resume.text

        partial_resume = client.patch(
            "/api/v1/projects/dev-resume/content",
            headers=hdr,
            json={"basics": {"label": "首席系统架构师", "location": {"city": "深圳"}}},
        )
        assert partial_resume.status_code == 200
        assert secret_val not in partial_resume.text
        body = partial_resume.json()["content"]
        assert body["basics"]["name"] == "林深"
        assert body["basics"]["email"] == "lin@example.com"
        assert body["basics"]["label"] == "首席系统架构师"
        assert body["basics"]["location"]["city"] == "深圳"
        assert body["basics"]["location"]["region"] == "浦东"
        assert body["extensions"]["mascot"]["config"]["api_key"] == ""

        get_content = client.get("/api/v1/projects/dev-resume/content", headers=hdr)
        assert get_content.status_code == 200
        assert secret_val not in get_content.text

        with store.session() as db:
            proj = store.by_slug(db, "dev-resume")
            assert proj is not None
            raw_stored = json.loads(proj.content)
            assert raw_stored["extensions"]["mascot"]["config"]["api_key"] == secret_val

        sp1 = client.patch(
            "/api/v1/projects/theme-space/content",
            headers=hdr,
            json={"accent": "#0ea5e9", "font_family": "serif"},
        )
        assert sp1.status_code == 200
        sp2 = client.patch(
            "/api/v1/projects/theme-space/content",
            headers=hdr,
            json={"radius_card": "20px"},
        )
        assert sp2.status_code == 200
        assert sp2.json()["content"]["accent"] == "#0ea5e9"
        assert sp2.json()["content"]["font_family"] == "serif"
        assert sp2.json()["content"]["radius_card"] == "20px"

        bad_type = client.patch(
            "/api/v1/projects/theme-space/content",
            headers={**hdr, "Content-Type": "application/json"},
            content='"not-an-object"',
        )
        assert bad_type.status_code == 422
        assert bad_type.json()["code"] == "validation_error"


def test_static_deploy_idempotent_html_and_zip() -> None:
    hdr = _bearer(app.state.config.api_token)
    with TestClient(app) as client:
        first = client.put(
            "/api/v1/projects/landing-demo/deploy",
            headers=hdr,
            files={"file": ("index.html", b"<!doctype html><h1>V1 HTML</h1>", "text/html")},
            data={"title": "静态落地页", "description": "初版", "visible": "false"},
        )
        assert first.status_code == 201
        first_body = first.json()
        assert first_body["ok"] is True
        assert first_body["created"] is True
        assert first_body["url"] == "/p/landing-demo/"
        assert first_body["project"]["visible"] is False

        assert (
            client.patch(
                "/api/v1/projects/landing-demo",
                headers=hdr,
                json={"visible": True},
            ).status_code
            == 200
        )

        pub_v1 = client.get("/projects/landing-demo/")
        assert pub_v1.status_code == 200
        assert "V1 HTML" in pub_v1.text
        assert pub_v1.headers.get("content-security-policy") == SANDBOX_CSP

        assert (
            client.patch(
                "/api/v1/projects/landing-demo",
                headers=hdr,
                json={"visible": False},
            ).status_code
            == 200
        )

        archive = _zip_bytes(
            {
                "dist/index.html": b"<!doctype html><h1>V2 ZIP</h1><script src='app.js'></script>",
                "dist/app.js": b"console.log('ok');",
            }
        )
        second = client.put(
            "/api/v1/projects/landing-demo/deploy",
            headers=hdr,
            files={"file": ("site.zip", archive, "application/zip")},
        )
        assert second.status_code == 200
        second_body = second.json()
        assert second_body["created"] is False
        assert second_body["project"]["visible"] is False
        assert second_body["project"]["entry"] == "dist/index.html"

        assert (
            client.patch(
                "/api/v1/projects/landing-demo",
                headers=hdr,
                json={"visible": True},
            ).status_code
            == 200
        )
        pub_v2 = client.get("/projects/landing-demo/")
        assert pub_v2.status_code == 200
        assert "V2 ZIP" in pub_v2.text

        bad_ext = client.put(
            "/api/v1/projects/landing-demo/deploy",
            headers=hdr,
            files={"file": ("readme.txt", b"plain text", "text/plain")},
        )
        assert bad_ext.status_code == 400
        assert bad_ext.json()["code"] == "unsupported_file_type"

        bad_zip = client.put(
            "/api/v1/projects/landing-demo/deploy",
            headers=hdr,
            files={"file": ("empty.zip", _zip_bytes({"other.txt": b"no index"}), "application/zip")},
        )
        assert bad_zip.status_code == 422
        assert bad_zip.json()["code"] == "invalid_upload"

        assert (
            client.post(
                "/api/v1/projects/app",
                headers=hdr,
                json={"type": "blog", "title": "冲突博客", "slug": "busy-blog"},
            ).status_code
            == 201
        )
        conflict = client.put(
            "/api/v1/projects/busy-blog/deploy",
            headers=hdr,
            files={"file": ("index.html", b"<h1>conflict</h1>", "text/html")},
        )
        assert conflict.status_code == 409
        assert conflict.json()["code"] == "slug_type_conflict"


def test_extensions_v1_crud_and_inheritance(monkeypatch) -> None:
    monkeypatch.setattr(og, "fetch_og", lambda url: None)
    monkeypatch.setattr(og, "fetch_image", lambda url: None)
    hdr = _bearer(app.state.config.api_token)
    parent_secret = "sk-parent-space-secret-123"

    with TestClient(app) as client:
        assert (
            client.post(
                "/api/v1/projects/app",
                headers=hdr,
                json={"type": "space", "title": "父空间", "slug": "ext-space"},
            ).status_code
            == 201
        )
        assert (
            client.post(
                "/api/v1/projects/app",
                headers=hdr,
                json={"type": "blog", "title": "子博客", "slug": "ext-blog", "parent_slug": "ext-space"},
            ).status_code
            == 201
        )
        assert (
            client.post(
                "/api/v1/projects/link",
                headers=hdr,
                json={"url": "https://example.com", "slug": "ext-link"},
            ).status_code
            == 201
        )

        unsupported = client.get("/api/v1/projects/ext-link/extensions", headers=hdr)
        assert unsupported.status_code == 400
        assert unsupported.json()["code"] == "extensions_unsupported"

        set_parent = client.put(
            "/api/v1/projects/ext-space/extensions/mascot",
            headers=hdr,
            json={
                "mode": "override",
                "cascade": True,
                "config": {"greeting": "空间欢迎你", "api_key": parent_secret},
            },
        )
        assert set_parent.status_code == 200
        assert parent_secret not in set_parent.text
        parent_ext = set_parent.json()["extension"]
        assert parent_ext["effective_enabled"] is True
        assert parent_ext["cascade"] is True
        assert parent_ext["secrets_set"]["api_key"] is True

        child_list = client.get("/api/v1/projects/ext-blog/extensions", headers=hdr)
        assert child_list.status_code == 200
        assert parent_secret not in child_list.text
        mascot_item = next(item for item in child_list.json()["extensions"] if item["id"] == "mascot")
        assert mascot_item["effective_enabled"] is True
        assert mascot_item["source"] == "ancestor"
        assert mascot_item["source_slug"] == "ext-space"
        assert mascot_item["secrets_set"]["api_key"] is True
        assert mascot_item["secret_inherited"]["api_key"] is True

        disable_child = client.put(
            "/api/v1/projects/ext-blog/extensions/mascot",
            headers=hdr,
            json={"mode": "disabled"},
        )
        assert disable_child.status_code == 200
        assert disable_child.json()["extension"]["effective_enabled"] is False
        assert disable_child.json()["extension"]["local_mode"] == "disabled"

        inherit_child = client.put(
            "/api/v1/projects/ext-blog/extensions/mascot",
            headers=hdr,
            json={"mode": "inherit"},
        )
        assert inherit_child.status_code == 200
        assert inherit_child.json()["extension"]["effective_enabled"] is True
        assert inherit_child.json()["extension"]["local_mode"] == "inherit"

        incompatible = client.put(
            "/api/v1/projects/ext-blog/extensions/resume_style",
            headers=hdr,
            json={"enabled": True},
        )
        assert incompatible.status_code == 400
        assert incompatible.json()["code"] == "extension_incompatible"

        unknown = client.put(
            "/api/v1/projects/ext-blog/extensions/nonexistent_ext",
            headers=hdr,
            json={"enabled": True},
        )
        assert unknown.status_code == 404
        assert unknown.json()["code"] == "extension_not_found"


def test_submissions_v1_bottle_moderation_flow() -> None:
    hdr = _bearer(app.state.config.api_token)
    with TestClient(app) as client:
        assert (
            client.post(
                "/api/v1/projects/app",
                headers=hdr,
                json={"type": "bottle", "title": "海边漂流瓶", "slug": "sea-bottle"},
            ).status_code
            == 201
        )

        thrown = client.post(
            "/api/projects/sea-bottle/bottle/throw",
            json={"message": "祝你今天开心顺利", "nickname": "远方旅人"},
            headers={"Origin": "http://testserver"},
        )
        assert thrown.status_code == 200
        assert thrown.json()["status"] == "pending"
        sub_id = thrown.json()["submission_id"]

        _, read_raw = _create_db_token("审核只读", ["read"], allowed_slugs=["sea-bottle"])
        _, mod_raw = _create_db_token("审核专员", ["read", "submissions:write"], allowed_slugs=["sea-bottle"])

        listed = client.get(
            "/api/v1/projects/sea-bottle/submissions?status=pending", headers=_bearer(read_raw)
        )
        assert listed.status_code == 200
        list_body = listed.json()
        assert list_body["ok"] is True
        assert list_body["counts"]["pending"] == 1
        assert list_body["counts"]["approved"] == 0
        assert list_body["submissions"][0]["id"] == sub_id

        forbidden_mod = client.post(
            f"/api/v1/projects/sea-bottle/submissions/{sub_id}/status",
            headers=_bearer(read_raw),
            json={"action": "approve"},
        )
        assert forbidden_mod.status_code == 403
        assert forbidden_mod.json()["code"] == "forbidden_scope"

        approved = client.post(
            f"/api/v1/projects/sea-bottle/submissions/{sub_id}/status",
            headers=_bearer(mod_raw),
            json={"action": "approve"},
        )
        assert approved.status_code == 200
        assert approved.json()["submission"]["status"] == "approved"
        assert approved.json()["counts"]["approved"] == 1

        bad_action = client.post(
            f"/api/v1/projects/sea-bottle/submissions/{sub_id}/status",
            headers=_bearer(mod_raw),
            json={"action": "archive"},
        )
        assert bad_action.status_code == 400
        assert bad_action.json()["code"] == "invalid_submission_action"

        deleted = client.post(
            f"/api/v1/projects/sea-bottle/submissions/{sub_id}/status",
            headers=_bearer(mod_raw),
            json={"action": "delete"},
        )
        assert deleted.status_code == 200
        assert deleted.json()["deleted"] is True
        assert deleted.json()["counts"]["total"] == 0

        missing = client.post(
            f"/api/v1/projects/sea-bottle/submissions/{sub_id}/status",
            headers=_bearer(mod_raw),
            json={"action": "approve"},
        )
        assert missing.status_code == 404
        assert missing.json()["code"] == "submission_not_found"


def test_v1_tokens_management_lifecycle_and_privilege_escalation_guard() -> None:
    admin_hdr = _bearer(app.state.config.api_token)
    future_iso = (datetime.now(UTC) + timedelta(days=14)).replace(microsecond=0).isoformat()
    past_iso = (datetime.now(UTC) - timedelta(minutes=5)).replace(microsecond=0).isoformat()

    with TestClient(app) as client:
        created = client.post(
            "/api/v1/tokens",
            headers=admin_hdr,
            json={
                "name": "自动化写作 Agent",
                "scopes": ["read", "posts:write"],
                "allowed_slugs": ["eng-blog"],
                "expires_at": future_iso,
            },
        )
        assert created.status_code == 201
        created_body = created.json()
        assert created_body["ok"] is True
        meta = created_body["token"]
        plaintext = created_body["plaintext"]
        assert plaintext.startswith(tokens.TOKEN_PREFIX)
        assert "token_hash" not in meta
        assert meta["name"] == "自动化写作 Agent"
        assert meta["scopes"] == ["read", "posts:write"]
        assert meta["allowed_slugs"] == ["eng-blog"]

        listed = client.get("/api/v1/tokens", headers=admin_hdr)
        assert listed.status_code == 200
        assert plaintext not in listed.text
        assert "token_hash" not in listed.text
        assert tokens.hash_token(plaintext) not in listed.text
        assert [t["id"] for t in listed.json()["tokens"]] == [meta["id"]]
        assert set(listed.json()["valid_scopes"]) == set(tokens.VALID_SCOPES)

        who_new = client.get("/api/v1/whoami", headers=_bearer(plaintext))
        assert who_new.status_code == 200
        assert who_new.json()["principal"]["token_id"] == meta["id"]

        low_list = client.get("/api/v1/tokens", headers=_bearer(plaintext))
        assert low_list.status_code == 403
        assert low_list.json()["code"] == "forbidden_scope"

        _, scoped_admin_raw = _create_db_token(
            "受限空间管理员",
            ["admin"],
            allowed_slugs=["space-a"],
        )
        esc_create = client.post(
            "/api/v1/tokens",
            headers=_bearer(scoped_admin_raw),
            json={"name": "提权尝试", "scopes": ["admin"]},
        )
        assert esc_create.status_code == 403
        assert esc_create.json()["code"] == "forbidden_project"
        assert client.get("/api/v1/tokens", headers=_bearer(scoped_admin_raw)).status_code == 403
        assert (
            client.delete(f"/api/v1/tokens/{meta['id']}", headers=_bearer(scoped_admin_raw)).status_code
            == 403
        )

        for bad_payload in (
            {"name": "", "scopes": ["read"]},
            {"name": "坏权限", "scopes": ["nonexistent"]},
            {"name": "已过期", "scopes": ["read"], "expires_at": past_iso},
        ):
            bad_res = client.post("/api/v1/tokens", headers=admin_hdr, json=bad_payload)
            assert bad_res.status_code == 422
            assert bad_res.json()["code"] == "invalid_token"

        revoked = client.delete(f"/api/v1/tokens/{meta['id']}", headers=admin_hdr)
        assert revoked.status_code == 200
        assert revoked.json() == {"ok": True, "revoked": True, "id": meta["id"]}

        revoked_again = client.delete(f"/api/v1/tokens/{meta['id']}", headers=admin_hdr)
        assert revoked_again.status_code == 404
        assert revoked_again.json()["code"] == "token_not_found"

        after_revoke = client.get("/api/v1/whoami", headers=_bearer(plaintext))
        assert after_revoke.status_code == 401
