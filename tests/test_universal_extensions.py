import json

import pytest
from fastapi.testclient import TestClient

from app import stats, store
from app.extensions.registry import build_render_bundle
from app.main import app
from app.models import Project
from tests.test_apps import create_app
from tests.test_flow import auth_headers, login, make_png, make_zip


def _create_non_extensible(client: TestClient, csrf: str) -> dict[str, dict]:
    html_proj = client.post(
        "/api/admin/projects/upload",
        files={"file": ("page.html", b"<h1>Hello</h1>", "text/html")},
        headers=auth_headers(csrf),
    ).json()["project"]
    zip_proj = client.post(
        "/api/admin/projects/upload",
        files={"file": ("site.zip", make_zip({"index.html": b"<h1>Zip</h1>"}), "application/zip")},
        headers=auth_headers(csrf),
    ).json()["project"]
    link_proj = client.post(
        "/api/admin/projects/link",
        json={"url": "https://example.com/demo", "title": "示例链接"},
        headers=auth_headers(csrf),
    ).json()["project"]
    return {"html": html_proj, "zip": zip_proj, "link": link_proj}


def test_target_isolation_across_blog_space_resume_and_non_extensible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.admin.fetch_og", lambda url: None)
    with TestClient(app) as client:
        csrf = login(client)
        blog = create_app(client, csrf, "blog", "隔离测试博客").json()["project"]
        space = create_app(client, csrf, "space", "隔离测试空间").json()["project"]
        resume = create_app(client, csrf, "resume", "隔离测试简历").json()["project"]
        others = _create_non_extensible(client, csrf)

        blog_cat = client.get(
            f"/api/admin/projects/{blog['id']}/extensions", headers=auth_headers(csrf)
        ).json()["extensions"]
        space_cat = client.get(
            f"/api/admin/projects/{space['id']}/extensions", headers=auth_headers(csrf)
        ).json()["extensions"]
        resume_cat = client.get(
            f"/api/admin/projects/{resume['id']}/extensions", headers=auth_headers(csrf)
        ).json()["extensions"]

        assert [item["id"] for item in blog_cat] == ["post_cover", "post_background", "mascot"]
        assert [item["id"] for item in space_cat] == [
            "mascot",
            "space_banner",
            "space_background",
            "space_layout",
        ]
        assert [item["id"] for item in resume_cat] == ["mascot", "resume_style"]

        cross_pairs = [
            (blog["id"], "space_banner"),
            (blog["id"], "space_background"),
            (blog["id"], "space_layout"),
            (blog["id"], "resume_style"),
            (space["id"], "post_cover"),
            (space["id"], "post_background"),
            (space["id"], "resume_style"),
            (resume["id"], "post_cover"),
            (resume["id"], "post_background"),
            (resume["id"], "space_banner"),
            (resume["id"], "space_background"),
            (resume["id"], "space_layout"),
        ]
        for pid, ext_id in cross_pairs:
            assert (
                client.post(
                    f"/api/admin/projects/{pid}/extensions/{ext_id}/install",
                    json={"enabled": True},
                    headers=auth_headers(csrf),
                ).status_code
                == 400
            )
            assert (
                client.patch(
                    f"/api/admin/projects/{pid}/extensions/{ext_id}",
                    json={"enabled": True},
                    headers=auth_headers(csrf),
                ).status_code
                == 400
            )
            assert (
                client.delete(
                    f"/api/admin/projects/{pid}/extensions/{ext_id}",
                    headers=auth_headers(csrf),
                ).status_code
                == 400
            )

        for proj in others.values():
            pid = proj["id"]
            assert (
                client.get(f"/api/admin/projects/{pid}/extensions", headers=auth_headers(csrf)).status_code
                == 400
            )
            assert (
                client.post(
                    f"/api/admin/projects/{pid}/extensions/mascot/install",
                    json={"enabled": True},
                    headers=auth_headers(csrf),
                ).status_code
                == 400
            )
            assert (
                client.patch(
                    f"/api/admin/projects/{pid}/extensions/mascot",
                    json={"enabled": True},
                    headers=auth_headers(csrf),
                ).status_code
                == 400
            )
            assert (
                client.delete(
                    f"/api/admin/projects/{pid}/extensions/mascot",
                    headers=auth_headers(csrf),
                ).status_code
                == 400
            )


def test_builtin_space_and_resume_extensions_validation_and_rendering() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        space = create_app(client, csrf, "space", "星辰作品空间").json()["project"]
        resume = create_app(client, csrf, "resume", "架构师简历").json()["project"]

        space_admin = client.get(f"/admin/projects/{space['id']}")
        assert space_admin.status_code == 200
        assert 'id="space-extensions"' in space_admin.text
        assert "空间外观" not in space_admin.text
        assert "space-theme-section" not in space_admin.text
        assert 'data-ext-install="space_banner"' in space_admin.text
        assert 'data-ext-install="space_background"' in space_admin.text
        assert 'data-ext-install="mascot"' in space_admin.text
        assert 'data-ext-install="post_cover"' not in space_admin.text

        resume_admin = client.get(f"/admin/projects/{resume['id']}")
        assert resume_admin.status_code == 200
        assert 'id="resume-extensions"' in resume_admin.text
        assert 'data-ext-install="resume_style"' in resume_admin.text
        assert 'data-ext-install="space_banner"' not in resume_admin.text

        assert (
            client.post(
                f"/api/admin/projects/{space['id']}/extensions/space_banner/install",
                json={"enabled": True, "config": {"tone": "neon"}},
                headers=auth_headers(csrf),
            ).status_code
            == 422
        )
        assert (
            client.post(
                f"/api/admin/projects/{space['id']}/extensions/space_banner/install",
                json={"enabled": True, "config": {"link_url": "javascript:alert(1)"}},
                headers=auth_headers(csrf),
            ).status_code
            == 422
        )
        assert (
            client.post(
                f"/api/admin/projects/{space['id']}/extensions/space_background/install",
                json={"enabled": True, "config": {"preset": "invalid_preset"}},
                headers=auth_headers(csrf),
            ).status_code
            == 422
        )
        assert (
            client.post(
                f"/api/admin/projects/{space['id']}/extensions/space_background/install",
                json={"enabled": True, "config": {"opacity": 0.99}},
                headers=auth_headers(csrf),
            ).status_code
            == 422
        )
        assert (
            client.post(
                f"/api/admin/projects/{resume['id']}/extensions/resume_style/install",
                json={"enabled": True, "config": {"accent": "rainbow"}},
                headers=auth_headers(csrf),
            ).status_code
            == 422
        )

        assert (
            client.post(
                f"/api/admin/projects/{space['id']}/extensions/space_banner/install",
                json={
                    "enabled": True,
                    "config": {
                        "title": "<b>欢迎公告</b>",
                        "message": "空间持续更新中",
                        "tone": "warm",
                        "link_label": "查看源码",
                        "link_url": "https://example.com/repo",
                        "dismissible": True,
                    },
                },
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert (
            client.post(
                f"/api/admin/projects/{space['id']}/extensions/space_background/install",
                json={
                    "enabled": True,
                    "config": {
                        "preset": "mesh",
                        "opacity": 0.35,
                        "frosted_cards": True,
                    },
                },
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert (
            client.post(
                f"/api/admin/projects/{space['id']}/extensions/mascot/install",
                json={
                    "enabled": True,
                    "config": {
                        "character": "whale",
                        "position": "left",
                        "greeting": "空间看板娘问好",
                    },
                },
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )

        space_page = client.get(f"/projects/{space['slug']}/")
        assert space_page.status_code == 200
        assert "content-security-policy" not in {k.lower() for k in space_page.headers}
        assert "/static/css/ext_space_banner.css" in space_page.text
        assert "/static/js/ext_space_banner.js" in space_page.text
        assert "/static/css/ext_space_background.css" in space_page.text
        assert "/static/css/blog_ext_mascot.css" in space_page.text
        assert "/static/js/blog_ext_mascot.js" in space_page.text
        assert "sf-space-banner-warm" in space_page.text
        assert "&lt;b&gt;欢迎公告&lt;/b&gt;" in space_page.text
        assert "<b>欢迎公告</b>" not in space_page.text
        assert 'rel="noopener noreferrer"' in space_page.text
        assert "has-space-bg" in space_page.text
        assert "space-bg-preset-mesh" in space_page.text
        assert "has-space-bg-frosted" in space_page.text
        assert 'class="sf-mascot-svg sf-mascot-skin-whale"' in space_page.text

        assert (
            client.post(
                f"/api/admin/projects/{resume['id']}/extensions/resume_style/install",
                json={
                    "enabled": True,
                    "config": {
                        "accent": "emerald",
                        "paper": "warm",
                        "density": "compact",
                        "font_style": "serif",
                        "show_section_dividers": False,
                    },
                },
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        resume_page = client.get(f"/projects/{resume['slug']}/")
        assert resume_page.status_code == 200
        assert "style=" not in resume_page.text
        assert "/static/css/ext_resume_style.css" in resume_page.text
        assert "has-resume-style" in resume_page.text
        assert "resume-accent-emerald" in resume_page.text
        assert "resume-paper-warm" in resume_page.text
        assert "resume-density-compact" in resume_page.text
        assert "resume-font-serif" in resume_page.text
        assert "resume-no-dividers" in resume_page.text

        space_obj = Project(id=space["id"], slug=space["slug"], type="space", title="星辰")
        space_bundle = build_render_bundle(
            "space",
            space_obj,
            {
                "extensions": {
                    "space_banner": {"installed": True, "enabled": True, "config": {"title": "测试"}},
                    "space_background": {"installed": True, "enabled": True, "config": {"preset": "dots"}},
                    "mascot": {"installed": True, "enabled": True, "config": {"character": "whale"}},
                }
            },
            target="space",
        )
        for frag in (
            *space_bundle["body_start_fragments"],
            *space_bundle["main_start_fragments"],
            *space_bundle["body_end_fragments"],
        ):
            frag_str = str(frag)
            assert "style=" not in frag_str
            assert "<script>" not in frag_str.lower()
            assert "<script " not in frag_str.lower().replace('<script type="application/json"', "")


def test_space_theme_and_resume_save_preserve_extensions() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        space = create_app(client, csrf, "space", "主题保留空间").json()["project"]
        resume = create_app(client, csrf, "resume", "扩展保留简历").json()["project"]

        assert (
            client.post(
                f"/api/admin/projects/{space['id']}/extensions/space_banner/install",
                json={"enabled": True, "config": {"title": "保留公告"}},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        patched_space = client.patch(
            f"/api/admin/projects/{space['id']}",
            json={"theme": {"accent": "#2563eb", "font_family": "serif", "radius_card": "14px"}},
            headers=auth_headers(csrf),
        )
        assert patched_space.status_code == 200
        space_stored = json.loads(patched_space.json()["project"]["content"])
        assert space_stored["accent"] == "#2563eb"
        assert space_stored["font_family"] == "serif"
        assert space_stored["extensions"]["space_banner"]["config"]["title"] == "保留公告"

        assert (
            client.post(
                f"/api/admin/projects/{resume['id']}/extensions/resume_style/install",
                json={"enabled": True, "config": {"accent": "rose", "density": "compact"}},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        resume_payload = {
            "basics": {
                "name": "林深",
                "label": "系统架构师",
                "email": "lin@example.com",
                "phone": "",
                "url": "",
                "summary": "分布式系统工程",
                "location": {"city": "上海", "region": "", "countryCode": "CN"},
                "profiles": [],
            },
            "work": [],
            "education": [],
            "projects": [],
            "skills": [],
        }
        patched_resume = client.patch(
            f"/api/admin/projects/{resume['id']}",
            json={"content": json.dumps(resume_payload, ensure_ascii=False)},
            headers=auth_headers(csrf),
        )
        assert patched_resume.status_code == 200
        resume_stored = json.loads(patched_resume.json()["project"]["content"])
        assert resume_stored["basics"]["name"] == "林深"
        assert resume_stored["extensions"]["resume_style"]["config"]["accent"] == "rose"
        assert resume_stored["extensions"]["resume_style"]["config"]["density"] == "compact"


def test_unified_ext_media_gates_etag_pv_and_orphan_cleanup() -> None:
    with TestClient(app) as admin_client, TestClient(app) as guest_client:
        csrf = login(admin_client)
        space = create_app(admin_client, csrf, "space", "媒体空间").json()["project"]
        pid, slug = space["id"], space["slug"]

        assert (
            admin_client.post(
                f"/api/admin/projects/{pid}/extensions/space_background/install",
                json={"enabled": True},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )

        up1 = admin_client.post(
            f"/api/admin/projects/{pid}/extensions/space_background/media",
            files={"file": ("bg1.png", make_png(), "image/png")},
            data={"kind": "bg"},
            headers=auth_headers(csrf),
        )
        assert up1.status_code == 200
        url1 = up1.json()["url"]
        assert url1.startswith(f"/media/ext/{slug}/bg-")
        assert url1.endswith(".webp")

        assert (
            admin_client.patch(
                f"/api/admin/projects/{pid}/extensions/space_background",
                json={"config": {"image_url": url1, "preset": "aurora"}},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )

        with store.session() as db:
            pv_before = stats.get_7day_stats(db, project_id=pid)["total_pv_7d"]

        pub_resp = guest_client.get(url1)
        assert pub_resp.status_code == 200
        assert pub_resp.headers["x-content-type-options"] == "nosniff"
        assert pub_resp.headers["content-type"].startswith("image/webp")
        etag = pub_resp.headers["etag"]
        assert guest_client.get(url1, headers={"If-None-Match": etag}).status_code == 304

        with store.session() as db:
            pv_after = stats.get_7day_stats(db, project_id=pid)["total_pv_7d"]
        assert pv_after == pv_before

        assert (
            admin_client.patch(
                f"/api/admin/projects/{pid}",
                json={"visible": False},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert guest_client.get(url1).status_code == 404
        admin_hidden = admin_client.get(url1)
        assert admin_hidden.status_code == 200
        assert "private" in admin_hidden.headers["cache-control"]

        assert (
            admin_client.patch(
                f"/api/admin/projects/{pid}",
                json={"visible": True, "password": "space-secret"},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert guest_client.get(url1).status_code == 401
        assert admin_client.get(url1).status_code == 200

        unlock = guest_client.post(
            f"/projects/{slug}/unlock",
            data={"password": "space-secret"},
            follow_redirects=False,
        )
        assert unlock.status_code == 303
        unlocked_media = guest_client.get(url1)
        assert unlocked_media.status_code == 200
        assert "private" in unlocked_media.headers["cache-control"]

        up2 = admin_client.post(
            f"/api/admin/projects/{pid}/extensions/space_background/media",
            files={"file": ("bg2.png", make_png(), "image/png")},
            data={"kind": "bg"},
            headers=auth_headers(csrf),
        )
        assert up2.status_code == 200
        url2 = up2.json()["url"]
        assert (
            admin_client.patch(
                f"/api/admin/projects/{pid}/extensions/space_background",
                json={"config": {"image_url": url2}},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert admin_client.get(url1).status_code == 404
        assert admin_client.get(url2).status_code == 200

        assert (
            admin_client.delete(
                f"/api/admin/projects/{pid}/extensions/space_background",
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert admin_client.get(url2).status_code == 404

        assert (
            admin_client.post(
                f"/api/admin/projects/{pid}/extensions/space_background/install",
                json={"enabled": True},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        url3 = admin_client.post(
            f"/api/admin/projects/{pid}/extensions/space_background/media",
            files={"file": ("bg3.png", make_png(), "image/png")},
            data={"kind": "bg"},
            headers=auth_headers(csrf),
        ).json()["url"]
        assert (
            admin_client.patch(
                f"/api/admin/projects/{pid}/extensions/space_background",
                json={"config": {"image_url": url3}},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert admin_client.get(url3).status_code == 200
        assert (
            admin_client.delete(
                f"/api/admin/projects/{pid}",
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert admin_client.get(url3).status_code == 404
        media_dir = app.state.config.data / "media" / "ext" / slug
        assert not media_dir.exists()


def test_same_type_instances_isolate_extension_install_config_media_and_client_keys() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        blog_a = create_app(client, csrf, "blog", "独立博客A").json()["project"]
        blog_b = create_app(client, csrf, "blog", "独立博客B").json()["project"]
        space_a = create_app(client, csrf, "space", "独立空间A").json()["project"]
        space_b = create_app(client, csrf, "space", "独立空间B").json()["project"]

        assert (
            client.post(
                f"/api/admin/projects/{blog_a['id']}/extensions/mascot/install",
                json={
                    "enabled": True,
                    "config": {
                        "character": "whale",
                        "greeting": "来自博客A",
                        "api_key": "sk-blog-a-only",
                    },
                },
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert (
            client.post(
                f"/api/admin/projects/{blog_a['id']}/extensions/post_background/install",
                json={"enabled": True, "config": {"preset": "aurora"}},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )

        blog_b_cat = {
            item["id"]: item
            for item in client.get(
                f"/api/admin/projects/{blog_b['id']}/extensions", headers=auth_headers(csrf)
            ).json()["extensions"]
        }
        assert blog_b_cat["mascot"]["installed"] is False
        assert blog_b_cat["mascot"]["enabled"] is False
        assert blog_b_cat["mascot"]["secrets_set"] == {"api_key": False}
        assert blog_b_cat["post_background"]["installed"] is False
        assert blog_b_cat["post_background"]["enabled"] is False

        render_a1 = client.get(f"/projects/{blog_a['slug']}/")
        render_b1 = client.get(f"/projects/{blog_b['slug']}/")
        assert render_a1.status_code == 200
        assert render_b1.status_code == 200
        assert 'class="sf-mascot-svg sf-mascot-skin-whale"' in render_a1.text
        assert "来自博客A" in render_a1.text
        assert "has-blog-bg" in render_a1.text
        assert 'class="sf-mascot-svg sf-mascot-skin-whale"' not in render_b1.text
        assert "来自博客A" not in render_b1.text
        assert "has-blog-bg" not in render_b1.text

        assert (
            client.post(
                f"/api/admin/projects/{blog_b['id']}/extensions/mascot/install",
                json={
                    "enabled": True,
                    "config": {
                        "character": "dog",
                        "greeting": "来自博客B",
                        "api_key": "sk-blog-b-only",
                    },
                },
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )

        render_a2 = client.get(f"/projects/{blog_a['slug']}/")
        render_b2 = client.get(f"/projects/{blog_b['slug']}/")
        assert 'class="sf-mascot-svg sf-mascot-skin-whale"' in render_a2.text
        assert "来自博客A" in render_a2.text
        assert 'class="sf-mascot-svg sf-mascot-skin-dog"' not in render_a2.text
        assert 'class="sf-mascot-svg sf-mascot-skin-dog"' in render_b2.text
        assert "来自博客B" in render_b2.text
        assert 'class="sf-mascot-svg sf-mascot-skin-whale"' not in render_b2.text

        avatar_up = client.post(
            f"/api/admin/projects/{blog_a['id']}/extensions/mascot/media",
            files={"file": ("avatar-a.png", make_png(), "image/png")},
            data={"kind": "avatar"},
            headers=auth_headers(csrf),
        )
        assert avatar_up.status_code == 200
        blog_a_avatar_url = avatar_up.json()["url"]
        assert blog_a_avatar_url.startswith(f"/media/blog/{blog_a['slug']}/")

        cross_media = client.patch(
            f"/api/admin/projects/{blog_b['id']}/extensions/mascot",
            json={"config": {"custom_avatar": blog_a_avatar_url}},
            headers=auth_headers(csrf),
        )
        assert cross_media.status_code == 422

        assert (
            client.delete(
                f"/api/admin/projects/{blog_a['id']}/extensions/mascot",
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        blog_b_after_del = {
            item["id"]: item
            for item in client.get(
                f"/api/admin/projects/{blog_b['id']}/extensions", headers=auth_headers(csrf)
            ).json()["extensions"]
        }
        assert blog_b_after_del["mascot"]["installed"] is True
        assert blog_b_after_del["mascot"]["enabled"] is True
        render_b3 = client.get(f"/projects/{blog_b['slug']}/")
        assert 'class="sf-mascot-svg sf-mascot-skin-dog"' in render_b3.text

        assert (
            client.post(
                f"/api/admin/projects/{space_a['id']}/extensions/space_banner/install",
                json={"enabled": True, "config": {"title": "空间A专属公告"}},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        space_b_cat = {
            item["id"]: item
            for item in client.get(
                f"/api/admin/projects/{space_b['id']}/extensions", headers=auth_headers(csrf)
            ).json()["extensions"]
        }
        assert space_b_cat["space_banner"]["installed"] is False
        space_a_page = client.get(f"/projects/{space_a['slug']}/")
        space_b_page = client.get(f"/projects/{space_b['slug']}/")
        assert "空间A专属公告" in space_a_page.text
        assert "空间A专属公告" not in space_b_page.text

        mascot_js = client.get("/static/js/blog_ext_mascot.js")
        assert mascot_js.status_code == 200
        assert '"sf_mascot_collapsed_" + config.slug' in mascot_js.text
        assert '"sf_mascot_greeted_" + config.slug' in mascot_js.text
        assert '"sf_mascot_pos_" + config.slug' in mascot_js.text
