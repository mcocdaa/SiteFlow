import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from app import store
from app.config import Config
from app.main import app
from tests.test_flow import auth_headers, login, make_zip, upload


def create_app(client: TestClient, csrf: str, app_type: str, title: str, parent_id: int | None = None):
    payload: dict = {"type": app_type, "title": title}
    if parent_id is not None:
        payload["parent_id"] = parent_id
    return client.post("/api/admin/projects/app", json=payload, headers=auth_headers(csrf))


def test_space_with_children() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        space = create_app(client, csrf, "space", "我的空间")
        assert space.status_code == 200, space.text
        space_id = space.json()["project"]["id"]
        assert space.json()["project"]["type"] == "space"

        child = upload(client, csrf, "子作品.html", b"<h1>child</h1>")
        assert child.status_code == 200
        assert child.json()["project"]["parent_id"] is None

        moved_child = client.post(
            "/api/admin/projects/upload",
            files={"file": ("空间子作品.html", b"<h1>in space</h1>", "text/html")},
            data={"parent_id": str(space_id)},
            headers=auth_headers(csrf),
        )
        assert moved_child.status_code == 200, moved_child.text
        child_slug = moved_child.json()["project"]["slug"]
        assert moved_child.json()["project"]["parent_id"] == space_id

        root = client.get("/")
        assert "空间子作品" not in root.text
        assert "我的空间" in root.text

        page = client.get("/projects/我的空间".replace("我的空间", space.json()["project"]["slug"]) + "/")
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

        too_deep = create_app(client, csrf, "space", "太深", parent_id=third.json()["project"]["id"])
        assert too_deep.status_code == 400

        resume = create_app(client, csrf, "resume", "我的简历", parent_id=root_space["id"])
        assert resume.status_code == 200
        resume_id = resume.json()["project"]["id"]

        under_resume = create_app(client, csrf, "space", "简历下", parent_id=resume_id)
        assert under_resume.status_code == 400

        html = upload(client, csrf, "普通作品.html", b"<h1>x</h1>")
        under_item = create_app(client, csrf, "space", "作品下", parent_id=html.json()["project"]["id"])
        assert under_item.status_code == 400


def test_resume_render_and_escaping() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        created = create_app(client, csrf, "resume", "张三的简历")
        project = created.json()["project"]
        content = {
            "basics": {
                "name": "<script>alert(1)</script>",
                "label": "工程师",
                "summary": "第一行\n第二行",
                "location": {"city": "深圳", "region": "", "countryCode": "CN"},
                "profiles": [{"network": "GitHub", "username": "x", "url": "https://github.com/x"}],
            },
            "work": [{"name": "某公司", "position": "后端", "startDate": "2022-07", "endDate": "至今", "highlights": ["要点一"]}],
            "skills": [{"name": "Python", "keywords": ["FastAPI"]}],
        }
        import json

        patched = client.patch(
            f"/api/admin/projects/{project['id']}",
            json={"content": json.dumps(content, ensure_ascii=False)},
            headers=auth_headers(csrf),
        )
        assert patched.status_code == 200, patched.text

        page = client.get(f"/projects/{project['slug']}/")
        assert page.status_code == 200
        assert "<script>alert(1)</script>" not in page.text
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page.text
        assert "后端" in page.text and "FastAPI" in page.text


def test_content_only_for_plugins() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        space = create_app(client, csrf, "space", "空间").json()["project"]
        response = client.patch(
            f"/api/admin/projects/{space['id']}",
            json={"content": "{}"},
            headers=auth_headers(csrf),
        )
        assert response.status_code == 400


def test_site_app_upload() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        archive = make_zip({"site/index.html": b"<h1>site app</h1>"})
        response = client.post(
            "/api/admin/projects/upload",
            files={"file": ("站点.zip", archive, "application/zip")},
            data={"as_app": "true"},
            headers=auth_headers(csrf),
        )
        assert response.status_code == 200, response.text
        project = response.json()["project"]
        assert project["type"] == "site"
        assert project["entry"] == "site/index.html"
        page = client.get(f"/projects/{project['slug']}/", follow_redirects=False)
        assert page.status_code == 302
        view = client.get(f"/projects/{project['slug']}/site/index.html")
        assert view.status_code == 200
        assert view.headers["content-security-policy"].startswith("sandbox ")


def test_cascade_delete_and_visibility_inheritance() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        space = create_app(client, csrf, "space", "待删空间").json()["project"]
        child = client.post(
            "/api/admin/projects/upload",
            files={"file": ("空间内.html", b"<h1>hidden child</h1>", "text/html")},
            data={"parent_id": str(space["id"])},
            headers=auth_headers(csrf),
        ).json()["project"]

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
        first = client.post(
            "/api/admin/projects/upload",
            files={"file": ("一.html", b"<h1>1</h1>", "text/html")},
            data={"parent_id": str(space["id"])},
            headers=auth_headers(csrf),
        ).json()["project"]
        second = client.post(
            "/api/admin/projects/upload",
            files={"file": ("二.html", b"<h1>2</h1>", "text/html")},
            data={"parent_id": str(space["id"])},
            headers=auth_headers(csrf),
        ).json()["project"]

        moved = client.post(
            f"/api/admin/projects/{first['id']}/move",
            json={"direction": "up"},
            headers=auth_headers(csrf),
        )
        assert moved.status_code == 200 and moved.json()["ok"] is True

        db = store.init(app.state.config)()
        space_children = [row.slug for row in store.all_projects(db, space["id"])]
        assert space_children == [first["slug"], second["slug"]]
        root_projects = [row.slug for row in store.all_projects(db)]
        assert root_projects == [space["slug"]]


def test_old_database_migration() -> None:
    import tempfile

    data = Path(tempfile.mkdtemp(prefix="siteflow-migrate-"))
    database = data / "siteflow.db"
    conn = sqlite3.connect(database)
    conn.execute(
        "CREATE TABLE projects (id INTEGER PRIMARY KEY, slug VARCHAR(100) UNIQUE, type VARCHAR(10), "
        "title VARCHAR(200), description TEXT, url TEXT, entry TEXT, cover VARCHAR(100), "
        "pinned BOOLEAN, visible BOOLEAN, sort_order INTEGER, created_at VARCHAR, updated_at VARCHAR)"
    )
    conn.execute(
        "INSERT INTO projects (slug, type, title, description, url, entry, cover, pinned, visible, sort_order, created_at, updated_at) "
        "VALUES ('old-one', 'html', '旧作品', '', '', 'index.html', '', 0, 1, 0, '2026-01-01', '2026-01-01')"
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


def test_admin_app_pages_render() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        space = create_app(client, csrf, "space", "页面空间").json()["project"]
        child = client.post(
            "/api/admin/projects/upload",
            files={"file": ("页面子项.html", b"<h1>c</h1>", "text/html")},
            data={"parent_id": str(space["id"])},
            headers=auth_headers(csrf),
        ).json()["project"]
        resume = create_app(client, csrf, "resume", "页面简历").json()["project"]
        resume["id"]

        root = client.get("/admin")
        assert "新建应用" in root.text
        assert "上传静态站点应用" in root.text

        space_page = client.get(f"/admin/projects/{space['id']}")
        assert space_page.status_code == 200
        assert "新建子应用" in space_page.text
        assert "页面子项" in space_page.text
        assert f'data-parent-id="{space["id"]}"' in space_page.text

        resume_page = client.get(f"/admin/projects/{resume['id']}")
        assert resume_page.status_code == 200
        assert 'id="resume-data"' in resume_page.text
        assert 'id="f-name"' in resume_page.text
        assert 'data-section="work"' in resume_page.text
        assert child["slug"] not in resume_page.text
