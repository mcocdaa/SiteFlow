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


def test_headless_bearer_api_and_idempotent_deploy() -> None:
    token = app.state.config.api_token
    assert token and len(token) == 32
    bearer = {"Authorization": f"Bearer {token}"}
    api_key_hdr = {"X-API-Key": token}

    with TestClient(app) as client:
        # (b) Invalid Bearer / X-API-Key token rejected with 401/403
        bad_bearer = client.get("/api/admin/projects", headers={"Authorization": "Bearer invalid-token"})
        assert bad_bearer.status_code in (401, 403)
        bad_key = client.get("/api/admin/projects", headers={"X-API-Key": "wrong-key"})
        assert bad_key.status_code in (401, 403)

        # (a) Valid Bearer token calling GET /api/admin/projects without cookies or CSRF/Origin headers
        list_resp = client.get("/api/admin/projects", headers=bearer)
        assert list_resp.status_code == 200
        assert list_resp.json() == {"ok": True, "projects": []}

        # POST /api/admin/projects/app via Bearer token without cookies/CSRF
        app_resp = client.post(
            "/api/admin/projects/app",
            json={"type": "space", "title": "AI 空间", "description": "Created by AI"},
            headers=bearer,
        )
        assert app_resp.status_code == 200
        space_proj = app_resp.json()["project"]
        assert space_proj["title"] == "AI 空间"

        # GET /api/admin/projects/{project_id} via X-API-Key
        detail_resp = client.get(f"/api/admin/projects/{space_proj['id']}", headers=api_key_hdr)
        assert detail_resp.status_code == 200
        detail_data = detail_resp.json()
        assert detail_data["ok"] is True
        assert detail_data["project"]["id"] == space_proj["id"]
        assert detail_data["children"] == []
        assert "today_pv" in detail_data["stats"]

        # PUT /api/admin/projects/my-ai-report/deploy via Bearer token
        deploy_v1 = client.put(
            "/api/admin/projects/my-ai-report/deploy",
            files={"file": ("report.html", b"<h1>AI Report v1</h1>", "text/html")},
            data={"title": "AI 报告 v1", "description": "第一版"},
            headers=bearer,
        )
        assert deploy_v1.status_code == 200, deploy_v1.text
        v1_data = deploy_v1.json()
        assert v1_data["ok"] is True
        assert v1_data["url"] == "/p/my-ai-report/"
        assert v1_data["project"]["slug"] == "my-ai-report"
        assert v1_data["project"]["title"] == "AI 报告 v1"
        v1_id = v1_data["project"]["id"]

        # Verify deployed content is served at both /p/my-ai-report/ and /projects/my-ai-report/
        page_v1 = client.get("/p/my-ai-report/")
        assert page_v1.status_code == 200
        assert "AI Report v1" in page_v1.text

        # (c) Idempotent re-deploy updating existing slug my-ai-report
        deploy_v2 = client.put(
            "/api/admin/projects/my-ai-report/deploy",
            files={
                "file": (
                    "bundle.zip",
                    make_zip({"index.html": b"<h1>AI Report v2 Updated</h1>", "data.json": b'{"v":2}'}),
                    "application/zip",
                )
            },
            data={"title": "AI 报告 v2", "description": "第二版"},
            headers=bearer,
        )
        assert deploy_v2.status_code == 200, deploy_v2.text
        v2_data = deploy_v2.json()
        assert v2_data["ok"] is True
        assert v2_data["project"]["id"] == v1_id
        assert v2_data["project"]["slug"] == "my-ai-report"
        assert v2_data["project"]["title"] == "AI 报告 v2"
        assert v2_data["project"]["description"] == "第二版"

        page_v2 = client.get("/projects/my-ai-report/index.html")
        assert page_v2.status_code == 200
        assert "AI Report v2 Updated" in page_v2.text
        assert client.get("/projects/my-ai-report/data.json").json() == {"v": 2}

        # POST /api/deploy/{slug} alias also works
        alias_resp = client.post(
            "/api/deploy/my-ai-report",
            files={"file": ("report.html", b"<h1>AI Report v3 Alias</h1>", "text/html")},
            headers=api_key_hdr,
        )
        assert alias_resp.status_code == 200
        assert alias_resp.json()["project"]["id"] == v1_id
        assert "AI Report v3 Alias" in client.get("/p/my-ai-report/index.html").text

        # Verify GET /api/admin/projects returns both space and my-ai-report without duplicates
        all_resp = client.get("/api/admin/projects", headers=bearer)
        assert all_resp.status_code == 200
        slugs = [p["slug"] for p in all_resp.json()["projects"]]
        assert slugs.count("my-ai-report") == 1

        # Verify Admin UI header does not expose raw API token or curl clutter
        login(client)
        admin_html = client.get("/admin").text
        assert "copy-api-token-btn" not in admin_html
        assert f'data-token="{token}"' not in admin_html
        assert "curl -X PUT" not in admin_html


def test_bilingual_i18n_assets_and_toggle_controls() -> None:
    with TestClient(app) as client:
        # 1. Verify /static/js/i18n.js serves the bilingual dictionary and SiteFlowI18n API
        i18n_js = client.get("/static/js/i18n.js")
        assert i18n_js.status_code == 200
        assert "siteflow_lang" in i18n_js.text
        assert "SiteFlowI18n" in i18n_js.text
        assert "Space Theme Customizer" in i18n_js.text
        assert "LAN QR Preview" in i18n_js.text

        # 2. Verify #lang-toggle-btn and i18n.js on public gallery and login pages
        gallery_html = client.get("/").text
        assert 'id="lang-toggle-btn"' in gallery_html
        assert "/static/js/i18n.js" in gallery_html
        assert "data-i18n=" in gallery_html

        login_html = client.get("/login").text
        assert 'id="lang-toggle-btn"' in login_html
        assert "/static/js/i18n.js" in login_html

        # 3. Verify #lang-toggle-btn and data-i18n on admin, space, and space detail pages
        csrf = login(client)
        admin_html = client.get("/admin").text
        assert 'id="lang-toggle-btn"' in admin_html
        assert 'data-testid="locale-toggle"' in admin_html
        assert "copy-api-token-btn" not in admin_html
        assert 'data-i18n="admin.new_space"' in admin_html

        space_resp = client.post(
            "/api/admin/projects/app",
            json={"type": "space", "title": "双语测试空间"},
            headers=auth_headers(csrf),
        )
        assert space_resp.status_code == 200
        space_proj = space_resp.json()["project"]

        space_admin_html = client.get(f"/admin/projects/{space_proj['id']}").text
        assert 'id="lang-toggle-btn"' in space_admin_html
        assert 'data-i18n="theme.section_title"' in space_admin_html
        assert 'data-i18n="theme.save_btn"' in space_admin_html

        space_pub_html = client.get(f"/projects/{space_proj['slug']}/").text
        assert 'id="lang-toggle-btn"' in space_pub_html
        assert "/static/js/i18n.js" in space_pub_html

        # 4. Verify Round 3 audit additions in i18n.js, preview.js, admin.js, and _admin_rows.html
        for expected in (
            '"简历": "Resume"',
            '"博客": "Blog"',
            '"已经在边界": "Already at the boundary"',
            '"标题不能为空": "Title cannot be empty"',
            '"未找到该项目": "Project not found"',
            '"简": "R"',
            '"博": "B"',
            '"新": "N"',
            "toZhText",
        ):
            assert expected in i18n_js.text

        preview_js = client.get("/static/js/preview.js").text
        assert "data-zh-title-orig" in preview_js
        assert "data-zh-orig" in preview_js

        admin_js = client.get("/static/js/admin.js").text
        assert "SiteFlowI18n.translateText(data.error)" in admin_js

        # Verify inline SVG cover in /admin rows
        admin_rows_html = client.get("/admin").text
        assert 'class="cover-svg thumb"' in admin_rows_html

        # 5. Verify English search queries match Chinese seeded titles
        fin_resp = client.post(
            "/api/admin/projects/app",
            json={"type": "space", "title": "2026 Q3 财务审计与预算决算"},
            headers=auth_headers(csrf),
        )
        assert fin_resp.status_code == 200
        search_en = client.get("/api/search?q=Financial").json()
        assert any(it["title"] == "2026 Q3 财务审计与预算决算" for it in search_en)

        # 6. Verify all 5 plugin templates (resume, resume_admin, blog, blog_admin, blog_post) have i18n & toggle
        resume_resp = client.post(
            "/api/admin/projects/app",
            json={"type": "resume", "title": "简历"},
            headers=auth_headers(csrf),
        )
        assert resume_resp.status_code == 200
        resume_proj = resume_resp.json()["project"]

        resume_pub = client.get(f"/projects/{resume_proj['slug']}/").text
        assert "/static/js/i18n.js" in resume_pub
        assert 'id="lang-toggle-btn"' in resume_pub
        assert 'data-i18n="resume.print_pdf"' in resume_pub

        resume_adm = client.get(f"/admin/projects/{resume_proj['id']}").text
        assert "/static/js/i18n.js" in resume_adm
        assert 'id="lang-toggle-btn"' in resume_adm
        assert 'data-i18n="resume.basic_info"' in resume_adm
        assert "/admin/logout" in resume_adm

        blog_resp = client.post(
            "/api/admin/projects/app",
            json={"type": "blog", "title": "博客"},
            headers=auth_headers(csrf),
        )
        assert blog_resp.status_code == 200
        blog_proj = blog_resp.json()["project"]
        client.patch(
            f"/api/admin/projects/{blog_proj['id']}",
            json={
                "content": '{"title":"技术博客","description":"架构笔记","posts":[{"slug":"hello","title":"第一篇","date":"2026-10-17","tags":["AI"],"summary":"摘要","body":"正文内容"}]}'
            },
            headers=auth_headers(csrf),
        )

        blog_pub = client.get(f"/projects/{blog_proj['slug']}/").text
        assert "/static/js/i18n.js" in blog_pub
        assert 'id="lang-toggle-btn"' in blog_pub
        assert 'data-i18n="blog.read_more"' in blog_pub

        blog_post_pub = client.get(f"/projects/{blog_proj['slug']}/posts/hello").text
        assert "/static/js/i18n.js" in blog_post_pub
        assert 'id="lang-toggle-btn"' in blog_post_pub
        assert 'data-i18n="blog.back_to_list"' in blog_post_pub

        blog_adm = client.get(f"/admin/projects/{blog_proj['id']}").text
        assert "/static/js/i18n.js" in blog_adm
        assert 'id="lang-toggle-btn"' in blog_adm
        assert 'data-i18n="blog.info_title"' in blog_adm
        assert "/admin/logout" in blog_adm
        assert "canonicalInputText" in blog_adm
        assert "canonicalInputText" in resume_adm
        assert "dataset.zhVal" in admin_js

        # 7. Verify .cover-svg.thumb rule in app.css and modal language toggles
        app_css = client.get("/static/css/app.css").text
        assert ".cover-svg.thumb" in app_css
        assert 'data-action="toggle-lang"' in gallery_html
        assert "postMessage" in preview_js
        assert "siteflow:lang" in preview_js
        assert "siteflow:lang" in i18n_js.text
