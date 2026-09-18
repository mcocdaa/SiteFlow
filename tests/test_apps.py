import re
import sqlite3
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from app import store
from app.config import Config
from app.main import app
from tests.test_flow import ORIGIN, auth_headers, login, upload


def create_app(client: TestClient, csrf: str, app_type: str, title: str, parent_id: int | None = None):
    payload: dict = {"type": app_type, "title": title}
    if parent_id is not None:
        payload["parent_id"] = parent_id
    return client.post("/api/admin/projects/app", json=payload, headers=auth_headers(csrf))


def upload_to(client: TestClient, csrf: str, filename: str, content: bytes, parent_id: int):
    return client.post(
        "/api/admin/projects/upload",
        files={"file": (filename, content, "text/html")},
        data={"parent_id": str(parent_id)},
        headers=auth_headers(csrf),
    )


def test_space_with_children() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        space = create_app(client, csrf, "space", "我的空间")
        assert space.status_code == 200, space.text
        space_id = space.json()["project"]["id"]
        assert space.json()["project"]["type"] == "space"

        child = upload_to(client, csrf, "空间子作品.html", b"<h1>in space</h1>", space_id)
        assert child.status_code == 200, child.text
        child_slug = child.json()["project"]["slug"]
        assert child.json()["project"]["parent_id"] == space_id

        root = client.get("/")
        assert "空间子作品" not in root.text
        assert "我的空间" in root.text
        assert 'target="_blank"' not in root.text

        page = client.get(f"/projects/{space.json()['project']['slug']}/")
        assert page.status_code == 200
        assert "空间子作品" in page.text
        assert client.get(f"/projects/{child_slug}/", follow_redirects=False).status_code == 302
        assert client.get(f"/projects/{child_slug}/index.html").status_code == 200


def test_depth_and_leaf_rules() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        root_space = create_app(client, csrf, "space", "根空间").json()["project"]
        sub_space = create_app(client, csrf, "space", "子空间", parent_id=root_space["id"])
        assert sub_space.status_code == 200
        sub_id = sub_space.json()["project"]["id"]

        third = create_app(client, csrf, "space", "第三层", parent_id=sub_id)
        assert third.status_code == 200
        third_id = third.json()["project"]["id"]

        too_deep = create_app(client, csrf, "space", "太深", parent_id=third_id)
        assert too_deep.status_code == 400
        assert "深度" in too_deep.json()["error"]

        html = upload(client, csrf, "普通作品.html", b"<h1>x</h1>").json()["project"]
        under_item = create_app(client, csrf, "space", "作品下", parent_id=html["id"])
        assert under_item.status_code == 400


def test_unknown_app_type_rejected() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        response = create_app(client, csrf, "podcast", "未注册类型")
    assert response.status_code == 400
    assert "不支持" in response.json()["error"]


def test_content_edit_requires_plugin() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        space = create_app(client, csrf, "space", "空间").json()["project"]
        response = client.patch(
            f"/api/admin/projects/{space['id']}",
            json={"content": "{}"},
            headers=auth_headers(csrf),
        )
    assert response.status_code == 400


def test_cascade_delete_and_visibility_inheritance() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        space = create_app(client, csrf, "space", "待删空间").json()["project"]
        child = upload_to(client, csrf, "空间内.html", b"<h1>child</h1>", space["id"]).json()["project"]

        hidden = client.patch(
            f"/api/admin/projects/{space['id']}",
            json={"visible": False},
            headers=auth_headers(csrf),
        )
        assert hidden.status_code == 200
        assert client.get(f"/projects/{space['slug']}/").status_code == 404
        assert client.get(f"/projects/{child['slug']}/").status_code == 404
        assert "待删空间" not in client.get("/").text

        deleted = client.delete(f"/api/admin/projects/{space['id']}", headers=auth_headers(csrf))
        assert deleted.status_code == 200
        db = store.init(app.state.config)()
        assert store.by_id(db, space["id"]) is None
        assert store.by_id(db, child["id"]) is None
        assert not (Path(app.state.config.data) / "projects" / child["slug"]).exists()


def test_scoped_move_does_not_affect_root() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        space = create_app(client, csrf, "space", "排序空间").json()["project"]
        first = upload_to(client, csrf, "一.html", b"<h1>1</h1>", space["id"]).json()["project"]
        second = upload_to(client, csrf, "二.html", b"<h1>2</h1>", space["id"]).json()["project"]

        moved = client.post(
            f"/api/admin/projects/{first['id']}/move",
            json={"direction": "up"},
            headers=auth_headers(csrf),
        )
        assert moved.status_code == 200 and moved.json()["ok"] is True

        db = store.init(app.state.config)()
        assert [row.slug for row in store.all_projects(db, space["id"])] == [first["slug"], second["slug"]]
        assert [row.slug for row in store.all_projects(db)] == [space["slug"]]


def test_admin_pages_use_registered_app_list() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        space = create_app(client, csrf, "space", "页面空间").json()["project"]
        child = upload_to(client, csrf, "页面子项.html", b"<h1>c</h1>", space["id"]).json()["project"]

        root = client.get("/admin")
        assert "新建空间" in root.text
        assert "新建简历" in root.text
        assert "新建博客" in root.text
        assert "上传静态站点" not in root.text
        assert 'id="app-type"' not in root.text

        space_page = client.get(f"/admin/projects/{space['id']}")
        assert space_page.status_code == 200
        assert "新建空间" in space_page.text
        assert "页面子项" in space_page.text
        assert f'data-parent-id="{space["id"]}"' in space_page.text
        assert child["slug"]  # used


def test_multiple_spaces_and_login_persists() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        first = create_app(client, csrf, "space", "子空间1").json()["project"]
        second = create_app(client, csrf, "space", "子空间2").json()["project"]
        assert first["slug"] != second["slug"]

        root = client.get("/")
        assert "子空间1" in root.text and "子空间2" in root.text

        again = client.get("/login", follow_redirects=False)
        assert again.status_code == 303
        assert again.headers["location"] == "/admin"
        assert client.get("/admin").status_code == 200


def test_old_database_migration() -> None:
    data = Path(tempfile.mkdtemp(prefix="siteflow-migrate-"))
    database = data / "siteflow.db"
    conn = sqlite3.connect(database)
    conn.execute(
        "CREATE TABLE projects (id INTEGER PRIMARY KEY, slug VARCHAR(100) UNIQUE, type VARCHAR(10), "
        "title VARCHAR(200), description TEXT, url TEXT, entry TEXT, cover VARCHAR(100), "
        "pinned BOOLEAN, visible BOOLEAN, sort_order INTEGER, created_at VARCHAR, updated_at VARCHAR)"
    )
    conn.execute(
        "INSERT INTO projects (slug, type, title, description, url, entry, cover, pinned, visible, sort_order, "
        "created_at, updated_at) VALUES ('old-one', 'html', '旧作品', '', '', 'index.html', '', 0, 1, 0, "
        "'2026-01-01', '2026-01-01')"
    )
    conn.commit()
    conn.close()

    config = Config(
        data=data,
        password="x",
        secret="y",
        secure=False,
        site_title="t",
        site_description="d",
        upload_limit=1024,
        extract_limit=1024,
        zip_entries=10,
    )
    store._engine = None
    store._factory = None
    store._current = None
    store.init(config)
    db = store.session()
    project = store.by_slug(db, "old-one")
    assert project is not None
    assert project.parent_id is None
    assert project.content == "{}"


def test_space_is_registered_in_app_list() -> None:
    from app.plugins import registry

    types = [plugin.type for plugin in registry.all_apps()]
    assert types == ["space", "resume", "blog"]
    assert registry.get("space") is not None
    assert registry.get("resume") is not None
    assert registry.get("podcast") is None


def test_login_roundtrip_for_app_management() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        space = create_app(client, csrf, "space", "回跳空间").json()["project"]
        path = f"/admin/projects/{space['id']}"
        client.cookies.clear()

        anonymous = client.get(path, follow_redirects=False)
        assert anonymous.status_code == 303
        assert anonymous.headers["location"] == f"/login?next={path}"

        page = client.get(anonymous.headers["location"])
        token = re.search(r'name="csrf" value="(.+?)"', page.text)
        assert token is not None
        response = client.post(
            "/login",
            data={"password": app.state.config.password, "csrf": token.group(1), "next": path},
            headers=ORIGIN,
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == path
        assert client.get(path).status_code == 200


def test_login_next_rejects_external_targets() -> None:
    with TestClient(app) as client:
        page = client.get("/login")
        token = re.search(r'name="csrf" value="(.+?)"', page.text)
        assert token is not None
        response = client.post(
            "/login",
            data={"password": app.state.config.password, "csrf": token.group(1), "next": "//evil.example"},
            headers=ORIGIN,
            follow_redirects=False,
        )
    assert response.status_code == 303
    assert response.headers["location"] == "/admin"


def test_resume_plugin_render_and_escape() -> None:
    import json

    from tests.test_flow import auth_headers

    with TestClient(app) as client:
        csrf = login(client)
        resume = create_app(client, csrf, "resume", "张三的简历").json()["project"]
        content = {
            "basics": {
                "name": "<script>alert(1)</script>",
                "label": "工程师",
                "summary": "第一行\n第二行",
                "location": {"city": "深圳", "region": "", "countryCode": "CN"},
                "profiles": [{"network": "GitHub", "username": "x", "url": "https://github.com/x"}],
            },
            "work": [
                {
                    "name": "某公司",
                    "position": "后端",
                    "startDate": "2022-07",
                    "endDate": "至今",
                    "highlights": ["要点一"],
                }
            ],
            "skills": [{"name": "Python", "keywords": ["FastAPI"]}],
        }
        patched = client.patch(
            f"/api/admin/projects/{resume['id']}",
            json={"content": json.dumps(content, ensure_ascii=False)},
            headers=auth_headers(csrf),
        )
        assert patched.status_code == 200

        page = client.get(f"/projects/{resume['slug']}/")
        assert page.status_code == 200
        assert "<script>alert(1)</script>" not in page.text
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page.text
        assert "后端" in page.text and "FastAPI" in page.text

        admin_page = client.get(f"/admin/projects/{resume['id']}")
        assert admin_page.status_code == 200
        assert 'id="plugin-data"' in admin_page.text
        assert 'id="f-name"' in admin_page.text
        assert 'data-section="work"' in admin_page.text
        assert "保存并查看" in admin_page.text


def test_blog_plugin_index_detail_and_markdown_safety() -> None:
    import json

    from tests.test_flow import auth_headers

    with TestClient(app) as client:
        csrf = login(client)
        blog = create_app(client, csrf, "blog", "我的博客").json()["project"]
        content = {
            "title": "我的博客",
            "description": "记录",
            "posts": [
                {
                    "slug": "hello",
                    "title": "第一篇",
                    "date": "2026-09-01",
                    "tags": ["生活"],
                    "summary": "摘要一",
                    "body": "**粗体**\n\n<script>alert(1)</script>\n\n[坏链接](javascript:alert(1))",
                },
                {"slug": "second", "title": "第二篇", "date": "2026-09-18", "body": "正文二"},
            ],
        }
        patched = client.patch(
            f"/api/admin/projects/{blog['id']}",
            json={"content": json.dumps(content, ensure_ascii=False)},
            headers=auth_headers(csrf),
        )
        assert patched.status_code == 200

        index = client.get(f"/projects/{blog['slug']}/")
        assert index.status_code == 200
        assert "第一篇" in index.text and "第二篇" in index.text
        assert index.text.index("第二篇") < index.text.index("第一篇")

        detail = client.get(f"/projects/{blog['slug']}/posts/hello")
        assert detail.status_code == 200
        assert "文章列表" in detail.text
        assert "上一篇" in detail.text and "第二篇" in detail.text
        assert "<strong>粗体</strong>" in detail.text
        assert "<script>alert(1)</script>" not in detail.text
        assert "&lt;script&gt;" in detail.text
        assert 'href="javascript:' not in detail.text

        missing = client.get(f"/projects/{blog['slug']}/posts/nope")
        assert missing.status_code == 404
        assert client.get(f"/projects/{blog['slug']}/posts/").status_code == 404

        admin_page = client.get(f"/admin/projects/{blog['id']}")
        assert admin_page.status_code == 200
        assert 'id="plugin-data"' in admin_page.text
        assert "添加文章" in admin_page.text
        assert "保存并查看" in admin_page.text
        assert 'data-preview-url="/projects/' in admin_page.text
        assert 'id="post-count"' in admin_page.text


def test_plugin_pages_show_admin_entry() -> None:
    import json

    from tests.test_flow import auth_headers

    with TestClient(app) as client:
        csrf = login(client)
        resume = create_app(client, csrf, "resume", "入口简历").json()["project"]
        blog = create_app(client, csrf, "blog", "入口博客").json()["project"]
        client.patch(
            f"/api/admin/projects/{blog['id']}",
            json={"content": json.dumps({"posts": [{"slug": "p1", "title": "文一", "body": "x"}]})},
            headers=auth_headers(csrf),
        )

        resume_page = client.get(f"/projects/{resume['slug']}/")
        assert f'href="/admin/projects/{resume["id"]}"' in resume_page.text

        blog_page = client.get(f"/projects/{blog['slug']}/")
        assert f'href="/admin/projects/{blog["id"]}"' in blog_page.text

        post_page = client.get(f"/projects/{blog['slug']}/posts/p1")
        assert f'href="/admin/projects/{blog["id"]}"' in post_page.text
