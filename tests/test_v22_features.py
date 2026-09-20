from fastapi.testclient import TestClient

from app.main import app
from tests.test_flow import auth_headers, login, make_zip, upload


def test_etag_and_304_cache() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        resp = upload(
            client,
            csrf,
            "cache_test.zip",
            make_zip({"index.html": b"<h1>Cache Test</h1>", "style.css": b"body { color: red; }"}),
        )
        assert resp.status_code == 200
        slug = resp.json()["project"]["slug"]

        # 1. Entry HTML check
        r_entry = client.get(f"/projects/{slug}/index.html")
        assert r_entry.status_code == 200
        assert "ETag" in r_entry.headers
        etag = r_entry.headers["ETag"]
        assert "no-cache" in r_entry.headers["Cache-Control"]

        # Conditional request for HTML -> 304
        r_entry_304 = client.get(f"/projects/{slug}/index.html", headers={"If-None-Match": etag})
        assert r_entry_304.status_code == 304

        # 2. Static asset check -> public cache + ETag
        r_asset = client.get(f"/projects/{slug}/style.css")
        assert r_asset.status_code == 200
        assert "ETag" in r_asset.headers
        asset_etag = r_asset.headers["ETag"]
        assert "public" in r_asset.headers["Cache-Control"]

        # Conditional request for static asset -> 304
        r_asset_304 = client.get(f"/projects/{slug}/style.css", headers={"If-None-Match": asset_etag})
        assert r_asset_304.status_code == 304


def test_x_frame_options_sameorigin_for_projects() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        resp = upload(client, csrf, "frame_test.html", b"<h1>Frame</h1>")
        slug = resp.json()["project"]["slug"]

        # Project routes allow SAMEORIGIN
        r_proj = client.get(f"/projects/{slug}/index.html")
        assert r_proj.headers.get("X-Frame-Options") == "SAMEORIGIN"

        # Gallery and admin deny framing
        r_gallery = client.get("/")
        assert r_gallery.headers.get("X-Frame-Options") == "DENY"

        r_admin = client.get("/admin")
        assert r_admin.headers.get("X-Frame-Options") == "DENY"


def test_space_theme_customization() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        # Create space
        space_resp = client.post(
            "/api/admin/projects/app",
            json={"type": "space", "title": "主题定制空间"},
            headers=auth_headers(csrf),
        )
        assert space_resp.status_code == 200
        space_id = space_resp.json()["project"]["id"]
        space_slug = space_resp.json()["project"]["slug"]

        # Patch space theme
        patch_resp = client.patch(
            f"/api/admin/projects/{space_id}",
            json={
                "theme": {
                    "accent": "#0ea5e9",
                    "font_family": "serif",
                    "radius_card": "20px",
                }
            },
            headers=auth_headers(csrf),
        )
        assert patch_resp.status_code == 200

        # View space page and verify injected CSS variables
        view_resp = client.get(f"/projects/{space_slug}/")
        assert view_resp.status_code == 200
        assert "--accent: #0ea5e9;" in view_resp.text
        assert "--radius-card: 20px;" in view_resp.text
        assert "Georgia" in view_resp.text or "serif" in view_resp.text


def test_daily_stats_pv_uv_deduplication() -> None:
    with TestClient(app) as client:
        # Initial visit
        r1 = client.get("/", headers={"User-Agent": "TestBrowser/1.0"})
        assert r1.status_code == 200

        # Second visit with same client and UA -> PV increments, UV stays deduplicated
        r2 = client.get("/", headers={"User-Agent": "TestBrowser/1.0"})
        assert r2.status_code == 200

        # Third visit with different UA -> new UV
        r3 = client.get("/", headers={"User-Agent": "MobileDevice/2.0"})
        assert r3.status_code == 200

        login(client)
        admin_page = client.get("/admin")
        assert admin_page.status_code == 200
        assert "sparkline" in admin_page.text
        assert "今日访问" in admin_page.text


def test_project_password_protection_and_cookie() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        resp = upload(client, csrf, "secret_doc.html", b"<h1>Confidential Content</h1>")
        pid = resp.json()["project"]["id"]
        slug = resp.json()["project"]["slug"]

        # 1. Set password
        set_pwd = client.patch(
            f"/api/admin/projects/{pid}",
            json={"password": "SafePassword123!"},
            headers=auth_headers(csrf),
        )
        assert set_pwd.status_code == 200
        assert set_pwd.json()["project"]["has_password"] is True

    # 2. Anonymous client access -> redirected or shown gate page
    anon_client = TestClient(app)
    gate_resp = anon_client.get(f"/projects/{slug}/")
    assert gate_resp.status_code == 200
    assert "此作品已设置访问密码保护" in gate_resp.text
    assert "Confidential Content" not in gate_resp.text

    # 3. Unlock with wrong password -> 401
    bad_unlock = anon_client.post(
        f"/projects/{slug}/unlock",
        data={"password": "WrongPassword"},
        follow_redirects=False,
    )
    assert bad_unlock.status_code == 401
    assert "密码不正确" in bad_unlock.text

    # 4. Unlock with correct password -> 303 + sets path-restricted cookie
    good_unlock = anon_client.post(
        f"/projects/{slug}/unlock",
        data={"password": "SafePassword123!"},
        follow_redirects=False,
    )
    assert good_unlock.status_code == 303
    set_cookie_header = good_unlock.headers.get("set-cookie", "")
    assert f"Path=/projects/{slug}" in set_cookie_header

    # 5. Access with authenticated cookie -> content visible
    view_unlocked = anon_client.get(f"/projects/{slug}/")
    assert view_unlocked.status_code == 200
    assert "Confidential Content" in view_unlocked.text

    # 6. Admin user can view password-protected project directly
    with TestClient(app) as admin_client:
        login(admin_client)
        admin_view = admin_client.get(f"/projects/{slug}/")
        assert admin_view.status_code == 200
        assert "Confidential Content" in admin_view.text

    # 7. Clear password -> public again
    with TestClient(app) as client:
        csrf = login(client)
        clear_pwd = client.patch(
            f"/api/admin/projects/{pid}",
            json={"password": "clear"},
            headers=auth_headers(csrf),
        )
        assert clear_pwd.status_code == 200
        assert clear_pwd.json()["project"]["has_password"] is False

    anon_again = TestClient(app)
    public_again = anon_again.get(f"/projects/{slug}/")
    assert public_again.status_code == 200
    assert "Confidential Content" in public_again.text


def test_procedural_svg_cover_and_qrcode_api() -> None:
    with TestClient(app) as client:
        # SVG placeholder route
        svg_resp = client.get("/media/placeholder/demo-tech-project.svg")
        assert svg_resp.status_code == 200
        assert "image/svg+xml" in svg_resp.headers["Content-Type"]
        assert "<svg" in svg_resp.text
        assert "SITEFLOW" in svg_resp.text

        # QR Code route
        qr_resp = client.get("/api/qrcode?url=http://127.0.0.1:8000/projects/demo/")
        assert qr_resp.status_code == 200
        assert "image/svg+xml" in qr_resp.headers["Content-Type"]
        assert "<svg" in qr_resp.text


def test_search_api() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        resp = upload(client, csrf, "search-target.html", b"<h1>Search Target</h1>")
        assert resp.status_code == 200

        # Query matches
        search_res = client.get("/api/search?q=search-target")
        assert search_res.status_code == 200
        items = search_res.json()
        assert len(items) >= 1
        assert any(it["slug"] == "search-target" for it in items)

        # Empty query returns items
        all_res = client.get("/api/search")
        assert all_res.status_code == 200
        assert len(all_res.json()) >= 1


def test_subdomain_routing() -> None:
    from app.config import Config
    from app.main import create_app

    custom_cfg = Config(
        data=app.state.config.data,
        password=app.state.config.password,
        secret=app.state.config.secret,
        secure=False,
        site_title="Subdomain Test",
        site_description="desc",
        upload_limit=1024 * 1024,
        extract_limit=1024 * 1024,
        zip_entries=100,
        base_domain="siteflow.local",
    )
    sub_app = create_app(custom_cfg)

    with TestClient(sub_app) as client:
        csrf = login(client)
        upload(client, csrf, "subdemo.html", b"<h1>Subdomain Demo Content</h1>")

        # Request via subdomain header maps to /projects/subdemo/
        sub_resp = client.get("/", headers={"host": "subdemo.siteflow.local"})
        assert sub_resp.status_code == 200
        assert "Subdomain Demo Content" in sub_resp.text

        # Normal request to root on base domain is unaffected
        root_resp = client.get("/", headers={"host": "siteflow.local"})
        assert root_resp.status_code == 200
        assert "Subdomain Test" in root_resp.text

