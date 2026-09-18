import io
import re
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

ORIGIN = {"Origin": "http://testserver"}


def login(client: TestClient) -> str:
    page = client.get("/login")
    match = re.search(r'name="csrf" value="([^"]+)"', page.text)
    assert match is not None
    response = client.post(
        "/login",
        data={"password": app.state.config.password, "csrf": match.group(1)},
        headers=ORIGIN,
        follow_redirects=False,
    )
    assert response.status_code == 303
    admin = client.get("/admin")
    csrf = re.search(r'name="csrf" content="([^"]+)"', admin.text)
    assert csrf is not None
    return csrf.group(1)


def auth_headers(csrf: str) -> dict[str, str]:
    return {**ORIGIN, "X-CSRF-Token": csrf}


def make_zip(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def upload(client: TestClient, csrf: str, filename: str, content: bytes):
    return client.post(
        "/api/admin/projects/upload",
        files={"file": (filename, content)},
        headers=auth_headers(csrf),
    )


def make_png() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (32, 24), (10, 120, 200)).save(buffer, format="PNG")
    return buffer.getvalue()


def data_dir() -> Path:
    return Path(app.state.config.data)


def test_upload_html_and_view_with_sandbox() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        response = upload(client, csrf, "我的作品.html", b"<h1>Hello</h1>")
        assert response.status_code == 200, response.text
        project = response.json()["project"]
        assert project["type"] == "html"
        assert project["entry"] == "index.html"
        slug = project["slug"]

        gallery = client.get("/")
        assert "我的作品" in gallery.text

        root = client.get(f"/projects/{slug}", follow_redirects=False)
        assert root.status_code == 302
        assert root.headers["location"] == f"/projects/{slug}/index.html"

        page = client.get(f"/projects/{slug}/index.html")
        assert page.status_code == 200
        assert page.text == "<h1>Hello</h1>"
        assert page.headers["content-security-policy"].startswith("sandbox ")
        assert page.headers["x-content-type-options"] == "nosniff"


def test_upload_zip_with_wrapper_and_macosx() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        archive = make_zip(
            {
                "site/index.html": b"<link rel=stylesheet href=app.css><h1>Zip</h1>",
                "site/app.css": b"h1{color:red}",
                "__MACOSX/._site": b"junk",
            }
        )
        response = upload(client, csrf, "作品集.zip", archive)
        assert response.status_code == 200, response.text
        project = response.json()["project"]
        assert project["entry"] == "site/index.html"
        slug = project["slug"]

        page = client.get(f"/projects/{slug}/site/index.html")
        assert page.status_code == 200
        asset = client.get(f"/projects/{slug}/site/app.css")
        assert asset.status_code == 200
        assert asset.headers["content-type"].startswith("text/css")
        assert client.get(f"/projects/{slug}/__MACOSX/._site").status_code == 404


def test_zip_without_index_rejected_and_cleaned() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        response = upload(client, csrf, "无入口.zip", make_zip({"readme.txt": b"hi"}))
        assert response.status_code == 422
        projects = data_dir() / "projects"
        assert list(projects.iterdir()) == []


def test_zip_slip_rejected() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        archive = make_zip({"../evil.html": b"bad", "index.html": b"ok"})
        response = upload(client, csrf, "逃逸.zip", archive)
        assert response.status_code == 422
        assert not (data_dir() / "projects" / "evil.html").exists()
        assert not (data_dir() / "projects" / "projects" / "evil.html").exists()


def test_link_and_mutations() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        link = client.post(
            "/api/admin/projects/link",
            json={"url": "http://127.0.0.1:9/page", "title": "示例链接"},
            headers=auth_headers(csrf),
        )
        assert link.status_code == 200, link.text
        assert link.json()["project"]["type"] == "link"
        assert link.json()["project"]["url"] == "http://127.0.0.1:9/page"

        bad = client.post(
            "/api/admin/projects/link",
            json={"url": "javascript:alert(1)"},
            headers=auth_headers(csrf),
        )
        assert bad.status_code == 400

        html = upload(client, csrf, "待隐藏.html", b"<h1>Hidden</h1>")
        assert html.status_code == 200
        project = html.json()["project"]
        pid, slug = project["id"], project["slug"]

        pinned = client.patch(
            f"/api/admin/projects/{pid}", json={"pinned": True}, headers=auth_headers(csrf)
        )
        assert pinned.status_code == 200
        assert pinned.json()["project"]["pinned"] is True

        hidden = client.patch(
            f"/api/admin/projects/{pid}", json={"visible": False}, headers=auth_headers(csrf)
        )
        assert hidden.status_code == 200
        assert "待隐藏" not in client.get("/").text
        assert client.get(f"/projects/{slug}/index.html").status_code == 404

        moved = client.post(
            f"/api/admin/projects/{pid}/move", json={"direction": "up"}, headers=auth_headers(csrf)
        )
        assert moved.status_code == 200

        deleted = client.delete(f"/api/admin/projects/{pid}", headers=auth_headers(csrf))
        assert deleted.status_code == 200
        assert not (data_dir() / "projects" / slug).exists()


def test_cover_upload() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        html = upload(client, csrf, "封面测试.html", b"<h1>Cover</h1>")
        pid = html.json()["project"]["id"]

        response = client.post(
            f"/api/admin/projects/{pid}/cover",
            files={"file": ("cover.png", make_png(), "image/png")},
            headers=auth_headers(csrf),
        )
        assert response.status_code == 200, response.text
        cover = response.json()["project"]["cover"]
        assert cover.endswith(".webp")

        media = client.get(f"/media/covers/{cover}")
        assert media.status_code == 200
        assert media.headers["content-type"] == "image/webp"


def test_admin_requires_auth_and_csrf() -> None:
    with TestClient(app) as client:
        anonymous = client.get("/admin", follow_redirects=False)
        assert anonymous.status_code == 303
        assert anonymous.headers["location"] == "/login"

        no_session = client.post(
            "/api/admin/projects/link",
            json={"url": "https://example.com"},
            headers=ORIGIN,
        )
        assert no_session.status_code == 401

        login(client)
        no_csrf = client.post(
            "/api/admin/projects/link",
            json={"url": "https://example.com"},
            headers=ORIGIN,
        )
        assert no_csrf.status_code == 403


def test_traversal_blocked() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        upload(client, csrf, "穿越测试.html", b"<h1>T</h1>")
        secret = data_dir() / "siteflow.db"
        assert secret.exists()
        response = client.get("/projects/x/..%2f..%2fsiteflow.db")
        assert response.status_code == 404


def test_gallery_shows_admin_entry_and_guide() -> None:
    with TestClient(app) as client:
        anonymous = client.get("/")
        assert 'href="/login"' in anonymous.text
        assert "去管理台上传第一个作品" not in anonymous.text

        login(client)
        logged_in = client.get("/")
        assert "去管理台上传第一个作品" in logged_in.text


def test_admin_uses_svg_icons_not_text_glyphs() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        upload(client, csrf, "图标测试.html", b"<h1>Icon</h1>")
        admin = client.get("/admin")
    assert '<svg class="icon"' in admin.text
    assert "data-pinned=" in admin.text
    assert "data-visible=" in admin.text
    assert "↑" not in admin.text
    assert "↓" not in admin.text
    assert "★" not in admin.text


def test_admin_icon_buttons_have_tooltips() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        upload(client, csrf, "提示测试.html", b"<h1>Tip</h1>")
        admin = client.get("/admin")
    for tip in ("查看", "编辑", "置顶", "上移", "下移", "隐藏", "删除"):
        assert f'data-tip="{tip}"' in admin.text
