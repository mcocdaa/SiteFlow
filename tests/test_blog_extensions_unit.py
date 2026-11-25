from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import stats, store, uploads
from app.main import app
from app.models import Project
from app.plugins.base import InvalidContent
from app.plugins.blog.extensions import (
    BaseBlogExtension,
    active_extensions,
    all_extensions,
    build_admin_catalog,
    build_editor_bundle,
    build_render_bundle,
    get,
    normalize_extensions,
    normalize_post_meta,
    referenced_blog_media_urls,
    register,
    sanitize_image_url,
)
from app.templating import static_url, templates
from tests.test_apps import create_app
from tests.test_flow import auth_headers, login, make_png


def _blog_project(slug: str = "my-blog") -> Project:
    return Project(id=1, slug=slug, type="blog", title="测试博客")


def test_catalog_registration_and_schema_shape() -> None:
    ids = [ext.id for ext in all_extensions()]
    assert ids == ["post_cover", "post_background", "mascot"]
    assert get("post_cover") is not None
    assert get("unknown_ext") is None

    catalog = build_admin_catalog({"title": "旧博客", "posts": []})
    assert len(catalog) == 3
    for item in catalog:
        assert item["installed"] is False
        assert item["enabled"] is False
        assert set(item.keys()) >= {
            "id",
            "name",
            "name_key",
            "description",
            "description_key",
            "version",
            "icon",
            "installed",
            "enabled",
            "config",
            "default_config",
            "config_schema",
        }
        for field in item["config_schema"]:
            assert set(field.keys()) == {
                "key",
                "kind",
                "label_key",
                "label_default",
                "help_key",
                "help_default",
                "placeholder_key",
                "placeholder_default",
                "options",
                "min_value",
                "max_value",
                "step",
                "max_length",
                "upload_kind",
                "group",
                "group_key",
                "group_default",
                "accept",
                "rows",
            }


def test_register_rejects_invalid_id() -> None:
    bad = BaseBlogExtension()
    bad.id = "Bad-Id!"
    with pytest.raises(ValueError):
        register(bad)


def test_vanilla_and_legacy_blog_zero_footprint() -> None:
    project = _blog_project()
    legacy_posts: list[dict[str, Any]] = [{"slug": "p1", "title": "旧文", "body": "内容"}]
    legacy: dict[str, Any] = {"title": "旧博客", "posts": legacy_posts}
    assert active_extensions(legacy) == []

    list_bundle = build_render_bundle("list", project, legacy, posts=legacy_posts)
    assert list_bundle["css_files"] == []
    assert list_bundle["js_files"] == []
    assert list_bundle["body_classes"] == []
    assert list_bundle["body_start_fragments"] == []
    assert list_bundle["body_end_fragments"] == []
    assert list_bundle["list_card_templates"] == []
    assert list_bundle["contexts"] == {}

    post_bundle = build_render_bundle("post", project, legacy, post=legacy_posts[0])
    assert post_bundle["css_files"] == []
    assert post_bundle["post_header_templates"] == []

    editor_bundle = build_editor_bundle(legacy, project, post=legacy_posts[0])
    assert editor_bundle == {"fields": []}


def test_image_url_validation_blocks_unsafe_and_cross_blog() -> None:
    assert sanitize_image_url("https://example.com/a.png") == "https://example.com/a.png"
    assert sanitize_image_url("http://example.com/b.jpg?x=1#pic") == "http://example.com/b.jpg?x=1#pic"
    assert (
        sanitize_image_url("/media/blog/demo/cover-0123456789abcdef.webp", project_slug="demo")
        == "/media/blog/demo/cover-0123456789abcdef.webp"
    )
    assert sanitize_image_url("", strict=True) == ""
    assert sanitize_image_url(None, strict=True) == ""

    bad_urls = [
        "javascript:alert(1)",
        "JAVASCRIPT:alert(1)",
        "data:image/svg+xml,<svg onload=alert(1)>",
        "data:text/html,<script>alert(1)</script>",
        "vbscript:msgbox(1)",
        "file:///etc/passwd",
        "//evil.example/a.png",
        "/media/blog/other/cover-0123456789abcdef.webp",
        "/media/blog/demo/../other/cover-0123456789abcdef.webp",
        "/media/blog/demo/cover.png",
        'https://example.com/a.png" onload="alert(1)',
        "https://example.com/a.png');background:url(x",
        "https://example.com/<script>.png",
        "https://example.com/" + "a" * 500,
    ]
    for bad in bad_urls:
        assert sanitize_image_url(bad, project_slug="demo", strict=False) == ""
        with pytest.raises(InvalidContent):
            sanitize_image_url(bad, project_slug="demo", strict=True)


def test_normalize_extensions_and_post_meta() -> None:
    normalized = normalize_extensions(
        {
            "post_cover": {
                "installed": True,
                "enabled": True,
                "config": {
                    "show_in_list": True,
                    "show_in_post": False,
                    "aspect_ratio": "21/9",
                    "default_cover": "/media/blog/demo/cover-0123456789abcdef.webp",
                },
            },
            "post_background": {
                "installed": True,
                "enabled": False,
                "config": {"preset": "aurora", "opacity": 0.23, "apply_to": "post", "surface_card": False},
            },
            "mascot": {
                "installed": True,
                "enabled": True,
                "config": {"position": "left", "theme": "sakura", "tips": "第一条\n\n第二条\n第三条"},
            },
            "ghost": {"installed": True, "enabled": True},
        },
        strict=False,
        project_slug="demo",
    )
    assert set(normalized.keys()) == {"post_cover", "post_background", "mascot"}
    assert normalized["post_cover"]["config"]["aspect_ratio"] == "21/9"
    assert normalized["post_background"]["config"]["opacity"] == 0.25
    assert normalized["mascot"]["config"]["tips"] == ["第一条", "第二条", "第三条"]

    with pytest.raises(InvalidContent):
        normalize_extensions({"ghost": {"installed": True}}, strict=True)
    with pytest.raises(InvalidContent):
        normalize_extensions(
            {"post_background": {"installed": True, "config": {"opacity": 0.9}}},
            strict=True,
        )
    with pytest.raises(InvalidContent):
        normalize_extensions(
            {"post_background": {"installed": True, "config": {"preset": "invalid"}}},
            strict=True,
        )
    with pytest.raises(InvalidContent):
        normalize_extensions(
            {"post_background": {"installed": True, "config": {"opacity": True}}},
            strict=True,
        )
    with pytest.raises(InvalidContent):
        normalize_extensions(
            {"mascot": {"installed": True, "config": {"position": "top"}}},
            strict=True,
        )

    assert normalize_post_meta({}) == {}
    assert normalize_post_meta({"cover": "", "cover_alt": "无图"}) == {}
    meta = normalize_post_meta(
        {"cover": "https://cdn.example/c.webp", "cover_alt": "<b>封面</b>"},
        strict=True,
        project_slug="demo",
    )
    assert meta == {"cover": "https://cdn.example/c.webp", "cover_alt": "<b>封面</b>"}
    with pytest.raises(InvalidContent):
        normalize_post_meta({"cover": "javascript:alert(1)"}, strict=True, project_slug="demo")


def test_render_bundles_templates_and_xss_safety() -> None:
    project = _blog_project("demo")
    posts: list[dict[str, Any]] = [
        {
            "slug": "first",
            "title": '第一篇<script>alert("t")</script>',
            "body": "正文",
            "meta": {
                "cover": "/media/blog/demo/cover-abcdef0123456789.webp",
                "cover_alt": '封面" onload="alert(1)',
            },
        },
        {"slug": "plain", "title": "第二篇", "body": "正文"},
    ]
    blog: dict[str, Any] = {
        "title": "演示博客",
        "posts": posts,
        "extensions": {
            "post_cover": {
                "installed": True,
                "enabled": True,
                "config": {
                    "show_in_list": True,
                    "show_in_post": True,
                    "aspect_ratio": "16/10",
                    "default_cover": "",
                },
            },
            "post_background": {
                "installed": True,
                "enabled": True,
                "config": {
                    "preset": "aurora",
                    "image_url": "/media/blog/demo/bg-abcdef0123456789.webp",
                    "opacity": 0.25,
                    "apply_to": "post",
                    "surface_card": True,
                },
            },
            "mascot": {
                "installed": True,
                "enabled": True,
                "config": {
                    "position": "left",
                    "theme": "mint",
                    "greeting": "<script>alert(1)</script>你好",
                    "tips": ["</script><img src=x onerror=alert(2)>", "第二条"],
                    "show_on_mobile": True,
                },
            },
        },
    }

    list_bundle = build_render_bundle("list", project, blog, posts=posts)
    assert list_bundle["css_files"] == [
        static_url("/static/css/blog_ext_cover.css"),
        static_url("/static/css/blog_ext_background.css"),
        static_url("/static/css/blog_ext_mascot.css"),
    ]
    assert list_bundle["js_files"] == [static_url("/static/js/blog_ext_mascot.js")]
    assert "has-post-cover" in list_bundle["body_classes"]
    assert "has-blog-bg" not in list_bundle["body_classes"]
    assert list_bundle["body_start_fragments"] == []
    assert len(list_bundle["body_end_fragments"]) == 1
    assert list_bundle["list_card_templates"] == [("post_cover", "extensions/_post_cover_card.html")]

    mascot_html = str(list_bundle["body_end_fragments"][0])
    assert "sf-mascot-left" in mascot_html
    assert "sf-mascot-theme-mint" in mascot_html
    assert "sf-mascot-hide-mobile" not in mascot_html
    assert "<script>alert(1)</script>" not in mascot_html
    assert "</script><img" not in mascot_html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in mascot_html
    assert "\\u003c/script\\u003e" in mascot_html
    assert "style=" not in mascot_html
    assert "http://" not in mascot_html and "https://" not in mascot_html

    card_tpl = templates.env.get_template("extensions/_post_cover_card.html")
    card_html = card_tpl.render(post=posts[0], ext=list_bundle)
    assert 'src="/media/blog/demo/cover-abcdef0123456789.webp"' in card_html
    assert 'referrerpolicy="no-referrer"' in card_html
    assert "ratio-16-10" in card_html
    assert 'onload="alert(1)' not in card_html
    assert "&#34;" in card_html or "&quot;" in card_html
    assert card_tpl.render(post=posts[1], ext=list_bundle).strip() == ""

    post_bundle = build_render_bundle("post", project, blog, post=posts[0])
    assert "has-blog-bg" in post_bundle["body_classes"]
    assert "blog-bg-preset-aurora" in post_bundle["body_classes"]
    assert "has-blog-bg-card" in post_bundle["body_classes"]
    assert len(post_bundle["body_start_fragments"]) == 1
    bg_html = str(post_bundle["body_start_fragments"][0])
    assert "blog-bg-layer-aurora" in bg_html
    assert "blog-bg-op-25" in bg_html
    assert 'src="/media/blog/demo/bg-abcdef0123456789.webp"' in bg_html
    assert 'referrerpolicy="no-referrer"' in bg_html
    assert "style=" not in bg_html and "<style" not in bg_html

    header_tpl = templates.env.get_template("extensions/_post_cover_header.html")
    header_html = header_tpl.render(post=posts[0], ext=post_bundle)
    assert "post-cover-banner" in header_html
    assert 'referrerpolicy="no-referrer"' in header_html
    assert "style=" not in header_html

    editor_bundle = build_editor_bundle(blog, project, post=posts[0])
    assert len(editor_bundle["fields"]) == 1
    field = editor_bundle["fields"][0]
    assert field["id"] == "post_cover"
    editor_tpl = templates.env.get_template(field["template"])
    editor_html = editor_tpl.render(field=field, post=posts[0])
    assert 'name="meta.cover"' in editor_html
    assert 'name="meta.cover_alt"' in editor_html
    assert 'data-ext-upload="post_cover"' in editor_html
    assert 'data-upload-kind="cover"' in editor_html
    assert 'data-upload-target="meta.cover"' in editor_html
    assert 'data-ext-clear="meta.cover"' in editor_html
    assert 'data-ext-preview="meta.cover"' in editor_html
    assert "style=" not in editor_html and "<script" not in editor_html

    refs = referenced_blog_media_urls(blog)
    assert refs == {
        "/media/blog/demo/cover-abcdef0123456789.webp",
        "/media/blog/demo/bg-abcdef0123456789.webp",
    }


def test_icons_template_has_extension_icons() -> None:
    tpl = templates.env.from_string('{% import "icons.html" as icons %}{{ icons.icon(name) }}')
    for name in ("puzzle", "palette", "sparkles"):
        svg = tpl.render(name=name)
        assert "<svg " in svg and "</svg>" in svg


def test_uploads_blog_media_save_delete_and_limits(monkeypatch) -> None:
    with TestClient(app):
        config = app.state.config
        url = uploads.save_blog_media(config, "my-blog", "cover", make_png())
        assert url.startswith("/media/blog/my-blog/cover-") and url.endswith(".webp")
        filename = url.rsplit("/", 1)[1]
        disk_path = config.data / "media" / "blog" / "my-blog" / filename
        assert disk_path.is_file()

        with pytest.raises(uploads.InvalidUpload):
            uploads.save_blog_media(config, "my-blog", "invalid", make_png())
        with pytest.raises(uploads.InvalidUpload):
            uploads.save_blog_media(config, "../escape", "cover", make_png())
        with pytest.raises(uploads.InvalidUpload):
            uploads.save_blog_media(config, "my-blog", "cover", b"not-an-image")

        monkeypatch.setattr(uploads, "MAX_BLOG_MEDIA_FILES", 1)
        with pytest.raises(uploads.InvalidUpload):
            uploads.save_blog_media(config, "my-blog", "bg", make_png())

        assert uploads.delete_blog_media_url(config, "other-blog", url) is False
        assert uploads.delete_blog_media_url(config, "my-blog", "/media/blog/my-blog/../x.webp") is False
        assert uploads.delete_blog_media_url(config, "my-blog", url) is True
        assert not disk_path.exists()


def test_blog_media_endpoint_security_visibility_pv_and_cleanup() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        blog = create_app(client, csrf, "blog", "媒体博客").json()["project"]
        space = create_app(client, csrf, "space", "非博客空间").json()["project"]
        slug = blog["slug"]

        media_url = uploads.save_blog_media(app.state.config, slug, "cover", make_png())
        uploads.save_blog_media(app.state.config, space["slug"], "cover", make_png())

        assert client.get(f"/media/blog/{space['slug']}/cover-1234567890abcdef.webp").status_code == 404
        assert client.get(f"/media/blog/{slug}/not-webp.png").status_code == 404
        assert client.get(f"/media/blog/{slug}/../secret.webp").status_code == 404
        assert client.get(f"/media/blog/{slug}/missing.webp").status_code == 404

        client.cookies.clear()
        resp = client.get(media_url)
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/webp"
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert resp.headers["cache-control"] == "public, max-age=86400"
        etag = resp.headers["etag"]

        not_mod = client.get(media_url, headers={"If-None-Match": etag})
        assert not_mod.status_code == 304
        assert not_mod.headers["x-content-type-options"] == "nosniff"

        with store.session() as db:
            assert stats.get_7day_stats(db)["today_pv"] == 0
            assert stats.get_7day_stats(db, blog["id"])["today_pv"] == 0

        csrf = login(client)
        assert (
            client.patch(
                f"/api/admin/projects/{blog['id']}",
                json={"visible": False},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        admin_hidden = client.get(media_url)
        assert admin_hidden.status_code == 200
        assert admin_hidden.headers["cache-control"] == "private, max-age=86400"

        client.cookies.clear()
        assert client.get(media_url).status_code == 404

        csrf = login(client)
        assert (
            client.patch(
                f"/api/admin/projects/{blog['id']}",
                json={"visible": True, "password": "secret-blog-password"},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert client.get(media_url).status_code == 200

        client.cookies.clear()
        assert client.get(media_url).status_code == 401
        unlocked = client.post(
            f"/projects/{slug}/unlock",
            data={"password": "secret-blog-password"},
            follow_redirects=False,
        )
        assert unlocked.status_code == 303
        unlocked_media = client.get(media_url)
        assert unlocked_media.status_code == 200
        assert unlocked_media.headers["cache-control"] == "private, max-age=86400"

        csrf = login(client)
        media_dir = Path(app.state.config.data) / "media" / "blog" / slug
        assert media_dir.exists()
        assert (
            client.delete(f"/api/admin/projects/{blog['id']}", headers=auth_headers(csrf)).status_code == 200
        )
        assert not media_dir.exists()
