import io
import json
import subprocess
import zipfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from markupsafe import Markup

from app.extensions.base import (
    BaseExtension,
    PageKind,
    SlotKind,
    StructuredSlotKind,
    sanitize_icon_overrides,
    sanitize_theme_tokens,
)
from app.extensions.registry import build_render_bundle, register
from app.main import app
from app.models import Project
from app.plugins.base import InvalidContent
from tests.test_apps import create_app
from tests.test_flow import auth_headers, login

SIBLING_PLUGINS_REPO = Path(__file__).resolve().parent.parent.parent / "siteflow-plugins"


def _make_pack_zip(
    pack_id: str,
    plugin_id: str,
    plugin_manifest: dict[str, Any],
    assets: dict[str, bytes] | None = None,
) -> bytes:
    pack_manifest = {
        "schema_version": 1,
        "id": pack_id,
        "name": f"Pack {pack_id}",
        "version": "1.0.0",
        "plugins": [f"plugins/{plugin_id}"],
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("siteflow-pack.json", json.dumps(pack_manifest, ensure_ascii=False))
        zf.writestr(
            f"plugins/{plugin_id}/plugin.json",
            json.dumps(plugin_manifest, ensure_ascii=False),
        )
        for rel, data in (assets or {}).items():
            zf.writestr(f"plugins/{plugin_id}/assets/{rel}", data)
    return buf.getvalue()


def _zip_real_pack(root: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            if rel.startswith(".git/") or rel == ".git" or "/.git/" in rel:
                continue
            zf.writestr(f"siteflow-plugins-main/{rel}", path.read_bytes())
    return buf.getvalue()


def test_theme_tokens_whitelist_and_css_injection_blocked() -> None:
    valid = sanitize_theme_tokens(
        {
            "--accent": "#3b82f6",
            "--accent-soft": "rgba(59, 130, 246, 0.12)",
            "--bg": "#f2f8ff",
            "--surface": "#ffffff",
            "--text": "#0c2444",
            "--muted": "#4a6b8c",
            "--border": "#cde0f7",
            "--radius-card": "18px",
            "--font-family": '"PingFang SC", sans-serif',
        },
        strict=True,
    )
    assert valid["--accent"] == "#3b82f6"
    assert valid["--radius-card"] == "18px"
    assert valid["--font-family"] == "PingFang SC, sans-serif"

    malicious_payloads = [
        {"--accent": "#fff; } body { display: none; }"},
        {"--accent": "red}</style><script>alert(1)</script>"},
        {"--bg": "url(javascript:alert(1))"},
        {"--bg": "expression(alert(1))"},
        {"--surface": "#fff; @import url(https://evil.example/a.css)"},
        {"--radius-card": "12px; color: red"},
        {"--font-family": "Arial; } body { background: red"},
        {"--not-in-whitelist": "#123456"},
        {"background-image": "url(https://evil.example/a.png)"},
    ]
    for payload in malicious_payloads:
        assert sanitize_theme_tokens(payload, strict=False) == {}
        with pytest.raises(InvalidContent):
            sanitize_theme_tokens(payload, strict=True)

    with TestClient(app) as client:
        csrf = login(client)
        bad_zip = _make_pack_zip(
            "bad-tokens-pack",
            "evil_theme",
            {
                "schema_version": 1,
                "id": "evil_theme",
                "name": "恶意主题",
                "version": "1.0.0",
                "targets": ["space"],
                "slot": "none",
                "tokens": {"--accent": "#fff; } </style><script>alert(1)</script>"},
            },
        )
        res = client.post(
            "/api/admin/plugin-packs/upload",
            files={"file": ("bad.zip", bad_zip, "application/zip")},
            headers=auth_headers(csrf),
        )
        assert res.status_code == 422


def test_icon_overrides_traversal_blocked_and_valid_accepted() -> None:
    valid = sanitize_icon_overrides(
        {
            "layers": "/media/plugins/demo-pack/ocean_theme/icons/layers.svg?v=1234abcd",
            "book-open": "/static/img/book.svg",
            "mail": "/media/plugins/demo-pack/ocean_theme/mail.svg",
        },
        strict=True,
    )
    assert len(valid) == 3

    malicious_icons = [
        {"layers": "/media/plugins/demo-pack/ocean_theme/../../etc/passwd.svg"},
        {"layers": "../secret.svg"},
        {"layers": "https://evil.example/icon.svg"},
        {"layers": "javascript:alert(1)"},
        {"layers": "data:image/svg+xml,<svg/>"},
        {"layers": "/media/plugins/demo-pack/ocean_theme/icon.png"},
        {"layers": "/media/plugins/demo-pack/ocean_theme/icon.svg?evil=1"},
        {"unknown-icon": "/static/img/icon.svg"},
    ]
    for payload in malicious_icons:
        assert sanitize_icon_overrides(payload, strict=False) == {}
        with pytest.raises(InvalidContent):
            sanitize_icon_overrides(payload, strict=True)

    with TestClient(app) as client:
        csrf = login(client)
        traversal_zip = _make_pack_zip(
            "bad-icon-pack",
            "bad_icon",
            {
                "schema_version": 1,
                "id": "bad_icon",
                "name": "越界图标插件",
                "version": "1.0.0",
                "targets": ["space"],
                "slot": "none",
                "icon_overrides": {"layers": "../outside.svg"},
            },
            assets={"icons/layers.svg": b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"/>'},
        )
        res_trav = client.post(
            "/api/admin/plugin-packs/upload",
            files={"file": ("trav.zip", traversal_zip, "application/zip")},
            headers=auth_headers(csrf),
        )
        assert res_trav.status_code == 422

        xss_svg_zip = _make_pack_zip(
            "xss-icon-pack",
            "xss_icon",
            {
                "schema_version": 1,
                "id": "xss_icon",
                "name": "恶意SVG图标插件",
                "version": "1.0.0",
                "targets": ["space"],
                "slot": "none",
                "icon_overrides": {"layers": "assets/icons/layers.svg"},
            },
            assets={
                "icons/layers.svg": b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
            },
        )
        res_xss = client.post(
            "/api/admin/plugin-packs/upload",
            files={"file": ("xss.zip", xss_svg_zip, "application/zip")},
            headers=auth_headers(csrf),
        )
        assert res_xss.status_code == 422


def test_structured_slots_and_hooks_on_custom_extension(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.extensions import registry as reg_mod

    class _DemoSlotExt(BaseExtension):
        id = "demo_slots_ext"
        targets = ("space",)
        name = "Demo Slots"

        def theme_tokens(self, page: PageKind, config: dict[str, Any]) -> dict[str, str]:
            return {
                "--accent": "#0ea5e9",
                "--bg": "url(javascript:alert(1))",
            }

        def icon_overrides(self, page: PageKind, config: dict[str, Any]) -> dict[str, str]:
            return {
                "layers": "/static/img/custom-layers.svg",
                "mail": "https://evil.example/mail.svg",
            }

        def layout_mode(self, page: PageKind, config: dict[str, Any]) -> str | None:
            return "polaroid"

        def inject_slot(
            self,
            slot: StructuredSlotKind | SlotKind,
            page: PageKind,
            project: Project,
            content: dict[str, Any],
            config: dict[str, Any],
            context: dict[str, Any],
        ) -> Markup:
            if slot == "title_deco":
                return Markup('<span class="demo-title-deco">★</span>')
            if slot == "footer":
                return Markup('<span class="demo-footer-note">OK</span>')
            return super().inject_slot(slot, page, project, content, config, context)

    monkeypatch.setitem(reg_mod._builtins, "_keep_clean_sentinel", _DemoSlotExt())
    monkeypatch.delitem(reg_mod._builtins, "_keep_clean_sentinel")
    original = dict(reg_mod._builtins)
    try:
        register(_DemoSlotExt())
        dummy_proj = Project(slug="demo-space", title="Demo Space", type="space")
        bundle = build_render_bundle(
            "space",
            dummy_proj,
            {"extensions": {"demo_slots_ext": {"installed": True, "enabled": True, "config": {}}}},
            target="space",
        )
        assert set(bundle["slots"].keys()) == {"header", "aside", "overlay", "footer", "title_deco", "icons"}
        assert '<span class="demo-title-deco">★</span>' in str(bundle["slots"]["title_deco"][0])
        assert '<span class="demo-footer-note">OK</span>' in str(bundle["slots"]["footer"][0])
        assert bundle["tokens"] == {"--accent": "#0ea5e9"}
        assert bundle["icon_overrides"] == {"layers": "/static/img/custom-layers.svg"}
        assert bundle["layout"] == "polaroid"
        assert "body_start_fragments" in bundle
        assert "main_start_fragments" in bundle
        assert "body_end_fragments" in bundle
    finally:
        reg_mod._builtins.clear()
        reg_mod._builtins.update(original)


def test_space_layout_four_modes_validation_and_rendering() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        space = create_app(client, csrf, "space", "排布测试空间").json()["project"]
        blog = create_app(client, csrf, "blog", "普通博客").json()["project"]
        create_app(client, csrf, "blog", "子博客", parent_id=space["id"])
        create_app(client, csrf, "resume", "子简历", parent_id=space["id"])

        assert (
            client.post(
                f"/api/admin/projects/{blog['id']}/extensions/space_layout/install",
                json={"enabled": True, "config": {"mode": "polaroid"}},
                headers=auth_headers(csrf),
            ).status_code
            == 400
        )

        assert (
            client.post(
                f"/api/admin/projects/{space['id']}/extensions/space_layout/install",
                json={"enabled": True, "config": {"mode": "carousel_3d"}},
                headers=auth_headers(csrf),
            ).status_code
            == 422
        )
        assert (
            client.post(
                f"/api/admin/projects/{space['id']}/extensions/space_layout/install",
                json={"enabled": True, "config": {"card_tilt": "extreme"}},
                headers=auth_headers(csrf),
            ).status_code
            == 422
        )

        install = client.post(
            f"/api/admin/projects/{space['id']}/extensions/space_layout/install",
            json={
                "enabled": True,
                "config": {"mode": "grid", "card_tilt": "none", "show_desk_controls": True},
            },
            headers=auth_headers(csrf),
        )
        assert install.status_code == 200

        for mode, tilt, expect_desk_bar in (
            ("grid", "none", False),
            ("masonry", "subtle", False),
            ("polaroid", "playful", False),
            ("desk", "medium", True),
        ):
            patch = client.patch(
                f"/api/admin/projects/{space['id']}/extensions/space_layout",
                json={
                    "enabled": True,
                    "config": {
                        "mode": mode,
                        "card_tilt": tilt,
                        "show_desk_controls": True,
                    },
                },
                headers=auth_headers(csrf),
            )
            assert patch.status_code == 200
            page = client.get(f"/projects/{space['slug']}/")
            assert page.status_code == 200
            assert f"space-layout-{mode}" in page.text
            assert f"space-tilt-{tilt}" in page.text
            assert f'data-space-layout="{mode}"' in page.text
            assert "/static/css/ext_space_layout.css" in page.text
            assert "/static/js/ext_space_layout.js" in page.text
            if expect_desk_bar:
                assert "data-space-desk-bar" in page.text
                assert "data-desk-shuffle" in page.text
                assert "data-desk-reset" in page.text
                assert 'aria-live="polite"' in page.text
            else:
                assert "data-space-desk-bar" not in page.text

        hide_ctrl = client.patch(
            f"/api/admin/projects/{space['id']}/extensions/space_layout",
            json={
                "enabled": True,
                "config": {"mode": "desk", "card_tilt": "medium", "show_desk_controls": False},
            },
            headers=auth_headers(csrf),
        )
        assert hide_ctrl.status_code == 200
        desk_no_btn = client.get(f"/projects/{space['slug']}/")
        assert desk_no_btn.status_code == 200
        assert "is-controls-hidden" in desk_no_btn.text
        assert "data-desk-shuffle" not in desk_no_btn.text
        assert 'aria-live="polite"' in desk_no_btn.text


def _in_memory_dafeiyu_pack_zip() -> bytes:
    svg_icon = (
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24">'
        b'<circle cx="12" cy="12" r="9" fill="#3b82f6"/>'
        b"</svg>"
    )
    whale_svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" width="48" height="48">'
        b'<circle cx="24" cy="24" r="18" fill="#3b82f6"/>'
        b"</svg>"
    )
    return _make_pack_zip(
        "dafeiyu-pack",
        "dafeiyu_theme",
        {
            "schema_version": 1,
            "id": "dafeiyu_theme",
            "name": "大肥鱼深海主题",
            "name_en": "DaFeiYu Deep-Sea Theme",
            "version": "1.0.0",
            "icon": "palette",
            "targets": ["space", "blog", "resume"],
            "pages": ["space", "list", "post", "resume"],
            "slot": "title_deco",
            "mount": {"tag": "span", "class": "sf-ext-dafeiyu-deco", "aria_label": "大肥鱼主题徽章"},
            "tokens": {
                "--accent": "#3b82f6",
                "--accent-soft": "rgba(59, 130, 246, 0.12)",
                "--bg": "#f2f8ff",
                "--surface": "#ffffff",
                "--text": "#0c2444",
                "--muted": "#4a6b8c",
                "--border": "#cde0f7",
                "--radius-card": "18px",
            },
            "icon_overrides": {
                "layers": "assets/icons/layers.svg",
                "book-open": "assets/icons/book-open.svg",
                "file-text": "assets/icons/file-text.svg",
                "globe": "assets/icons/globe.svg",
                "mail": "assets/icons/mail.svg",
            },
            "assets": {"css": ["assets/style.css"], "js": ["assets/main.js"]},
            "config_schema": [
                {
                    "key": "badge_text",
                    "kind": "text",
                    "label_default": "徽章文案",
                    "default": "大肥鱼",
                    "max_length": 24,
                },
                {
                    "key": "show_bubbles",
                    "kind": "boolean",
                    "label_default": "显示漂浮气泡装饰",
                    "default": True,
                },
            ],
        },
        assets={
            "style.css": b".sf-ext-dafeiyu-deco { display: inline-flex; }",
            "main.js": b"(function(){})();",
            "badge-whale.svg": whale_svg,
            "icons/layers.svg": svg_icon,
            "icons/book-open.svg": svg_icon,
            "icons/file-text.svg": svg_icon,
            "icons/globe.svg": svg_icon,
            "icons/mail.svg": svg_icon,
        },
    )


def test_theme_pack_end_to_end_in_memory_zip_tokens_title_deco_and_icons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.admin.fetch_og", lambda url: None)
    archive = _in_memory_dafeiyu_pack_zip()
    with TestClient(app) as client:
        csrf = login(client)
        uploaded = client.post(
            "/api/admin/plugin-packs/upload",
            files={"file": ("dafeiyu-pack.zip", archive, "application/zip")},
            headers=auth_headers(csrf),
        )
        assert uploaded.status_code == 200
        pack = uploaded.json()["pack"]
        assert [item["id"] for item in pack["plugins"]] == ["dafeiyu-pack.dafeiyu_theme"]

        space = create_app(client, csrf, "space", "大肥鱼内存包空间").json()["project"]
        create_app(client, csrf, "space", "子空间", parent_id=space["id"])
        child_blog = create_app(client, csrf, "blog", "大肥鱼博客", parent_id=space["id"]).json()["project"]
        child_resume = create_app(client, csrf, "resume", "大肥鱼简历", parent_id=space["id"]).json()[
            "project"
        ]
        blog_upd = client.patch(
            f"/api/admin/projects/{child_blog['id']}",
            json={
                "content": json.dumps(
                    {
                        "title": "大肥鱼博客",
                        "description": "海洋记录",
                        "posts": [
                            {
                                "slug": "hello-ocean",
                                "title": "深海首篇",
                                "date": "2026-11-25",
                                "tags": ["ocean"],
                                "summary": "摘要",
                                "body": "正文内容",
                            }
                        ],
                    },
                    ensure_ascii=False,
                )
            },
            headers=auth_headers(csrf),
        )
        assert blog_upd.status_code == 200
        resume_upd = client.patch(
            f"/api/admin/projects/{child_resume['id']}",
            json={
                "content": json.dumps(
                    {
                        "basics": {
                            "name": "大肥鱼",
                            "label": "工程师",
                            "email": "fish@example.com",
                            "url": "https://example.com",
                        },
                        "projects": [{"name": "SiteFlow", "description": "Gallery"}],
                    },
                    ensure_ascii=False,
                )
            },
            headers=auth_headers(csrf),
        )
        assert resume_upd.status_code == 200

        for target_id in (space["id"], child_blog["id"], child_resume["id"]):
            inst = client.post(
                f"/api/admin/projects/{target_id}/extensions/dafeiyu-pack.dafeiyu_theme/install",
                json={"enabled": True, "config": {"badge_text": "大肥鱼", "show_bubbles": True}},
                headers=auth_headers(csrf),
            )
            assert inst.status_code == 200

        space_page = client.get(f"/projects/{space['slug']}/")
        assert space_page.status_code == 200
        html = space_page.text
        assert "<style data-ext-tokens>:root {" in html
        assert "--accent: #3b82f6;" in html
        assert "--bg: #f2f8ff;" in html
        assert "--radius-card: 18px;" in html
        assert 'class="sf-title-row"' in html
        assert 'data-sf-pack-plugin="dafeiyu-pack.dafeiyu_theme"' in html
        assert "sf-ext-dafeiyu-deco" in html
        assert 'class="icon sf-icon-override"' in html
        assert "/media/plugins/dafeiyu-pack/dafeiyu_theme/icons/layers.svg?v=" in html
        assert "/media/plugins/dafeiyu-pack/dafeiyu_theme/icons/book-open.svg?v=" in html
        assert "/media/plugins/dafeiyu-pack/dafeiyu_theme/icons/file-text.svg?v=" in html
        assert "/media/plugins/dafeiyu-pack/dafeiyu_theme/icons/globe.svg?v=" in html

        icon_res = client.get("/media/plugins/dafeiyu-pack/dafeiyu_theme/icons/layers.svg")
        assert icon_res.status_code == 200
        assert "image/svg+xml" in icon_res.headers["content-type"]
        assert icon_res.headers["content-security-policy"] == "default-src 'none'; sandbox"
        assert "<script" not in icon_res.text

        for url in (
            f"/projects/{child_blog['slug']}/",
            f"/projects/{child_blog['slug']}/posts/hello-ocean",
            f"/projects/{child_resume['slug']}/",
        ):
            rendered = client.get(url)
            assert rendered.status_code == 200
            assert "--accent: #3b82f6;" in rendered.text
            assert 'data-sf-pack-plugin="dafeiyu-pack.dafeiyu_theme"' in rendered.text
            assert 'class="icon sf-icon-override"' in rendered.text


@pytest.mark.skipif(not SIBLING_PLUGINS_REPO.is_dir(), reason="siteflow-plugins sibling repo not present")
def test_dafeiyu_theme_pack_end_to_end_tokens_title_deco_and_icon_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.admin.fetch_og", lambda url: None)
    archive = _zip_real_pack(SIBLING_PLUGINS_REPO)
    with TestClient(app) as client:
        csrf = login(client)
        uploaded = client.post(
            "/api/admin/plugin-packs/upload",
            files={"file": ("siteflow-plugins.zip", archive, "application/zip")},
            headers=auth_headers(csrf),
        )
        assert uploaded.status_code == 200
        pack = uploaded.json()["pack"]
        plugin_ids = [item["id"] for item in pack["plugins"]]
        assert "siteflow-plugins.dafeiyu_theme" in plugin_ids

        space = create_app(client, csrf, "space", "大肥鱼深海空间").json()["project"]
        create_app(client, csrf, "space", "子空间", parent_id=space["id"])
        child_blog = create_app(client, csrf, "blog", "大肥鱼笔记", parent_id=space["id"]).json()["project"]
        child_resume = create_app(client, csrf, "resume", "大肥鱼简历", parent_id=space["id"]).json()[
            "project"
        ]
        client.post(
            "/api/admin/projects/link",
            json={"url": "https://example.com/ocean", "title": "深海外链", "parent_id": space["id"]},
            headers=auth_headers(csrf),
        )

        res_install = client.post(
            f"/api/admin/projects/{space['id']}/extensions/siteflow-plugins.dafeiyu_theme/install",
            json={
                "enabled": True,
                "config": {
                    "badge_text": "大肥鱼",
                    "badge_style": "pill",
                    "show_bubbles": True,
                    "show_wave": True,
                },
            },
            headers=auth_headers(csrf),
        )
        assert res_install.status_code == 200

        space_page = client.get(f"/projects/{space['slug']}/")
        assert space_page.status_code == 200
        html = space_page.text
        assert "<style data-ext-tokens>:root {" in html
        assert "--accent: #3b82f6;" in html
        assert "--bg: #f2f8ff;" in html
        assert "--radius-card: 18px;" in html
        assert 'class="sf-title-row"' in html
        assert 'data-sf-pack-plugin="siteflow-plugins.dafeiyu_theme"' in html
        assert "sf-ext-dafeiyu-deco" in html
        assert 'class="icon sf-icon-override"' in html
        assert "/media/plugins/siteflow-plugins/dafeiyu_theme/icons/layers.svg?v=" in html
        assert "/media/plugins/siteflow-plugins/dafeiyu_theme/icons/book-open.svg?v=" in html
        assert "/media/plugins/siteflow-plugins/dafeiyu_theme/icons/file-text.svg?v=" in html
        assert "/media/plugins/siteflow-plugins/dafeiyu_theme/icons/globe.svg?v=" in html

        icon_res = client.get("/media/plugins/siteflow-plugins/dafeiyu_theme/icons/layers.svg")
        assert icon_res.status_code == 200
        assert "image/svg+xml" in icon_res.headers["content-type"]
        assert icon_res.headers["content-security-policy"] == "default-src 'none'; sandbox"
        assert "<script" not in icon_res.text

        whale_res = client.get("/media/plugins/siteflow-plugins/dafeiyu_theme/badge-whale.svg")
        assert whale_res.status_code == 200
        assert "image/svg+xml" in whale_res.headers["content-type"]

        for target_id, target_url in (
            (child_blog["id"], f"/projects/{child_blog['slug']}/"),
            (child_resume["id"], f"/projects/{child_resume['slug']}/"),
        ):
            inst = client.post(
                f"/api/admin/projects/{target_id}/extensions/siteflow-plugins.dafeiyu_theme/install",
                json={"enabled": True},
                headers=auth_headers(csrf),
            )
            assert inst.status_code == 200
            rendered = client.get(target_url)
            assert rendered.status_code == 200
            assert "--accent: #3b82f6;" in rendered.text
            assert 'data-sf-pack-plugin="siteflow-plugins.dafeiyu_theme"' in rendered.text
            assert 'class="icon sf-icon-override"' in rendered.text


def test_i18n_zh_en_keys_aligned_including_space_layout() -> None:
    i18n_path = Path(__file__).resolve().parent.parent / "app" / "static" / "js" / "i18n.js"
    script = (
        "const fs = require('fs');"
        f"const src = fs.readFileSync({json.dumps(str(i18n_path))}, 'utf8');"
        "const m = src.match(/var DICT = (\\{[\\s\\S]*?\\n  \\});/);"
        "if (!m) throw new Error('DICT not found');"
        "const dict = Function('return ' + m[1])();"
        "const zh = Object.keys(dict.zh).sort();"
        "const en = Object.keys(dict.en).sort();"
        "const onlyZh = zh.filter(k => !dict.en.hasOwnProperty(k));"
        "const onlyEn = en.filter(k => !dict.zh.hasOwnProperty(k));"
        "console.log(JSON.stringify({onlyZh, onlyEn, hasLayout: Boolean(dict.zh['ext.space_layout.name'] && dict.en['ext.space_layout.name'])}));"
    )
    out = subprocess.check_output(["node", "-e", script], text=True)
    result = json.loads(out)
    assert result["onlyZh"] == []
    assert result["onlyEn"] == []
    assert result["hasLayout"] is True
