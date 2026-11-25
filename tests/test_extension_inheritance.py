import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import store
from app.extensions.inheritance import (
    SITE_EXTENSIONS_KEY,
    load_site_extensions,
    parse_layer_state,
    resolve_project_extensions,
)
from app.extensions.registry import active_extensions_for_project, build_render_bundle
from app.main import app
from app.models import Project
from tests.test_apps import create_app
from tests.test_flow import ORIGIN, auth_headers, login
from tests.test_mascot_chat import _patch_upstream
from tests.test_mascot_v2 import _extract_mascot_payload
from tests.test_plugin_packs import _multi_plugin_pack_zip
from tests.test_surface_mascot_resume import _sample_resume_payload

APP_DIR = Path(__file__).resolve().parent.parent / "app"
EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]")


def test_site_settings_helpers_and_legacy_layer_parsing() -> None:
    with store.session() as db:
        assert store.get_site_setting(db, "missing_key") is None
        assert store.get_site_setting(db, "missing_key", "{}") == "{}"
        store.set_site_setting(db, SITE_EXTENSIONS_KEY, json.dumps({"mascot": {"enabled": True}}))
        db.commit()
        assert load_site_extensions(db) == {"mascot": {"enabled": True}}
        store.set_site_setting(db, SITE_EXTENSIONS_KEY, json.dumps({"mascot": {"enabled": False}}))
        db.commit()
        assert load_site_extensions(db) == {"mascot": {"enabled": False}}

    legacy_on = parse_layer_state({"installed": True, "enabled": True, "config": {"theme": "mint"}})
    assert legacy_on.mode == "override"
    assert legacy_on.cascade is False
    assert legacy_on.config == {"theme": "mint"}

    legacy_off = parse_layer_state({"installed": True, "enabled": False, "config": {"theme": "mono"}})
    assert legacy_off.mode == "disabled"
    assert legacy_off.cascade is False

    legacy_uninstalled = parse_layer_state({"installed": False, "enabled": True})
    assert legacy_uninstalled.mode == "inherit"
    assert legacy_uninstalled.config == {}

    missing = parse_layer_state(None)
    assert missing.mode == "inherit"
    assert missing.cascade is False

    site_on = parse_layer_state({"enabled": True, "config": {"character": "whale"}}, is_site=True)
    assert site_on.mode == "override"
    assert site_on.cascade is True


def test_multilevel_inheritance_shallow_merge_and_reset() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        root_space = create_app(client, csrf, "space", "根空间").json()["project"]
        sub_space = create_app(client, csrf, "space", "子空间", parent_id=root_space["id"]).json()["project"]
        leaf_blog = create_app(client, csrf, "blog", "底层博客", parent_id=sub_space["id"]).json()["project"]
        leaf_resume = create_app(client, csrf, "resume", "个人简历", parent_id=sub_space["id"]).json()[
            "project"
        ]

        assert (
            client.put(
                "/api/admin/site/extensions/mascot",
                json={
                    "enabled": True,
                    "config": {
                        "character": "dafeiyu",
                        "theme": "sakura",
                        "position": "left",
                        "greeting": "全站默认问好",
                    },
                },
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert (
            client.put(
                "/api/admin/site/extensions/resume_style",
                json={
                    "enabled": True,
                    "config": {"accent": "emerald", "paper": "warm", "density": "compact"},
                },
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert (
            client.put(
                "/api/admin/site/extensions/post_cover",
                json={"enabled": True, "config": {"aspect_ratio": "21/9"}},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )

        root_cat = {
            item["id"]: item
            for item in client.get(
                f"/api/admin/projects/{root_space['id']}/extensions", headers=auth_headers(csrf)
            ).json()["extensions"]
        }
        assert root_cat["mascot"]["effective_enabled"] is True
        assert root_cat["mascot"]["source"] == "site"
        assert root_cat["mascot"]["source_title"] == "全站默认"
        assert root_cat["mascot"]["local_mode"] == "inherit"
        assert root_cat["mascot"]["inherited_enabled"] is True
        assert root_cat["mascot"]["config"]["character"] == "dafeiyu"
        assert root_cat["mascot"]["config"]["theme"] == "sakura"

        root_page = client.get(f"/projects/{root_space['slug']}/")
        assert root_page.status_code == 200
        assert "sf-mascot-skin-dafeiyu" in root_page.text
        assert "sf-mascot-theme-sakura" in root_page.text
        assert "全站默认问好" in root_page.text

        resume_page = client.get(f"/projects/{leaf_resume['slug']}/")
        assert resume_page.status_code == 200
        assert "resume-accent-emerald" in resume_page.text
        assert "resume-paper-warm" in resume_page.text
        assert "resume-density-compact" in resume_page.text

        sub_override = client.put(
            f"/api/admin/projects/{sub_space['id']}/extensions/mascot",
            json={"mode": "override", "cascade": True, "config": {"theme": "mint"}},
            headers=auth_headers(csrf),
        )
        assert sub_override.status_code == 200
        sub_ext = sub_override.json()["extension"]
        assert sub_ext["local_mode"] == "override"
        assert sub_ext["cascade"] is True
        assert sub_ext["source"] == "local"
        assert sub_ext["config"]["character"] == "dafeiyu"
        assert sub_ext["config"]["theme"] == "mint"
        assert sub_ext["config"]["greeting"] == "全站默认问好"

        blog_cat = {
            item["id"]: item
            for item in client.get(
                f"/api/admin/projects/{leaf_blog['id']}/extensions", headers=auth_headers(csrf)
            ).json()["extensions"]
        }
        assert blog_cat["mascot"]["effective_enabled"] is True
        assert blog_cat["mascot"]["source"] == "ancestor"
        assert blog_cat["mascot"]["source_slug"] == sub_space["slug"]
        assert blog_cat["mascot"]["source_title"] == "子空间"
        assert blog_cat["mascot"]["local_mode"] == "inherit"
        assert blog_cat["mascot"]["inherited_enabled"] is True
        assert blog_cat["mascot"]["inherited_source_title"] == "子空间"
        assert blog_cat["mascot"]["config"]["character"] == "dafeiyu"
        assert blog_cat["mascot"]["config"]["theme"] == "mint"
        assert blog_cat["mascot"]["config"]["position"] == "left"
        assert blog_cat["mascot"]["config"]["greeting"] == "全站默认问好"

        assert blog_cat["post_cover"]["effective_enabled"] is True
        assert blog_cat["post_cover"]["source"] == "site"
        assert blog_cat["post_cover"]["config"]["aspect_ratio"] == "21/9"

        editor_page = client.get(f"/admin/projects/{leaf_blog['id']}/posts/new")
        assert editor_page.status_code == 200
        assert 'name="meta.cover"' in editor_page.text

        blog_page = client.get(f"/projects/{leaf_blog['slug']}/")
        assert blog_page.status_code == 200
        assert "sf-mascot-skin-dafeiyu" in blog_page.text
        assert "sf-mascot-theme-mint" in blog_page.text
        assert "sf-mascot-left" in blog_page.text
        assert "全站默认问好" in blog_page.text

        blog_override = client.put(
            f"/api/admin/projects/{leaf_blog['id']}/extensions/mascot",
            json={"mode": "override", "config": {"greeting": "博客专属问好"}},
            headers=auth_headers(csrf),
        )
        assert blog_override.status_code == 200
        blog_ext = blog_override.json()["extension"]
        assert blog_ext["source"] == "local"
        assert blog_ext["local_mode"] == "override"
        assert blog_ext["config"]["character"] == "dafeiyu"
        assert blog_ext["config"]["theme"] == "mint"
        assert blog_ext["config"]["greeting"] == "博客专属问好"

        blog_page_overridden = client.get(f"/projects/{leaf_blog['slug']}/")
        assert "博客专属问好" in blog_page_overridden.text
        assert "sf-mascot-skin-dafeiyu" in blog_page_overridden.text
        assert "sf-mascot-theme-mint" in blog_page_overridden.text

        blog_reset = client.delete(
            f"/api/admin/projects/{leaf_blog['id']}/extensions/mascot",
            headers=auth_headers(csrf),
        )
        assert blog_reset.status_code == 200
        reset_ext = blog_reset.json()["extension"]
        assert reset_ext["local_mode"] == "inherit"
        assert reset_ext["source"] == "ancestor"
        assert reset_ext["source_title"] == "子空间"
        assert reset_ext["config"]["greeting"] == "全站默认问好"


def test_disabled_blocking_cascade_false_and_legacy_no_bleed() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        parent = create_app(client, csrf, "space", "父级空间").json()["project"]
        child_blog = create_app(client, csrf, "blog", "子博客", parent_id=parent["id"]).json()["project"]
        child_space = create_app(client, csrf, "space", "嵌套空间", parent_id=parent["id"]).json()["project"]

        with store.session() as db:
            row = store.by_id(db, parent["id"])
            assert row is not None
            row.content = json.dumps(
                {
                    "accent": "",
                    "font_family": "",
                    "radius_card": "",
                    "extensions": {
                        "mascot": {
                            "installed": True,
                            "enabled": True,
                            "config": {"character": "whale", "greeting": "旧格式父空间"},
                        }
                    },
                },
                ensure_ascii=False,
            )
            db.commit()

        parent_page = client.get(f"/projects/{parent['slug']}/")
        child_page = client.get(f"/projects/{child_blog['slug']}/")
        assert "sf-mascot-skin-whale" in parent_page.text
        assert "sf-mascot" not in child_page.text

        assert (
            client.put(
                "/api/admin/site/extensions/mascot",
                json={"enabled": True, "config": {"character": "cat", "theme": "indigo"}},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )

        assert (
            client.put(
                f"/api/admin/projects/{parent['id']}/extensions/mascot",
                json={"mode": "disabled", "cascade": False},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert "sf-mascot" not in client.get(f"/projects/{parent['slug']}/").text
        assert "sf-mascot-skin-cat" in client.get(f"/projects/{child_blog['slug']}/").text

        assert (
            client.patch(
                f"/api/admin/projects/{parent['id']}/extensions/mascot",
                json={"cascade": True},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert "sf-mascot" not in client.get(f"/projects/{child_blog['slug']}/").text
        assert "sf-mascot" not in client.get(f"/projects/{child_space['slug']}/").text

        child_cat = {
            item["id"]: item
            for item in client.get(
                f"/api/admin/projects/{child_blog['id']}/extensions", headers=auth_headers(csrf)
            ).json()["extensions"]
        }
        assert child_cat["mascot"]["effective_enabled"] is False
        assert child_cat["mascot"]["inherited_enabled"] is False
        assert child_cat["mascot"]["source"] == "none"

        assert (
            client.put(
                f"/api/admin/projects/{child_blog['id']}/extensions/mascot",
                json={"mode": "override", "config": {"character": "dog"}},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert "sf-mascot-skin-dog" in client.get(f"/projects/{child_blog['slug']}/").text

        assert (
            client.put(
                f"/api/admin/projects/{parent['id']}/extensions/mascot",
                json={"mode": "override", "cascade": False, "config": {"character": "slime"}},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert "sf-mascot-skin-slime" in client.get(f"/projects/{parent['slug']}/").text
        assert "sf-mascot-skin-cat" in client.get(f"/projects/{child_space['slug']}/").text

        assert (
            client.put(
                f"/api/admin/projects/{child_space['id']}/extensions/mascot",
                json={"mode": "disabled"},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert "sf-mascot" not in client.get(f"/projects/{child_space['slug']}/").text


def test_secret_inheritance_never_leaks_and_powers_mascot_chat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site_secret = "sk-site-super-secret-001"
    child_secret = "sk-child-override-secret-002"
    with TestClient(app) as client:
        csrf = login(client)
        parent = create_app(client, csrf, "space", "AI 空间").json()["project"]
        blog = create_app(client, csrf, "blog", "AI 博客", parent_id=parent["id"]).json()["project"]

        put_site = client.put(
            "/api/admin/site/extensions/mascot",
            json={
                "enabled": True,
                "config": {
                    "character": "dafeiyu",
                    "chat_access": "public",
                    "api_base_url": "https://api.deepseek.com",
                    "api_key": site_secret,
                    "model": "deepseek-chat",
                    "rate_limit_per_min": 60,
                },
            },
            headers=auth_headers(csrf),
        )
        assert put_site.status_code == 200
        assert site_secret not in put_site.text
        assert put_site.json()["extension"]["config"]["api_key"] == ""
        assert put_site.json()["extension"]["secrets_set"] == {"api_key": True}

        site_list = client.get("/api/admin/site/extensions", headers=auth_headers(csrf))
        assert site_list.status_code == 200
        assert site_secret not in site_list.text

        admin_home = client.get("/admin")
        assert admin_home.status_code == 200
        assert site_secret not in admin_home.text
        assert 'id="site-ext-dialog"' in admin_home.text
        assert 'id="site-ext-open-btn"' in admin_home.text

        blog_exts_resp = client.get(
            f"/api/admin/projects/{blog['id']}/extensions", headers=auth_headers(csrf)
        )
        assert blog_exts_resp.status_code == 200
        assert site_secret not in blog_exts_resp.text
        mascot_item = next(e for e in blog_exts_resp.json()["extensions"] if e["id"] == "mascot")
        assert mascot_item["config"]["api_key"] == ""
        assert mascot_item["secrets_set"] == {"api_key": True}
        assert mascot_item["secret_inherited"] == {"api_key": True}
        assert mascot_item["local_secrets_set"] == {"api_key": False}

        blog_admin = client.get(f"/admin/projects/{blog['id']}")
        assert blog_admin.status_code == 200
        assert site_secret not in blog_admin.text
        assert "继承自全站" in blog_admin.text

        blog_pub = client.get(f"/projects/{blog['slug']}/")
        assert blog_pub.status_code == 200
        assert site_secret not in blog_pub.text
        assert '"chat_enabled": true' in blog_pub.text

        chat_url = f"/api/projects/{blog['slug']}/mascot/chat"
        captured = _patch_upstream(monkeypatch)
        chat_resp = client.post(
            chat_url,
            json={"messages": [{"role": "user", "content": "测试继承密钥"}]},
            headers=ORIGIN,
        )
        assert chat_resp.status_code == 200
        assert len(captured) == 1
        assert captured[0]["headers"]["x-api-key"] == site_secret
        assert captured[0]["json"]["model"] == "deepseek-chat"

        override_model = client.put(
            f"/api/admin/projects/{blog['id']}/extensions/mascot",
            json={"mode": "override", "config": {"model": "deepseek-flash"}},
            headers=auth_headers(csrf),
        )
        assert override_model.status_code == 200
        assert site_secret not in override_model.text
        assert override_model.json()["extension"]["secrets_set"] == {"api_key": True}
        assert override_model.json()["extension"]["secret_inherited"] == {"api_key": True}

        captured2 = _patch_upstream(monkeypatch)
        chat_resp2 = client.post(
            chat_url,
            json={"messages": [{"role": "user", "content": "浅合并模型但保留上级密钥"}]},
            headers=ORIGIN,
        )
        assert chat_resp2.status_code == 200
        assert captured2[0]["headers"]["x-api-key"] == site_secret
        assert captured2[0]["json"]["model"] == "deepseek-flash"

        override_secret = client.put(
            f"/api/admin/projects/{blog['id']}/extensions/mascot",
            json={"mode": "override", "config": {"api_key": child_secret}},
            headers=auth_headers(csrf),
        )
        assert override_secret.status_code == 200
        assert child_secret not in override_secret.text
        assert override_secret.json()["extension"]["secrets_set"] == {"api_key": True}
        assert override_secret.json()["extension"]["secret_inherited"] == {"api_key": False}
        assert override_secret.json()["extension"]["local_secrets_set"] == {"api_key": True}

        captured3 = _patch_upstream(monkeypatch)
        chat_resp3 = client.post(
            chat_url,
            json={"messages": [{"role": "user", "content": "本层密钥覆盖"}]},
            headers=ORIGIN,
        )
        assert chat_resp3.status_code == 200
        assert captured3[0]["headers"]["x-api-key"] == child_secret

        cleared_local = client.patch(
            f"/api/admin/projects/{blog['id']}/extensions/mascot",
            json={"config": {"clear_api_key": True}},
            headers=auth_headers(csrf),
        )
        assert cleared_local.status_code == 200
        assert cleared_local.json()["extension"]["secrets_set"] == {"api_key": True}
        assert cleared_local.json()["extension"]["secret_inherited"] == {"api_key": True}
        assert cleared_local.json()["extension"]["local_secrets_set"] == {"api_key": False}

        captured4 = _patch_upstream(monkeypatch)
        chat_resp4 = client.post(
            chat_url,
            json={"messages": [{"role": "user", "content": "清除本地后回退全站密钥"}]},
            headers=ORIGIN,
        )
        assert chat_resp4.status_code == 200
        assert captured4[0]["headers"]["x-api-key"] == site_secret

        assert (
            client.put(
                f"/api/admin/projects/{blog['id']}/extensions/mascot",
                json={"mode": "disabled"},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert (
            client.post(
                chat_url,
                json={"messages": [{"role": "user", "content": "关闭后不可对话"}]},
                headers=ORIGIN,
            ).status_code
            == 404
        )

        site_keep = client.put(
            "/api/admin/site/extensions/mascot",
            json={"config": {"greeting": "保留密钥更新", "api_key": ""}},
            headers=auth_headers(csrf),
        )
        assert site_keep.status_code == 200
        assert site_keep.json()["extension"]["secrets_set"] == {"api_key": True}

        site_clear = client.put(
            "/api/admin/site/extensions/mascot",
            json={"config": {"clear_api_key": True}},
            headers=auth_headers(csrf),
        )
        assert site_clear.status_code == 200
        assert site_clear.json()["extension"]["secrets_set"] == {"api_key": False}


def test_site_extensions_api_auth_csrf_origin_validation_and_pack_cleanup() -> None:
    token = app.state.config.api_token
    bearer = {"Authorization": f"Bearer {token}"}

    with TestClient(app) as client:
        assert client.get("/api/admin/site/extensions").status_code == 401
        assert client.put("/api/admin/site/extensions/mascot", json={"enabled": True}).status_code == 401
        assert client.delete("/api/admin/site/extensions/mascot").status_code == 401

        csrf = login(client)
        assert client.get("/api/admin/site/extensions").status_code == 403
        assert (
            client.put(
                "/api/admin/site/extensions/mascot",
                json={"enabled": True},
                headers=ORIGIN,
            ).status_code
            == 403
        )
        assert client.delete("/api/admin/site/extensions/mascot", headers=ORIGIN).status_code == 403

        foreign = {**auth_headers(csrf), "Origin": "https://evil.example"}
        assert client.get("/api/admin/site/extensions", headers=foreign).status_code == 403
        assert (
            client.put(
                "/api/admin/site/extensions/mascot",
                json={"enabled": True},
                headers=foreign,
            ).status_code
            == 403
        )
        assert client.delete("/api/admin/site/extensions/mascot", headers=foreign).status_code == 403

        assert (
            client.put(
                "/api/admin/site/extensions/nonexistent",
                json={"enabled": True},
                headers=auth_headers(csrf),
            ).status_code
            == 404
        )
        assert (
            client.delete(
                "/api/admin/site/extensions/nonexistent",
                headers=auth_headers(csrf),
            ).status_code
            == 404
        )
        assert (
            client.put(
                "/api/admin/site/extensions/mascot",
                json={"mode": "invalid_mode"},
                headers=auth_headers(csrf),
            ).status_code
            == 422
        )
        assert (
            client.put(
                "/api/admin/site/extensions/mascot",
                json={
                    "enabled": True,
                    "config": {"custom_avatar": "/media/blog/other/avatar-0123456789abcdef.webp"},
                },
                headers=auth_headers(csrf),
            ).status_code
            == 422
        )

        bearer_put = client.put(
            "/api/admin/site/extensions/space_banner",
            json={"enabled": True, "config": {"title": "Bearer 公告"}},
            headers=bearer,
        )
        assert bearer_put.status_code == 200
        assert bearer_put.json()["extension"]["enabled"] is True

        bearer_get = client.get("/api/admin/site/extensions", headers=bearer)
        assert bearer_get.status_code == 200
        banner_item = next(e for e in bearer_get.json()["extensions"] if e["id"] == "space_banner")
        assert banner_item["enabled"] is True
        assert banner_item["config"]["title"] == "Bearer 公告"

        bearer_del = client.delete("/api/admin/site/extensions/space_banner", headers=bearer)
        assert bearer_del.status_code == 200
        assert bearer_del.json()["extension"]["configured"] is False
        assert bearer_del.json()["extension"]["enabled"] is False

        pack_zip = _multi_plugin_pack_zip()
        up = client.post(
            "/api/admin/plugin-packs/upload",
            files={"file": ("siteflow-plugins.zip", pack_zip, "application/zip")},
            data={"replace": "true"},
            headers=auth_headers(csrf),
        )
        assert up.status_code == 200
        assert (
            client.put(
                "/api/admin/site/extensions/siteflow-plugins.reading_progress",
                json={"enabled": True},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert (
            client.delete(
                "/api/admin/plugin-packs/siteflow-plugins",
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        with store.session() as db:
            assert "siteflow-plugins.reading_progress" not in load_site_extensions(db)


def test_registry_resolve_helpers_and_no_db_backward_compat() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        parent = create_app(client, csrf, "space", "工具空间").json()["project"]
        blog = create_app(client, csrf, "blog", "工具博客", parent_id=parent["id"]).json()["project"]
        assert (
            client.put(
                "/api/admin/site/extensions/mascot",
                json={"enabled": True, "config": {"character": "whale"}},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        with store.session() as db:
            blog_row = store.by_id(db, blog["id"])
            assert blog_row is not None
            resolved = resolve_project_extensions(db, blog_row, target="blog", config=app.state.config)
            assert resolved["mascot"].effective_enabled is True
            assert resolved["mascot"].source == "site"
            active_with_db = active_extensions_for_project(
                db, blog_row, target="blog", config=app.state.config
            )
            assert [ext.id for ext, _ in active_with_db] == ["mascot"]
            bundle_with_db = build_render_bundle(
                "list",
                blog_row,
                {"title": "工具博客", "posts": []},
                target="blog",
                config=app.state.config,
                db=db,
            )
            assert "has-mascot" in bundle_with_db["body_classes"]

        standalone = Project(id=999, slug="standalone", type="blog", title="无DB")
        bundle_no_db = build_render_bundle(
            "list",
            standalone,
            {"title": "无DB", "posts": [], "extensions": {"mascot": {"mode": "override", "config": {}}}},
            target="blog",
        )
        assert "has-mascot" in bundle_no_db["body_classes"]


def test_i18n_key_parity_and_ui_badge_rendering() -> None:
    i18n_path = APP_DIR / "static" / "js" / "i18n.js"
    check_script = (
        "const fs=require('fs'),vm=require('vm');"
        f"const code=fs.readFileSync({json.dumps(str(i18n_path))},'utf8');"
        "const m=code.match(/var DICT = (\\{[\\s\\S]*?\\n  \\});/);"
        "const dict=vm.runInNewContext('('+m[1]+')');"
        "const zh=Object.keys(dict.zh).sort(),en=Object.keys(dict.en).sort();"
        "const onlyZh=zh.filter(k=>!dict.en.hasOwnProperty(k));"
        "const onlyEn=en.filter(k=>!dict.zh.hasOwnProperty(k));"
        "console.log(JSON.stringify({zhCount:zh.length,enCount:en.length,onlyZh,onlyEn}));"
    )
    proc = subprocess.run(["node", "-e", check_script], capture_output=True, text=True, check=True)
    report: dict[str, Any] = json.loads(proc.stdout)
    assert report["onlyZh"] == []
    assert report["onlyEn"] == []
    assert report["zhCount"] == report["enCount"]

    for rel in (
        "templates/admin.html",
        "templates/_extensions_panel.html",
        "static/js/admin_ui.js",
        "static/js/extensions_admin.js",
        "extensions/inheritance.py",
    ):
        text = (APP_DIR / rel).read_text(encoding="utf-8")
        assert not EMOJI_RE.findall(text), rel

    with TestClient(app) as client:
        csrf = login(client)
        parent = create_app(client, csrf, "space", "设计系统空间").json()["project"]
        child = create_app(client, csrf, "space", "子组件空间", parent_id=parent["id"]).json()["project"]
        blog = create_app(client, csrf, "blog", "技术博客", parent_id=child["id"]).json()["project"]
        resume = create_app(client, csrf, "resume", "个人简历", parent_id=child["id"]).json()["project"]
        bottle = create_app(client, csrf, "bottle", "海边漂流瓶", parent_id=child["id"]).json()["project"]

        assert (
            client.put(
                f"/api/admin/projects/{parent['id']}/extensions/mascot",
                json={"mode": "override", "cascade": True, "config": {"character": "dafeiyu"}},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        parent_html = client.get(f"/admin/projects/{parent['id']}").text
        assert "ext-count-pill" not in parent_html
        assert "ext-section-desc" not in parent_html
        assert "ext-panel-status" not in parent_html
        assert "本层覆盖" not in parent_html
        assert "恢复继承" not in parent_html
        assert "已启用" in parent_html
        assert "恢复默认" in parent_html
        assert 'aria-disabled="true"' in parent_html
        assert 'data-ext-cascade="mascot"' in parent_html
        assert 'data-ext-mode="inherit"' in parent_html
        assert 'data-ext-mode="override"' in parent_html
        assert 'data-ext-mode="disabled"' in parent_html
        assert ">继承<" in parent_html
        assert ">启用<" in parent_html
        assert ">关闭<" in parent_html
        assert "admin_ui.js" in parent_html

        child_html = client.get(f"/admin/projects/{child['id']}").text
        assert "继承自 设计系统空间" in child_html
        assert 'data-ext-mode="inherit"' in child_html
        assert 'data-ext-mode="override"' in child_html
        assert 'data-ext-mode="disabled"' in child_html
        assert "ext-count-pill" not in child_html
        assert "ext-section-desc" not in child_html

        admin_html = client.get("/admin").text
        assert "site-ext-dialog-sub" not in admin_html
        assert "admin_ui.js" in admin_html
        assert 'data-i18n-hover-tip="ext.site_section_desc"' in admin_html

        blog_html = client.get(f"/admin/projects/{blog['id']}").text
        assert "ext-count-pill" not in blog_html
        assert "admin_ui.js" in blog_html
        editor_html = client.get(f"/admin/projects/{blog['id']}/posts/new").text
        assert "正文（Markdown）" not in editor_html
        assert 'data-i18n-hover-tip="blog.col_body_help"' in editor_html
        assert "admin_ui.js" in editor_html

        resume_html = client.get(f"/admin/projects/{resume['id']}").text
        assert "ai-vis-hint" not in resume_html
        assert "联系方式对 AI 可见（邮箱 / 电话）" not in resume_html
        assert "链接（每行一条" not in resume_html
        assert "要点（每行一条）" not in resume_html
        assert "关键词（逗号分隔）" not in resume_html
        assert 'data-i18n-hover-tip="resume.ai_privacy_hint"' in resume_html
        assert "admin_ui.js" in resume_html

        bottle_html = client.get(f"/admin/projects/{bottle['id']}").text
        assert "bottle-admin-sub" not in bottle_html
        assert "单条字数上限（" not in bottle_html
        assert "先审后发（" not in bottle_html
        assert "投一捞一（" not in bottle_html
        assert "允许包含网址或链接（" not in bottle_html
        assert 'data-i18n-hover-tip="bottle.admin_queue_desc"' in bottle_html
        assert "admin_ui.js" in bottle_html

        mascot_cat = next(
            e
            for e in client.get("/api/admin/site/extensions", headers=auth_headers(csrf)).json()["extensions"]
            if e["id"] == "mascot"
        )
        for field in mascot_cat["config_schema"]:
            label = str(field["label_default"])
            for forbidden in (
                "Thinking",
                "deepseek_web_search",
                "deepseek_read_url",
                "safety_check",
                "（title）",
                "（人设）",
                "（可选）",
                "（每行一条）",
            ):
                assert forbidden not in label, (field["key"], label)
            for opt in field.get("options", []):
                opt_label = str(opt["label_default"])
                assert "Q版" not in opt_label, opt_label
                assert "（high" not in opt_label, opt_label
                assert "（low" not in opt_label, opt_label
        assert "CDN" not in mascot_cat["description"]


def test_capability_matched_site_inheritance_and_resume_mascot_privacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inh_source = (APP_DIR / "extensions" / "inheritance.py").read_text(encoding="utf-8")
    for literal in ('"blog"', "'blog'", '"space"', "'space'", '"resume"', "'resume'"):
        assert literal not in inh_source

    site_secret = "sk-site-cap-secret-999"
    with TestClient(app) as admin_client, TestClient(app) as guest_client:
        csrf = login(admin_client)
        root_space = create_app(admin_client, csrf, "space", "能力根空间").json()["project"]
        sub_space = create_app(admin_client, csrf, "space", "能力子空间", parent_id=root_space["id"]).json()[
            "project"
        ]
        blog = create_app(admin_client, csrf, "blog", "能力博客", parent_id=sub_space["id"]).json()["project"]
        resume = create_app(admin_client, csrf, "resume", "能力简历", parent_id=sub_space["id"]).json()[
            "project"
        ]

        assert (
            admin_client.patch(
                f"/api/admin/projects/{resume['id']}",
                json={"content": json.dumps(_sample_resume_payload(), ensure_ascii=False)},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )

        for ext_id, cfg in (
            (
                "mascot",
                {
                    "character": "dafeiyu",
                    "chat_access": "public",
                    "api_key": site_secret,
                    "rate_limit_per_min": 60,
                },
            ),
            ("space_layout", {"mode": "polaroid", "card_tilt": "playful"}),
            ("post_cover", {"aspect_ratio": "16/9"}),
            ("resume_style", {"accent": "emerald"}),
        ):
            assert (
                admin_client.put(
                    f"/api/admin/site/extensions/{ext_id}",
                    json={"enabled": True, "config": cfg},
                    headers=auth_headers(csrf),
                ).status_code
                == 200
            )

        sub_cat = {
            e["id"]: e
            for e in admin_client.get(
                f"/api/admin/projects/{sub_space['id']}/extensions", headers=auth_headers(csrf)
            ).json()["extensions"]
        }
        assert set(sub_cat.keys()) == {"mascot", "space_banner", "space_background", "space_layout"}
        assert sub_cat["space_layout"]["effective_enabled"] is True
        assert sub_cat["space_layout"]["source"] == "site"
        assert sub_cat["mascot"]["effective_enabled"] is True
        assert sub_cat["mascot"]["source"] == "site"

        space_html = guest_client.get(f"/projects/{sub_space['slug']}/").text
        assert "space-layout-polaroid" in space_html
        assert "space-tilt-playful" in space_html
        assert "sf-mascot-skin-dafeiyu" in space_html

        blog_cat = {
            e["id"]: e
            for e in admin_client.get(
                f"/api/admin/projects/{blog['id']}/extensions", headers=auth_headers(csrf)
            ).json()["extensions"]
        }
        assert set(blog_cat.keys()) == {"post_cover", "post_background", "mascot"}
        assert blog_cat["post_cover"]["effective_enabled"] is True
        assert blog_cat["mascot"]["effective_enabled"] is True

        blog_html = guest_client.get(f"/projects/{blog['slug']}/").text
        assert "sf-mascot-skin-dafeiyu" in blog_html
        assert "space-layout-polaroid" not in blog_html
        assert "has-space-layout" not in blog_html

        resume_cat = {
            e["id"]: e
            for e in admin_client.get(
                f"/api/admin/projects/{resume['id']}/extensions", headers=auth_headers(csrf)
            ).json()["extensions"]
        }
        assert set(resume_cat.keys()) == {"mascot", "resume_style"}
        assert resume_cat["mascot"]["effective_enabled"] is True
        assert resume_cat["mascot"]["source"] == "site"
        assert resume_cat["mascot"]["secret_inherited"] == {"api_key": True}
        assert resume_cat["resume_style"]["effective_enabled"] is True
        assert resume_cat["resume_style"]["source"] == "site"

        resume_html = guest_client.get(f"/projects/{resume['slug']}/").text
        assert "resume-accent-emerald" in resume_html
        assert "sf-mascot-skin-dafeiyu" in resume_html
        assert "space-layout-polaroid" not in resume_html
        assert site_secret not in resume_html
        mascot_payload = _extract_mascot_payload(resume_html)
        assert mascot_payload["page"] == "resume"
        assert mascot_payload["chat_enabled"] is True
        assert "简历" in str(mascot_payload["greeting"])

        captured = _patch_upstream(monkeypatch)
        chat_resp = guest_client.post(
            f"/api/projects/{resume['slug']}/mascot/chat",
            json={"messages": [{"role": "user", "content": "介绍候选人经历与联系方式"}]},
            headers=ORIGIN,
        )
        assert chat_resp.status_code == 200
        assert len(captured) == 1
        assert captured[0]["headers"]["x-api-key"] == site_secret
        sys_prompt = captured[0]["json"]["system"]
        assert "简历" in sys_prompt
        assert "绝不编造" in sys_prompt
        assert "星云科技" in sys_prompt
        assert "Kubernetes" in sys_prompt
        assert "secret-lin@example.com" not in sys_prompt
        assert "138-0013-8000" not in sys_prompt
        assert "秘密城市上海" not in sys_prompt

        with store.session() as db:
            music_proj = Project(id=888, slug="radio", type="music", title="电台")
            resolved_music = resolve_project_extensions(
                db,
                music_proj,
                capabilities=frozenset({"has_content", "has_items"}),
                config=app.state.config,
            )
            assert list(resolved_music.keys()) == ["mascot"]
            assert resolved_music["mascot"].effective_enabled is True
            assert resolved_music["mascot"].source == "site"
            assert resolved_music["mascot"].effective_config["api_key"] == site_secret
