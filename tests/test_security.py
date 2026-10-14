import io
import re
import zipfile

from fastapi.testclient import TestClient

from app.main import app
from app.og import parse_og
from tests.test_flow import ORIGIN, login, make_zip, upload


def test_symlink_zip_rejected() -> None:
    info = zipfile.ZipInfo("link")
    info.external_attr = 0o120777 << 16
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("index.html", b"ok")
        archive.writestr(info, "target")
    with TestClient(app) as client:
        csrf = login(client)
        response = upload(client, csrf, "symlink.zip", buffer.getvalue())
    assert response.status_code == 422


def test_extract_size_limit(monkeypatch) -> None:
    with TestClient(app) as client:
        monkeypatch.setattr(app.state.config, "extract_limit", 1024)
        csrf = login(client)
        response = upload(client, csrf, "bomb.zip", make_zip({"index.html": b"x" * 5000}))
    assert response.status_code == 422


def test_zipbomb_expansion_ratio_rejected() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("index.html", b"0" * (2 * 1024 * 1024))
    with TestClient(app) as client:
        csrf = login(client)
        response = upload(client, csrf, "ratio_bomb.zip", buffer.getvalue())
    assert response.status_code == 422
    assert "疑似解压炸弹" in response.text


def test_zip_gbk_filename_supported() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("index.html", b"<h1>GBK Test</h1>")
        # Simulate Windows GBK zip file: flag_bits & 0x800 == 0
        gbk_bytes = "说明文档.txt".encode("gbk")
        cp437_str = gbk_bytes.decode("cp437")
        info = zipfile.ZipInfo(cp437_str)
        info.flag_bits = 0
        archive.writestr(info, b"Windows Chinese Filename Content")
    with TestClient(app) as client:
        csrf = login(client)
        response = upload(client, csrf, "gbk_test.zip", buffer.getvalue())
    assert response.status_code == 200
    slug = response.json()["project"]["slug"]
    with TestClient(app) as client:
        file_resp = client.get(f"/projects/{slug}/说明文档.txt")
        assert file_resp.status_code == 200
        assert b"Windows Chinese Filename Content" in file_resp.content


def test_zip_inode_limit_rejected(monkeypatch) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("index.html", b"<h1>Test</h1>")
        for i in range(15):
            archive.writestr(f"dir_{i}/file_{i}.txt", b"ok")
    with TestClient(app) as client:
        monkeypatch.setattr(app.state.config, "zip_entries", 10)
        csrf = login(client)
        response = upload(client, csrf, "too_many_inodes.zip", buffer.getvalue())
    assert response.status_code == 422
    assert "超出限制" in response.text or "Inode" in response.text


def test_parse_og_metadata() -> None:
    html = (
        b"<html><head><title>Fallback</title>"
        b'<meta property="og:title" content="OG Title">'
        b'<meta property="og:description" content="OG Desc">'
        b'<meta property="og:image" content="https://example.com/i.png">'
        b"</head></html>"
    )
    og = parse_og(html, "https://example.com")
    assert og is not None
    assert og.title == "OG Title"
    assert og.description == "OG Desc"
    assert og.image_url == "https://example.com/i.png"

    plain = parse_og(b"<title>Only</title>", "https://example.com")
    assert plain is not None
    assert plain.title == "Only"


def test_login_rate_limit() -> None:
    with TestClient(app) as client:
        for _ in range(5):
            page = client.get("/login")
            token = re.search(r'name="csrf" value="([^"]+)"', page.text)
            assert token is not None
            client.post(
                "/login",
                data={"password": "wrong", "csrf": token.group(1)},
                headers=ORIGIN,
            )
        page = client.get("/login")
        token = re.search(r'name="csrf" value="([^"]+)"', page.text)
        assert token is not None
        response = client.post(
            "/login",
            data={"password": "test-password", "csrf": token.group(1)},
            headers=ORIGIN,
        )
    assert response.status_code == 429


def test_password_change_invalidates_session(monkeypatch) -> None:
    with TestClient(app) as client:
        login(client)
        assert client.get("/admin", follow_redirects=False).status_code == 200

        monkeypatch.setattr(app.state.config, "password", "rotated-pass")
        assert client.get("/admin", follow_redirects=False).status_code == 303

        page = client.get("/login")
        token = re.search(r'name="csrf" value="([^"]+)"', page.text)
        assert token is not None
        response = client.post(
            "/login",
            data={"password": "rotated-pass", "csrf": token.group(1)},
            headers=ORIGIN,
            follow_redirects=False,
        )
    assert response.status_code == 303


def test_link_requires_http_url() -> None:
    from tests.test_flow import auth_headers

    with TestClient(app) as client:
        csrf = login(client)
        empty = client.post(
            "/api/admin/projects/link",
            json={"url": ""},
            headers=auth_headers(csrf),
        )
    assert empty.status_code == 400


def test_move_boundary_reports_not_moved() -> None:
    from tests.test_flow import auth_headers

    with TestClient(app) as client:
        csrf = login(client)
        html = upload(client, csrf, "唯一条目.html", b"<h1>one</h1>")
        pid = html.json()["project"]["id"]
        response = client.post(
            f"/api/admin/projects/{pid}/move",
            json={"direction": "up"},
            headers=auth_headers(csrf),
        )
    assert response.status_code == 200
    assert response.json()["ok"] is False


def test_fetch_image_blocks_private_and_non_http() -> None:
    from app.og import fetch_image

    assert fetch_image("http://127.0.0.1:9/cover.png") is None
    assert fetch_image("http://169.254.169.254/latest/meta-data") is None
    assert fetch_image("file:///etc/passwd") is None


def test_svg_placeholder_escapes_xss_and_validates_slug() -> None:
    from app.svg_cover import generate_svg_cover
    from tests.test_flow import auth_headers

    raw_svg = generate_svg_cover(
        'bad"><script>alert(1)</script>',
        "<script>alert(1)</script>",
        "<img src=x onerror=alert(1)>",
    )
    assert "<script>" not in raw_svg
    assert "<img" not in raw_svg
    assert "&lt;" in raw_svg
    assert 'id="glow-badscriptalert1script"' in raw_svg

    with TestClient(app) as client:
        csrf = login(client)
        resp = client.post(
            "/api/admin/projects/upload",
            files={"file": ("xss.html", b"<h1>ok</h1>", "text/html")},
            data={"title": "<script>alert(1)</script>"},
            headers=auth_headers(csrf),
        )
        assert resp.status_code == 200
        slug = resp.json()["project"]["slug"]

        svg_resp = client.get(f"/media/placeholder/{slug}.svg")
        assert svg_resp.status_code == 200
        assert (
            svg_resp.headers.get("Content-Security-Policy") == "default-src 'none'; style-src 'unsafe-inline'"
        )
        assert "<script>" not in svg_resp.text
        assert "&lt;</text>" in svg_resp.text

        invalid_resp = client.get('/media/placeholder/bad"slug.svg')
        assert invalid_resp.status_code == 404


def test_search_does_not_leak_hidden_projects_with_login_csrf_cookie() -> None:
    from tests.test_flow import auth_headers

    with TestClient(app) as admin_client:
        csrf = login(admin_client)
        pub = upload(admin_client, csrf, "public-item.html", b"<h1>Public</h1>").json()["project"]
        sec = upload(admin_client, csrf, "secret-hidden-item.html", b"<h1>Hidden</h1>").json()["project"]
        patch_resp = admin_client.patch(
            f"/api/admin/projects/{sec['id']}",
            json={"visible": False},
            headers=auth_headers(csrf),
        )
        assert patch_resp.status_code == 200

    with TestClient(app) as anon_client:
        # Visiting /login issues an unauthenticated session cookie {"admin": False}
        login_page = anon_client.get("/login")
        assert login_page.status_code == 200
        assert "siteflow_session" in anon_client.cookies

        search_resp = anon_client.get("/api/search")
        assert search_resp.status_code == 200
        slugs = [item["slug"] for item in search_resp.json()]
        assert pub["slug"] in slugs
        assert sec["slug"] not in slugs


def test_project_unlock_rate_limit() -> None:
    from tests.test_flow import auth_headers

    with TestClient(app) as admin_client:
        csrf = login(admin_client)
        proj = upload(admin_client, csrf, "locked-work.html", b"<h1>Locked</h1>").json()["project"]
        pid, slug = proj["id"], proj["slug"]
        res = admin_client.patch(
            f"/api/admin/projects/{pid}",
            json={"password": "CorrectHorseBatteryStaple"},
            headers=auth_headers(csrf),
        )
        assert res.status_code == 200

    with TestClient(app) as anon_client:
        for _ in range(5):
            attempt = anon_client.post(
                f"/projects/{slug}/unlock",
                data={"password": "wrong-password"},
                follow_redirects=False,
            )
            assert attempt.status_code == 401

        blocked = anon_client.post(
            f"/projects/{slug}/unlock",
            data={"password": "CorrectHorseBatteryStaple"},
            follow_redirects=False,
        )
        assert blocked.status_code == 429
        assert "尝试次数过多" in blocked.text


def test_space_not_sandboxed_and_static_cors_headers() -> None:
    from tests.test_flow import auth_headers

    with TestClient(app) as client:
        csrf = login(client)
        space = client.post(
            "/api/admin/projects/app",
            json={"type": "space", "title": "测试空间"},
            headers=auth_headers(csrf),
        ).json()["project"]
        pub_html = upload(client, csrf, "public-app.html", b"<h1>App</h1>").json()["project"]

        space_resp = client.get(f"/projects/{space['slug']}/")
        assert space_resp.status_code == 200
        assert "Content-Security-Policy" not in space_resp.headers

        static_resp = client.get(f"/projects/{pub_html['slug']}/index.html")
        assert static_resp.status_code == 200
        assert static_resp.headers.get("Content-Security-Policy", "").startswith("sandbox ")
        assert static_resp.headers.get("Access-Control-Allow-Origin") == "*"

    rel_og = parse_og(
        b'<html><head><meta property="og:title" content="T"><meta property="og:image" content="/img/cover.png"></head></html>',
        "https://example.com/posts/1",
    )
    assert rel_og is not None
    assert rel_og.image_url == "https://example.com/img/cover.png"
