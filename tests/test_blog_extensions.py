import json
from pathlib import Path

from fastapi.testclient import TestClient

from app import stats, store
from app.main import app
from tests.test_apps import create_app
from tests.test_flow import ORIGIN, auth_headers, login, make_png


def test_blog_extensions_catalog_and_legacy_zero_footprint() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        blog = create_app(client, csrf, "blog", "传统博客").json()["project"]
        pid, slug = blog["id"], blog["slug"]

        catalog_resp = client.get(f"/api/admin/projects/{pid}/extensions", headers=auth_headers(csrf))
        assert catalog_resp.status_code == 200
        catalog = catalog_resp.json()["extensions"]
        assert [item["id"] for item in catalog] == ["post_cover", "post_background", "mascot"]
        assert all(item["installed"] is False and item["enabled"] is False for item in catalog)

        admin_page = client.get(f"/admin/projects/{pid}")
        assert admin_page.status_code == 200
        assert 'id="blog-extensions"' in admin_page.text
        for ext_id in ("post_cover", "post_background", "mascot"):
            assert f'data-ext-install="{ext_id}"' in admin_page.text

        editor_page = client.get(f"/admin/projects/{pid}/posts/new")
        assert editor_page.status_code == 200
        assert 'name="meta.cover"' not in editor_page.text

        legacy_content = {
            "title": "传统博客",
            "description": "兼容旧数据",
            "posts": [{"slug": "legacy-1", "title": "旧文章", "body": "纯文本正文"}],
        }
        patched = client.patch(
            f"/api/admin/projects/{pid}",
            json={"content": json.dumps(legacy_content, ensure_ascii=False)},
            headers=auth_headers(csrf),
        )
        assert patched.status_code == 200
        stored = json.loads(patched.json()["project"]["content"])
        assert "extensions" not in stored
        assert stored["posts"] == [
            {
                "slug": "legacy-1",
                "title": "旧文章",
                "date": "",
                "tags": [],
                "summary": "",
                "body": "纯文本正文",
            }
        ]

        for url in (f"/projects/{slug}/", f"/projects/{slug}/posts/legacy-1"):
            page = client.get(url)
            assert page.status_code == 200
            assert "blog_ext_" not in page.text
            assert "sf-mascot" not in page.text
            assert "blog-bg-layer" not in page.text
            assert "post-cover-" not in page.text


def test_blog_extensions_api_auth_and_lifecycle() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        blog = create_app(client, csrf, "blog", "插件生命周期博客").json()["project"]
        space = create_app(client, csrf, "space", "普通空间").json()["project"]
        pid = blog["id"]

        html_proj = client.post(
            "/api/admin/projects/upload",
            files={"file": ("demo.html", b"<h1>hi</h1>", "text/html")},
            headers=auth_headers(csrf),
        ).json()["project"]

        assert (
            client.get(
                f"/api/admin/projects/{html_proj['id']}/extensions", headers=auth_headers(csrf)
            ).status_code
            == 400
        )
        assert (
            client.post(
                f"/api/admin/projects/{space['id']}/extensions/post_cover/install",
                json={"enabled": True},
                headers=auth_headers(csrf),
            ).status_code
            == 400
        )
        assert (
            client.get("/api/admin/projects/99999/extensions", headers=auth_headers(csrf)).status_code == 404
        )
        assert (
            client.post(
                f"/api/admin/projects/{pid}/extensions/nonexistent/install",
                json={"enabled": True},
                headers=auth_headers(csrf),
            ).status_code
            == 404
        )

        not_installed = client.patch(
            f"/api/admin/projects/{pid}/extensions/post_cover",
            json={"enabled": True},
            headers=auth_headers(csrf),
        )
        assert not_installed.status_code == 400
        assert "请先安装" in not_installed.json()["error"]

        upload_before_install = client.post(
            f"/api/admin/projects/{pid}/extensions/post_cover/media",
            files={"file": ("c.png", make_png(), "image/png")},
            data={"kind": "cover"},
            headers=auth_headers(csrf),
        )
        assert upload_before_install.status_code == 400

        assert client.post(f"/api/admin/projects/{pid}/extensions/post_cover/install").status_code == 403
        foreign = {**auth_headers(csrf), "Origin": "https://evil.example"}
        assert (
            client.post(
                f"/api/admin/projects/{pid}/extensions/post_cover/install",
                json={"enabled": True},
                headers=foreign,
            ).status_code
            == 403
        )
        assert (
            client.patch(
                f"/api/admin/projects/{pid}/extensions/post_cover",
                json={"enabled": False},
                headers=ORIGIN,
            ).status_code
            == 403
        )
        assert (
            client.delete(f"/api/admin/projects/{pid}/extensions/post_cover", headers=foreign).status_code
            == 403
        )

        bad_install = client.post(
            f"/api/admin/projects/{pid}/extensions/post_cover/install",
            json={"enabled": True, "config": {"aspect_ratio": "99/1"}},
            headers=auth_headers(csrf),
        )
        assert bad_install.status_code == 422

        installed = client.post(
            f"/api/admin/projects/{pid}/extensions/post_cover/install",
            headers=auth_headers(csrf),
        )
        assert installed.status_code == 200
        ext_data = installed.json()["extension"]
        assert ext_data["installed"] is True
        assert ext_data["enabled"] is True
        assert ext_data["config"]["aspect_ratio"] == "16/9"

        updated_cfg = client.patch(
            f"/api/admin/projects/{pid}/extensions/post_cover",
            json={"config": {"aspect_ratio": "21/9", "show_in_post": False}},
            headers=auth_headers(csrf),
        )
        assert updated_cfg.status_code == 200
        assert updated_cfg.json()["extension"]["config"]["aspect_ratio"] == "21/9"
        assert updated_cfg.json()["extension"]["config"]["show_in_post"] is False
        assert updated_cfg.json()["extension"]["config"]["show_in_list"] is True

        reinstalled = client.post(
            f"/api/admin/projects/{pid}/extensions/post_cover/install",
            headers=auth_headers(csrf),
        )
        assert reinstalled.status_code == 200
        assert reinstalled.json()["extension"]["config"]["aspect_ratio"] == "21/9"

        bad_patch = client.patch(
            f"/api/admin/projects/{pid}/extensions/post_cover",
            json={"config": {"default_cover": "javascript:alert(1)"}},
            headers=auth_headers(csrf),
        )
        assert bad_patch.status_code == 422

        disabled = client.patch(
            f"/api/admin/projects/{pid}/extensions/post_cover",
            json={"enabled": False},
            headers=auth_headers(csrf),
        )
        assert disabled.status_code == 200
        assert disabled.json()["extension"]["installed"] is True
        assert disabled.json()["extension"]["enabled"] is False
        assert disabled.json()["extension"]["config"]["aspect_ratio"] == "21/9"

        disabled_page = client.get(f"/projects/{blog['slug']}/")
        assert disabled_page.status_code == 200
        assert "blog_ext_cover.css" not in disabled_page.text

        reenabled = client.patch(
            f"/api/admin/projects/{pid}/extensions/post_cover",
            json={"enabled": True},
            headers=auth_headers(csrf),
        )
        assert reenabled.status_code == 200
        assert reenabled.json()["extension"]["enabled"] is True
        assert reenabled.json()["extension"]["config"]["aspect_ratio"] == "21/9"

        meta_patch = client.patch(
            f"/api/admin/projects/{pid}",
            json={"title": "重命名博客", "description": "新简介"},
            headers=auth_headers(csrf),
        )
        assert meta_patch.status_code == 200
        after_meta = json.loads(meta_patch.json()["project"]["content"])
        assert after_meta["extensions"]["post_cover"]["config"]["aspect_ratio"] == "21/9"

        uninstalled = client.delete(
            f"/api/admin/projects/{pid}/extensions/post_cover",
            headers=auth_headers(csrf),
        )
        assert uninstalled.status_code == 200
        assert uninstalled.json()["extension"]["installed"] is False
        assert uninstalled.json()["extension"]["enabled"] is False

        client.cookies.clear()
        assert client.get(f"/api/admin/projects/{pid}/extensions").status_code == 401


def test_post_cover_e2e_upload_render_privacy_non_destructive_and_cleanup() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        blog = create_app(client, csrf, "blog", "封面博客").json()["project"]
        other_blog = create_app(client, csrf, "blog", "他人的博客").json()["project"]
        pid, slug = blog["id"], blog["slug"]

        assert (
            client.post(
                f"/api/admin/projects/{pid}/extensions/post_cover/install",
                json={"enabled": True},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert (
            client.post(
                f"/api/admin/projects/{pid}/extensions/mascot/install",
                json={"enabled": False},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert (
            client.post(
                f"/api/admin/projects/{other_blog['id']}/extensions/post_cover/install",
                json={"enabled": True},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )

        editor_enabled = client.get(f"/admin/projects/{pid}/posts/new")
        assert editor_enabled.status_code == 200
        assert 'name="meta.cover"' in editor_enabled.text
        assert 'name="meta.cover_alt"' in editor_enabled.text
        assert 'data-ext-upload="post_cover"' in editor_enabled.text
        assert 'data-ext-clear="meta.cover"' in editor_enabled.text

        up1 = client.post(
            f"/api/admin/projects/{pid}/extensions/post_cover/media",
            files={"file": ("cover1.png", make_png(), "image/png")},
            data={"kind": "cover"},
            headers=auth_headers(csrf),
        )
        assert up1.status_code == 200
        cover_url_1 = up1.json()["url"]
        assert cover_url_1.startswith(f"/media/blog/{slug}/cover-") and cover_url_1.endswith(".webp")

        bad_img = client.post(
            f"/api/admin/projects/{pid}/extensions/post_cover/media",
            files={"file": ("bad.png", b"not-an-image", "image/png")},
            data={"kind": "cover"},
            headers=auth_headers(csrf),
        )
        assert bad_img.status_code == 422

        too_big = client.post(
            f"/api/admin/projects/{pid}/extensions/post_cover/media",
            files={"file": ("huge.png", b"x" * (10 * 1024 * 1024 + 1), "image/png")},
            data={"kind": "cover"},
            headers=auth_headers(csrf),
        )
        assert too_big.status_code == 413

        wrong_kind = client.post(
            f"/api/admin/projects/{pid}/extensions/post_cover/media",
            files={"file": ("bg.png", make_png(), "image/png")},
            data={"kind": "bg"},
            headers=auth_headers(csrf),
        )
        assert wrong_kind.status_code == 400

        mascot_upload = client.post(
            f"/api/admin/projects/{pid}/extensions/mascot/media",
            files={"file": ("m.png", make_png(), "image/png")},
            data={"kind": "cover"},
            headers=auth_headers(csrf),
        )
        assert mascot_upload.status_code == 400

        other_cover = client.post(
            f"/api/admin/projects/{other_blog['id']}/extensions/post_cover/media",
            files={"file": ("other.png", make_png(), "image/png")},
            data={"kind": "cover"},
            headers=auth_headers(csrf),
        ).json()["url"]
        cross_blog_post = client.post(
            f"/api/admin/projects/{pid}/posts",
            json={"title": "越权封面", "slug": "cross", "body": "正文", "meta": {"cover": other_cover}},
            headers=auth_headers(csrf),
        )
        assert cross_blog_post.status_code == 422

        cross_blog_default = client.patch(
            f"/api/admin/projects/{pid}/extensions/post_cover",
            json={"config": {"default_cover": other_cover}},
            headers=auth_headers(csrf),
        )
        assert cross_blog_default.status_code == 422

        created = client.post(
            f"/api/admin/projects/{pid}/posts",
            json={
                "title": "封面文章",
                "slug": "with-cover",
                "date": "2026-10-01",
                "body": "正文内容",
                "meta": {"cover": cover_url_1, "cover_alt": '说明" onload="alert(1)'},
            },
            headers=auth_headers(csrf),
        )
        assert created.status_code == 200
        assert created.json()["post"]["meta"]["cover"] == cover_url_1

        plain_created = client.post(
            f"/api/admin/projects/{pid}/posts",
            json={"title": "无封面文章", "slug": "no-cover", "date": "2026-09-20", "body": "普通正文"},
            headers=auth_headers(csrf),
        )
        assert plain_created.status_code == 200
        assert "meta" not in plain_created.json()["post"]

        client.cookies.clear()
        media_resp = client.get(cover_url_1)
        assert media_resp.status_code == 200
        assert media_resp.headers["content-type"] == "image/webp"
        assert media_resp.headers["x-content-type-options"] == "nosniff"
        with store.session() as db:
            assert stats.get_7day_stats(db)["today_pv"] == 0

        list_page = client.get(f"/projects/{slug}/")
        assert list_page.status_code == 200
        assert "/static/css/blog_ext_cover.css" in list_page.text
        assert f'src="{cover_url_1}"' in list_page.text
        assert 'referrerpolicy="no-referrer"' in list_page.text
        assert "post-cover-thumb ratio-16-9" in list_page.text
        assert 'onload="alert(1)' not in list_page.text
        assert list_page.text.count("post-cover-thumb") == 1

        detail_page = client.get(f"/projects/{slug}/posts/with-cover")
        assert detail_page.status_code == 200
        assert "post-cover-banner ratio-16-9" in detail_page.text
        assert f'src="{cover_url_1}"' in detail_page.text
        assert "style=" not in detail_page.text

        csrf = login(client)
        fallback_url = "https://example.com/default-cover.webp"
        assert (
            client.patch(
                f"/api/admin/projects/{pid}/extensions/post_cover",
                json={
                    "config": {
                        "show_in_list": True,
                        "show_in_post": False,
                        "aspect_ratio": "16/10",
                        "default_cover": fallback_url,
                    }
                },
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        list_with_fallback = client.get(f"/projects/{slug}/")
        assert list_with_fallback.text.count("post-cover-thumb ratio-16-10") == 2
        assert fallback_url in list_with_fallback.text
        detail_no_banner = client.get(f"/projects/{slug}/posts/with-cover")
        assert "post-cover-banner" not in detail_no_banner.text

        assert (
            client.patch(
                f"/api/admin/projects/{pid}/extensions/post_cover",
                json={"enabled": False},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert 'name="meta.cover"' not in client.get(f"/admin/projects/{pid}/posts/with-cover/edit").text
        edited_without_meta = client.patch(
            f"/api/admin/projects/{pid}/posts/with-cover",
            json={
                "title": "封面文章（更新）",
                "slug": "with-cover",
                "date": "2026-10-01",
                "body": "更新后正文",
            },
            headers=auth_headers(csrf),
        )
        assert edited_without_meta.status_code == 200
        assert edited_without_meta.json()["post"]["meta"]["cover"] == cover_url_1

        assert (
            client.patch(
                f"/api/admin/projects/{pid}/extensions/post_cover",
                json={"enabled": True, "config": {"show_in_post": True, "default_cover": ""}},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        restored_detail = client.get(f"/projects/{slug}/posts/with-cover")
        assert f'src="{cover_url_1}"' in restored_detail.text

        assert (
            client.patch(
                f"/api/admin/projects/{pid}",
                json={"visible": False},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert client.get(cover_url_1).status_code == 200
        client.cookies.clear()
        assert client.get(cover_url_1).status_code == 404

        csrf = login(client)
        assert (
            client.patch(
                f"/api/admin/projects/{pid}",
                json={"visible": True, "password": "blog-secret-pass"},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert client.get(cover_url_1).status_code == 200
        client.cookies.clear()
        assert client.get(cover_url_1).status_code == 401
        unlock = client.post(
            f"/projects/{slug}/unlock",
            data={"password": "blog-secret-pass"},
            follow_redirects=False,
        )
        assert unlock.status_code == 303
        assert client.get(cover_url_1).status_code == 200

        csrf = login(client)
        assert (
            client.patch(
                f"/api/admin/projects/{pid}",
                json={"password": "clear"},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        cover_url_2 = client.post(
            f"/api/admin/projects/{pid}/extensions/post_cover/media",
            files={"file": ("cover2.png", make_png(), "image/png")},
            data={"kind": "cover"},
            headers=auth_headers(csrf),
        ).json()["url"]
        replaced = client.patch(
            f"/api/admin/projects/{pid}/posts/with-cover",
            json={
                "title": "封面文章（换图）",
                "slug": "with-cover",
                "date": "2026-10-01",
                "body": "正文",
                "meta": {"cover": cover_url_2, "cover_alt": "新图"},
            },
            headers=auth_headers(csrf),
        )
        assert replaced.status_code == 200
        assert client.get(cover_url_1).status_code == 404
        assert client.get(cover_url_2).status_code == 200

        assert (
            client.delete(
                f"/api/admin/projects/{pid}/posts/with-cover", headers=auth_headers(csrf)
            ).status_code
            == 200
        )
        assert client.get(cover_url_2).status_code == 404

        default_upload = client.post(
            f"/api/admin/projects/{pid}/extensions/post_cover/media",
            files={"file": ("def.png", make_png(), "image/png")},
            data={"kind": "cover"},
            headers=auth_headers(csrf),
        ).json()["url"]
        assert (
            client.patch(
                f"/api/admin/projects/{pid}/extensions/post_cover",
                json={"config": {"default_cover": default_upload}},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert client.get(default_upload).status_code == 200
        assert (
            client.delete(
                f"/api/admin/projects/{pid}/extensions/post_cover",
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert client.get(default_upload).status_code == 404

        assert (
            client.post(
                f"/api/admin/projects/{pid}/extensions/post_cover/install",
                json={"enabled": True},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        final_cover = client.post(
            f"/api/admin/projects/{pid}/extensions/post_cover/media",
            files={"file": ("final.png", make_png(), "image/png")},
            data={"kind": "cover"},
            headers=auth_headers(csrf),
        ).json()["url"]
        assert (
            client.post(
                f"/api/admin/projects/{pid}/posts",
                json={"title": "收尾", "slug": "last", "body": "x", "meta": {"cover": final_cover}},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        media_dir = Path(app.state.config.data) / "media" / "blog" / slug
        assert media_dir.is_dir()
        assert client.delete(f"/api/admin/projects/{pid}", headers=auth_headers(csrf)).status_code == 200
        assert not media_dir.exists()


def test_post_background_e2e_presets_image_opacity_and_xss_defense() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        blog = create_app(client, csrf, "blog", "背景博客").json()["project"]
        pid, slug = blog["id"], blog["slug"]
        assert (
            client.post(
                f"/api/admin/projects/{pid}/posts",
                json={"title": "背景文章", "slug": "bg-post", "body": "正文内容"},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )

        assert (
            client.post(
                f"/api/admin/projects/{pid}/extensions/post_background/install",
                json={"enabled": True},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )

        for preset in ("dots", "grid", "aurora", "paper"):
            res = client.patch(
                f"/api/admin/projects/{pid}/extensions/post_background",
                json={"config": {"preset": preset, "apply_to": "all", "surface_card": True}},
                headers=auth_headers(csrf),
            )
            assert res.status_code == 200
            page = client.get(f"/projects/{slug}/")
            assert f"blog-bg-preset-{preset}" in page.text
            assert f"blog-bg-layer-{preset}" in page.text
            assert "has-blog-bg-card" in page.text
            assert "/static/css/blog_ext_background.css" in page.text

        assert (
            client.patch(
                f"/api/admin/projects/{pid}/extensions/post_background",
                json={"config": {"apply_to": "post", "surface_card": False}},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        list_only = client.get(f"/projects/{slug}/")
        assert "blog-bg-layer" not in list_only.text
        assert "has-blog-bg-card" not in list_only.text
        post_only = client.get(f"/projects/{slug}/posts/bg-post")
        assert "blog-bg-layer" in post_only.text
        assert "has-blog-bg-card" not in post_only.text

        bg_upload = client.post(
            f"/api/admin/projects/{pid}/extensions/post_background/media",
            files={"file": ("wall.png", make_png(), "image/png")},
            data={"kind": "bg"},
            headers=auth_headers(csrf),
        )
        assert bg_upload.status_code == 200
        bg_url = bg_upload.json()["url"]

        assert (
            client.patch(
                f"/api/admin/projects/{pid}/extensions/post_background",
                json={"config": {"preset": "none", "image_url": bg_url, "opacity": 0.30, "apply_to": "all"}},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        bg_page = client.get(f"/projects/{slug}/posts/bg-post")
        assert f'src="{bg_url}"' in bg_page.text
        assert "blog-bg-op-30" in bg_page.text
        assert 'referrerpolicy="no-referrer"' in bg_page.text
        assert "style=" not in bg_page.text and "<style" not in bg_page.text

        for bad_url in (
            "javascript:alert(1)",
            "data:image/svg+xml,<svg onload=alert(1)>",
            "https://evil.test/bg.png');background:url(x",
            'https://evil.test/bg.png" onerror="alert(1)',
        ):
            bad_resp = client.patch(
                f"/api/admin/projects/{pid}/extensions/post_background",
                json={"config": {"image_url": bad_url}},
                headers=auth_headers(csrf),
            )
            assert bad_resp.status_code == 422

        cleared = client.patch(
            f"/api/admin/projects/{pid}/extensions/post_background",
            json={"config": {"image_url": ""}},
            headers=auth_headers(csrf),
        )
        assert cleared.status_code == 200
        assert client.get(bg_url).status_code == 404


def test_mascot_e2e_render_xss_escaping_and_zero_cdn() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        blog = create_app(client, csrf, "blog", "看板娘博客").json()["project"]
        pid, slug = blog["id"], blog["slug"]
        assert (
            client.post(
                f"/api/admin/projects/{pid}/posts",
                json={"title": "互动测试", "slug": "mascot-post", "body": "正文"},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )

        installed = client.post(
            f"/api/admin/projects/{pid}/extensions/mascot/install",
            json={
                "enabled": True,
                "config": {
                    "position": "left",
                    "theme": "sakura",
                    "greeting": "<script>alert(1)</script>欢迎光临",
                    "tips": ["</script><img src=x onerror=alert(2)>", "第二条提示"],
                    "show_on_mobile": True,
                },
            },
            headers=auth_headers(csrf),
        )
        assert installed.status_code == 200

        for url in (f"/projects/{slug}/", f"/projects/{slug}/posts/mascot-post"):
            page = client.get(url)
            assert page.status_code == 200
            assert "/static/css/blog_ext_mascot.css" in page.text
            assert "/static/js/blog_ext_mascot.js" in page.text
            assert "sf-mascot-left" in page.text
            assert "sf-mascot-theme-sakura" in page.text
            assert "sf-mascot-hide-mobile" not in page.text
            assert 'class="sf-mascot-svg sf-mascot-skin-cat"' in page.text
            assert 'type="application/json" data-mascot-config' in page.text
            assert "<script>alert(1)</script>" not in page.text
            assert "</script><img" not in page.text
            assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page.text
            assert "\\u003c/script\\u003e" in page.text
            assert "style=" not in page.text
            assert "http://" not in page.text and "https://" not in page.text

        assert (
            client.patch(
                f"/api/admin/projects/{pid}/extensions/mascot",
                json={"config": {"show_on_mobile": False, "position": "right", "theme": "mono"}},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        updated_page = client.get(f"/projects/{slug}/")
        assert "sf-mascot-hide-mobile" in updated_page.text
        assert "sf-mascot-right" in updated_page.text
        assert "sf-mascot-theme-mono" in updated_page.text
