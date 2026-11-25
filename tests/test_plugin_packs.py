import io
import json
import stat
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.extensions import packs as packs_mod
from app.main import app
from tests.test_apps import create_app
from tests.test_flow import auth_headers, login

SIBLING_PLUGINS_REPO = Path(__file__).resolve().parent.parent.parent / "siteflow-plugins"


def _zip_directory(
    root: Path,
    *,
    prefix: str = "",
    manifest_overrides: dict[str, Any] | None = None,
    extra_files: dict[str, bytes] | None = None,
) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            if rel.startswith(".git/") or rel == ".git" or "/.git/" in rel:
                continue
            data = path.read_bytes()
            if rel == "siteflow-pack.json" and manifest_overrides:
                parsed = json.loads(data.decode("utf-8"))
                parsed.update(manifest_overrides)
                data = json.dumps(parsed, ensure_ascii=False).encode("utf-8")
            arcname = f"{prefix}{rel}" if prefix else rel
            zf.writestr(arcname, data)
        if extra_files:
            for rel_name, content in extra_files.items():
                arcname = f"{prefix}{rel_name}" if prefix else rel_name
                zf.writestr(arcname, content)
    return buf.getvalue()


def _multi_plugin_pack_zip(
    *,
    prefix: str = "",
    manifest_overrides: dict[str, Any] | None = None,
) -> bytes:
    pack_manifest: dict[str, Any] = {
        "schema_version": 1,
        "id": "siteflow-plugins",
        "name": "SiteFlow 官方扩展插件包",
        "name_en": "SiteFlow Official Plugin Pack",
        "description": "多场景声明式扩展插件包测试夹具",
        "description_en": "Declarative multi-target plugin pack fixture for tests.",
        "version": "1.0.0",
        "author": "SiteFlow",
        "homepage": "https://github.com/mcocdaa/siteflow-plugins",
        "plugins": [
            "plugins/reading_progress",
            "plugins/code_copy_badge",
            "plugins/space_welcome_badge",
            "plugins/resume_print_badge",
        ],
    }
    if manifest_overrides:
        pack_manifest.update(manifest_overrides)

    plugin_defs: list[dict[str, Any]] = [
        {
            "schema_version": 1,
            "id": "reading_progress",
            "name": "阅读进度条",
            "name_en": "Reading Progress",
            "description": "博客文章顶部阅读进度条",
            "description_en": "Top scroll reading progress bar for blog posts.",
            "version": "1.0.0",
            "icon": "eye",
            "targets": ["blog"],
            "pages": ["post"],
            "slot": "body_start",
            "assets": {"css": ["assets/style.css"], "js": ["assets/main.js"]},
            "mount": {"tag": "div", "class": "sf-ext-reading-progress", "aria_label": "阅读进度"},
            "config_schema": [
                {
                    "key": "height_px",
                    "kind": "range",
                    "label_default": "进度条高度 (px)",
                    "default": 3,
                    "min": 2,
                    "max": 6,
                    "step": 1,
                },
                {
                    "key": "color_style",
                    "kind": "select",
                    "label_default": "进度条配色",
                    "default": "accent",
                    "options": [
                        {"value": "accent", "label_default": "跟随主题强调色"},
                        {"value": "gradient", "label_default": "渐变动效"},
                        {"value": "mono", "label_default": "极简黑白"},
                    ],
                },
                {
                    "key": "show_percentage",
                    "kind": "boolean",
                    "label_default": "显示悬浮百分比胶囊",
                    "default": True,
                },
            ],
        },
        {
            "schema_version": 1,
            "id": "code_copy_badge",
            "name": "代码块一键复制",
            "name_en": "Code Copy Toolbar",
            "description": "博客文章代码块语言标签与一键复制按钮",
            "description_en": "Enhances fenced code blocks with copy button.",
            "version": "1.0.0",
            "icon": "command",
            "targets": ["blog"],
            "pages": ["post"],
            "slot": "body_end",
            "assets": {"css": ["assets/style.css"], "js": ["assets/main.js"]},
            "mount": {"tag": "div", "class": "sf-ext-code-copy-host", "aria_label": "代码块复制增强"},
            "config_schema": [
                {
                    "key": "show_language",
                    "kind": "boolean",
                    "label_default": "显示代码语言标签",
                    "default": True,
                },
                {
                    "key": "button_style",
                    "kind": "select",
                    "label_default": "复制按钮显示方式",
                    "default": "hover",
                    "options": [
                        {"value": "hover", "label_default": "悬停显示"},
                        {"value": "always", "label_default": "始终显示"},
                    ],
                },
                {
                    "key": "copy_label",
                    "kind": "text",
                    "label_default": "复制按钮文案",
                    "default": "复制",
                    "max_length": 24,
                },
                {
                    "key": "copied_label",
                    "kind": "text",
                    "label_default": "复制成功提示",
                    "default": "已复制",
                    "max_length": 24,
                },
                {
                    "key": "reset_delay_ms",
                    "kind": "number",
                    "label_default": "成功状态保持时长 (ms)",
                    "default": 1800,
                    "min": 600,
                    "max": 5000,
                    "step": 200,
                },
            ],
        },
        {
            "schema_version": 1,
            "id": "space_welcome_badge",
            "name": "空间状态徽章栏",
            "name_en": "Space Status Bar",
            "description": "空间作品画廊上方状态胶囊与欢迎语",
            "description_en": "Renders a status bar above the space gallery.",
            "version": "1.0.0",
            "icon": "layers",
            "targets": ["space"],
            "pages": ["space"],
            "slot": "main_start",
            "assets": {"css": ["assets/style.css"], "js": ["assets/main.js"]},
            "mount": {"tag": "section", "class": "sf-ext-space-welcome", "aria_label": "空间状态栏"},
            "config_schema": [
                {
                    "key": "status_label",
                    "kind": "text",
                    "label_default": "状态标签",
                    "default": "持续更新中",
                    "max_length": 40,
                },
                {
                    "key": "tone",
                    "kind": "select",
                    "label_default": "徽章色调",
                    "default": "accent",
                    "options": [
                        {"value": "accent", "label_default": "跟随空间强调色"},
                        {"value": "emerald", "label_default": "在线翠绿"},
                        {"value": "amber", "label_default": "精选暖琥珀"},
                        {"value": "neutral", "label_default": "低调中性灰"},
                    ],
                },
                {
                    "key": "show_count",
                    "kind": "boolean",
                    "label_default": "显示空间内作品数量",
                    "default": True,
                },
            ],
        },
        {
            "schema_version": 1,
            "id": "resume_print_badge",
            "name": "简历求职状态条",
            "name_en": "Resume Availability Ribbon",
            "description": "简历顶部求职意向与更新标记",
            "description_en": "Displays an availability ribbon at the top of a resume.",
            "version": "1.0.0",
            "icon": "printer",
            "targets": ["resume"],
            "pages": ["resume"],
            "slot": "main_start",
            "assets": {"css": ["assets/style.css"], "js": ["assets/main.js"]},
            "mount": {"tag": "aside", "class": "sf-ext-resume-badge", "aria_label": "简历状态提示"},
            "config_schema": [
                {
                    "key": "availability",
                    "kind": "select",
                    "label_default": "当前状态",
                    "default": "open",
                    "options": [
                        {"value": "open", "label_default": "正在看新机会"},
                        {"value": "consulting", "label_default": "开放顾问 / 合作"},
                        {"value": "passive", "label_default": "暂不求职，欢迎交流"},
                        {"value": "custom", "label_default": "自定义状态文案"},
                    ],
                },
                {
                    "key": "updated_tag",
                    "kind": "text",
                    "label_default": "更新标记（可选）",
                    "default": "",
                    "max_length": 32,
                },
                {
                    "key": "show_in_print",
                    "kind": "boolean",
                    "label_default": "打印 / 导出 PDF 时保留显示",
                    "default": False,
                },
            ],
        },
    ]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{prefix}siteflow-pack.json", json.dumps(pack_manifest, ensure_ascii=False))
        for pdef in plugin_defs:
            pid = pdef["id"]
            cls = pdef["mount"]["class"]
            zf.writestr(
                f"{prefix}plugins/{pid}/plugin.json",
                json.dumps(pdef, ensure_ascii=False),
            )
            zf.writestr(
                f"{prefix}plugins/{pid}/assets/style.css",
                f".{cls}{{display:block;}}",
            )
            zf.writestr(
                f"{prefix}plugins/{pid}/assets/main.js",
                f"window.__sfPackLoaded = window.__sfPackLoaded || []; window.__sfPackLoaded.push('{pid}');",
            )
    return buf.getvalue()


def _minimal_pack_zip(
    *,
    pack_id: str = "demo-pack",
    version: str = "1.0.0",
    plugin_id: str = "sample_badge",
    extra_assets: dict[str, bytes] | None = None,
    plugin_override: dict[str, Any] | None = None,
) -> bytes:
    pack_manifest = {
        "schema_version": 1,
        "id": pack_id,
        "name": "示例插件包",
        "version": version,
        "plugins": [f"plugins/{plugin_id}"],
    }
    plugin_manifest: dict[str, Any] = {
        "schema_version": 1,
        "id": plugin_id,
        "name": "示例徽章",
        "description": "测试声明式插件",
        "version": version,
        "icon": "sparkles",
        "targets": ["blog"],
        "pages": ["post"],
        "slot": "body_end",
        "assets": {"css": ["assets/style.css"], "js": ["assets/main.js"]},
        "mount": {"tag": "div", "class": "sf-demo-badge", "aria_label": "示例"},
        "config_schema": [
            {"key": "label", "kind": "text", "label_default": "标签", "default": "Demo"},
        ],
    }
    if plugin_override:
        plugin_manifest.update(plugin_override)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("siteflow-pack.json", json.dumps(pack_manifest, ensure_ascii=False))
        zf.writestr(f"plugins/{plugin_id}/plugin.json", json.dumps(plugin_manifest, ensure_ascii=False))
        zf.writestr(f"plugins/{plugin_id}/assets/style.css", ".sf-demo-badge{display:block;}")
        zf.writestr(f"plugins/{plugin_id}/assets/main.js", "console.log('ok');")
        if extra_assets:
            for name, raw in extra_assets.items():
                zf.writestr(f"plugins/{plugin_id}/assets/{name}", raw)
    return buf.getvalue()


def test_real_siteflow_plugins_upload_render_assets_and_batch_delete() -> None:
    direct_zip = _multi_plugin_pack_zip()
    wrapped_zip = _multi_plugin_pack_zip(prefix="siteflow-plugins-main/")

    with TestClient(app) as client:
        csrf = login(client)
        initial_packs = client.get("/api/admin/plugin-packs", headers={"X-CSRF-Token": csrf})
        assert initial_packs.status_code == 200
        assert (
            client.get(
                "/api/admin/plugin-packs",
                headers={"X-CSRF-Token": csrf, "Origin": "https://evil.example"},
            ).status_code
            == 403
        )
        assert (
            client.get(
                "/api/admin/plugin-packs",
                headers={"X-CSRF-Token": csrf, "Sec-Fetch-Site": "cross-site"},
            ).status_code
            == 403
        )
        packs_data = initial_packs.json()["packs"]
        assert len(packs_data) == 1
        assert packs_data[0]["id"] == "official"
        assert packs_data[0]["builtin"] is True

        uploaded = client.post(
            "/api/admin/plugin-packs/upload",
            files={"file": ("siteflow-plugins.zip", direct_zip, "application/zip")},
            headers=auth_headers(csrf),
        )
        assert uploaded.status_code == 200
        assert uploaded.json()["pack"]["id"] == "siteflow-plugins"
        assert uploaded.json()["pack"]["plugin_count"] == 4

        re_uploaded = client.post(
            "/api/admin/plugin-packs/upload",
            files={"file": ("siteflow-plugins-main.zip", wrapped_zip, "application/zip")},
            data={"replace": "true"},
            headers=auth_headers(csrf),
        )
        assert re_uploaded.status_code == 200
        assert len(re_uploaded.json()["packs"]) == 2

        blog = create_app(client, csrf, "blog", "插件包博客").json()["project"]
        space = create_app(client, csrf, "space", "插件包空间").json()["project"]
        resume = create_app(client, csrf, "resume", "插件包简历").json()["project"]
        assert (
            client.post(
                f"/api/admin/projects/{blog['id']}/posts",
                json={
                    "title": "外部插件测试文",
                    "slug": "pack-post",
                    "body": "## 标题\n\n```python\nprint('hello')\n```",
                },
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )

        blog_ids = [
            item["id"]
            for item in client.get(
                f"/api/admin/projects/{blog['id']}/extensions", headers=auth_headers(csrf)
            ).json()["extensions"]
        ]
        space_ids = [
            item["id"]
            for item in client.get(
                f"/api/admin/projects/{space['id']}/extensions", headers=auth_headers(csrf)
            ).json()["extensions"]
        ]
        resume_ids = [
            item["id"]
            for item in client.get(
                f"/api/admin/projects/{resume['id']}/extensions", headers=auth_headers(csrf)
            ).json()["extensions"]
        ]

        assert "siteflow-plugins.reading_progress" in blog_ids
        assert "siteflow-plugins.code_copy_badge" in blog_ids
        assert "siteflow-plugins.space_welcome_badge" not in blog_ids
        assert "siteflow-plugins.resume_print_badge" not in blog_ids

        assert "siteflow-plugins.space_welcome_badge" in space_ids
        assert "siteflow-plugins.reading_progress" not in space_ids

        assert "siteflow-plugins.resume_print_badge" in resume_ids
        assert "siteflow-plugins.code_copy_badge" not in resume_ids

        assert (
            client.post(
                f"/api/admin/projects/{blog['id']}/extensions/post_cover/install",
                json={"enabled": True},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert (
            client.post(
                f"/api/admin/projects/{blog['id']}/extensions/siteflow-plugins.reading_progress/install",
                json={"enabled": True, "config": {"height_px": 5, "color_style": "gradient"}},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert (
            client.post(
                f"/api/admin/projects/{blog['id']}/extensions/siteflow-plugins.code_copy_badge/install",
                json={"enabled": True, "config": {"button_style": "always", "copy_label": "复制代码"}},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert (
            client.post(
                f"/api/admin/projects/{space['id']}/extensions/siteflow-plugins.space_welcome_badge/install",
                json={"enabled": True, "config": {"status_label": "持续演进", "tone": "emerald"}},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert (
            client.post(
                f"/api/admin/projects/{resume['id']}/extensions/siteflow-plugins.resume_print_badge/install",
                json={"enabled": True, "config": {"availability": "open", "updated_tag": "2026-11"}},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )

        blog_list = client.get(f"/projects/{blog['slug']}/")
        assert blog_list.status_code == 200
        assert "siteflow-plugins.reading_progress" not in blog_list.text

        blog_post = client.get(f"/projects/{blog['slug']}/posts/pack-post")
        assert blog_post.status_code == 200
        assert 'data-sf-pack-plugin="siteflow-plugins.reading_progress"' in blog_post.text
        assert 'data-sf-pack-plugin="siteflow-plugins.code_copy_badge"' in blog_post.text
        assert "/media/plugins/siteflow-plugins/reading_progress/style.css?v=" in blog_post.text
        assert "/media/plugins/siteflow-plugins/code_copy_badge/main.js?v=" in blog_post.text

        space_page = client.get(f"/projects/{space['slug']}/")
        assert space_page.status_code == 200
        assert 'data-sf-pack-plugin="siteflow-plugins.space_welcome_badge"' in space_page.text
        assert "/media/plugins/siteflow-plugins/space_welcome_badge/style.css?v=" in space_page.text

        resume_page = client.get(f"/projects/{resume['slug']}/")
        assert resume_page.status_code == 200
        assert 'data-sf-pack-plugin="siteflow-plugins.resume_print_badge"' in resume_page.text
        assert "/media/plugins/siteflow-plugins/resume_print_badge/main.js?v=" in resume_page.text

        asset_v = client.get("/media/plugins/siteflow-plugins/reading_progress/style.css?v=deadbeef")
        assert asset_v.status_code == 200
        assert asset_v.headers["x-content-type-options"] == "nosniff"
        assert "immutable" in asset_v.headers["cache-control"]
        assert asset_v.headers["content-type"].startswith("text/css")
        etag = asset_v.headers["etag"]
        assert (
            client.get(
                "/media/plugins/siteflow-plugins/reading_progress/style.css?v=deadbeef",
                headers={"If-None-Match": etag},
            ).status_code
            == 304
        )
        asset_plain = client.get("/media/plugins/siteflow-plugins/reading_progress/main.js")
        assert asset_plain.status_code == 200
        assert "immutable" not in asset_plain.headers["cache-control"]

        for bad_path in (
            "/media/plugins/siteflow-plugins/reading_progress/../plugin.json",
            "/media/plugins/siteflow-plugins/reading_progress/%2e%2e/plugin.json",
            "/media/plugins/siteflow-plugins/reading_progress/.env",
            "/media/plugins/siteflow-plugins/reading_progress/evil.py",
            "/media/plugins/official/mascot/main.js",
        ):
            assert client.get(bad_path).status_code == 404

        assert (
            client.delete("/api/admin/plugin-packs/official", headers=auth_headers(csrf)).status_code == 400
        )

        deleted = client.delete(
            "/api/admin/plugin-packs/siteflow-plugins",
            headers=auth_headers(csrf),
        )
        assert deleted.status_code == 200
        assert deleted.json()["removed"]["cleaned_projects"] == 3
        assert len(deleted.json()["packs"]) == 1
        assert not (app.state.config.data / "plugins" / "packs" / "siteflow-plugins").exists()
        assert client.get("/media/plugins/siteflow-plugins/reading_progress/style.css").status_code == 404

        for pid in (blog["id"], space["id"], resume["id"]):
            detail = client.get(f"/api/admin/projects/{pid}", headers=auth_headers(csrf)).json()["project"]
            parsed = json.loads(detail["content"])
            ext_map = parsed.get("extensions", {})
            assert not any(k.startswith("siteflow-plugins.") for k in ext_map)
        blog_detail = json.loads(
            client.get(f"/api/admin/projects/{blog['id']}", headers=auth_headers(csrf)).json()["project"][
                "content"
            ]
        )
        assert "post_cover" in blog_detail["extensions"]


def test_plugin_pack_url_subscribe_sync_and_ssrf_rejection(monkeypatch: pytest.MonkeyPatch) -> None:
    v1_zip = _multi_plugin_pack_zip(prefix="siteflow-plugins-main/")
    v2_zip = _multi_plugin_pack_zip(
        prefix="siteflow-plugins-main/",
        manifest_overrides={"version": "1.1.0"},
    )
    renamed_zip = _multi_plugin_pack_zip(
        prefix="siteflow-plugins-main/",
        manifest_overrides={"id": "other-pack", "version": "1.2.0"},
    )
    seen_urls: list[str] = []
    current_archive: dict[str, bytes] = {"payload": v1_zip}

    def fake_validate(url: str) -> str:
        if "127.0.0.1" in url or "169.254.169.254" in url or "localhost" in url:
            raise ValueError("不安全的目标地址")
        return "github.com"

    def fake_fetch(url: str, *, max_bytes: int = 10 * 1024 * 1024, timeout: float = 15.0) -> bytes:
        seen_urls.append(url)
        return current_archive["payload"]

    with TestClient(app) as client:
        csrf = login(client)

        for bad_url in (
            "http://github.com/mcocdaa/siteflow-plugins",
            "https://localhost/pack.zip",
            "https://127.0.0.1/pack.zip",
            "https://169.254.169.254/latest/meta-data/pack.zip",
            "https://user:pass@github.com/mcocdaa/siteflow-plugins",
        ):
            resp = client.post(
                "/api/admin/plugin-packs",
                json={"url": bad_url},
                headers=auth_headers(csrf),
            )
            assert resp.status_code == 400

        monkeypatch.setattr("app.og._safe_host", lambda u: _reject_private_or_allow_public(u))

        class _RedirectResp:
            def __init__(self) -> None:
                self.status_code = 302
                self.headers = {"location": "https://169.254.169.254/secret.zip"}

            def iter_bytes(self, chunk_size: int = 65536):
                return iter(())

        @contextmanager
        def fake_stream(*args: Any, **kwargs: Any):
            yield _RedirectResp()

        monkeypatch.setattr("app.og.httpx.stream", fake_stream)
        redir_resp = client.post(
            "/api/admin/plugin-packs",
            json={"url": "https://example.com/plugin-pack.zip"},
            headers=auth_headers(csrf),
        )
        assert redir_resp.status_code == 400

        monkeypatch.setattr(packs_mod, "validate_public_host", fake_validate)
        monkeypatch.setattr(packs_mod, "fetch_archive", fake_fetch)

        sub = client.post(
            "/api/admin/plugin-packs",
            json={"url": "https://github.com/mcocdaa/siteflow-plugins"},
            headers=auth_headers(csrf),
        )
        assert sub.status_code == 200
        assert sub.json()["pack"]["id"] == "siteflow-plugins"
        assert sub.json()["pack"]["version"] == "1.0.0"
        assert seen_urls[-1] == "https://github.com/mcocdaa/siteflow-plugins/archive/refs/heads/main.zip"

        dup = client.post(
            "/api/admin/plugin-packs",
            json={"url": "https://github.com/mcocdaa/siteflow-plugins/tree/main"},
            headers=auth_headers(csrf),
        )
        assert dup.status_code == 409

        current_archive["payload"] = v2_zip
        synced = client.post(
            "/api/admin/plugin-packs/siteflow-plugins/sync",
            headers=auth_headers(csrf),
        )
        assert synced.status_code == 200
        assert synced.json()["pack"]["version"] == "1.1.0"

        current_archive["payload"] = renamed_zip
        bad_sync = client.post(
            "/api/admin/plugin-packs/siteflow-plugins/sync",
            headers=auth_headers(csrf),
        )
        assert bad_sync.status_code == 422

        assert (
            client.delete(
                "/api/admin/plugin-packs/siteflow-plugins",
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )

        current_archive["payload"] = v1_zip
        tree_sub = client.post(
            "/api/admin/plugin-packs",
            json={"url": "https://github.com/mcocdaa/siteflow-plugins/tree/main"},
            headers=auth_headers(csrf),
        )
        assert tree_sub.status_code == 200
        assert (
            tree_sub.json()["pack"]["source_url"] == "https://github.com/mcocdaa/siteflow-plugins/tree/main"
        )


def _reject_private_or_allow_public(url: str) -> tuple[Any, str]:
    import ipaddress
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").strip().lower()
    if host in ("127.0.0.1", "169.254.169.254", "localhost"):
        raise ValueError(f"不安全的目标地址: {host}")
    return ipaddress.ip_address("93.184.216.34"), host


def test_plugin_pack_negative_security_zips_and_svg_sanitization() -> None:
    with TestClient(app) as client:
        csrf = login(client)

        official_zip = _minimal_pack_zip(pack_id="official")
        assert (
            client.post(
                "/api/admin/plugin-packs/upload",
                files={"file": ("official.zip", official_zip, "application/zip")},
                headers=auth_headers(csrf),
            ).status_code
            == 400
        )

        slip_buf = io.BytesIO()
        with zipfile.ZipFile(slip_buf, "w") as zf:
            zf.writestr("../evil.js", "alert(1)")
        assert (
            client.post(
                "/api/admin/plugin-packs/upload",
                files={"file": ("slip.zip", slip_buf.getvalue(), "application/zip")},
                headers=auth_headers(csrf),
            ).status_code
            == 422
        )

        sym_buf = io.BytesIO()
        with zipfile.ZipFile(sym_buf, "w") as zf:
            info = zipfile.ZipInfo("siteflow-pack.json")
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, "/etc/passwd")
        assert (
            client.post(
                "/api/admin/plugin-packs/upload",
                files={"file": ("sym.zip", sym_buf.getvalue(), "application/zip")},
                headers=auth_headers(csrf),
            ).status_code
            == 422
        )

        enc_buf = io.BytesIO()
        with zipfile.ZipFile(enc_buf, "w") as zf:
            info = zipfile.ZipInfo("siteflow-pack.json")
            info.flag_bits |= 1
            zf.writestr(info, "{}")
        assert (
            client.post(
                "/api/admin/plugin-packs/upload",
                files={"file": ("enc.zip", enc_buf.getvalue(), "application/zip")},
                headers=auth_headers(csrf),
            ).status_code
            == 422
        )

        oversized = b"0" * (10 * 1024 * 1024 + 1)
        assert (
            client.post(
                "/api/admin/plugin-packs/upload",
                files={"file": ("big.zip", oversized, "application/zip")},
                headers=auth_headers(csrf),
            ).status_code
            == 413
        )

        bad_svg_zip = _minimal_pack_zip(
            pack_id="bad-svg-pack",
            extra_assets={
                "icon.svg": b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
            },
        )
        assert (
            client.post(
                "/api/admin/plugin-packs/upload",
                files={"file": ("bad-svg.zip", bad_svg_zip, "application/zip")},
                headers=auth_headers(csrf),
            ).status_code
            == 422
        )

        clean_svg_zip = _minimal_pack_zip(
            pack_id="clean-svg-pack",
            extra_assets={
                "icon.svg": b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="8" fill="#4f46e5"/></svg>'
            },
        )
        clean_resp = client.post(
            "/api/admin/plugin-packs/upload",
            files={"file": ("clean-svg.zip", clean_svg_zip, "application/zip")},
            headers=auth_headers(csrf),
        )
        assert clean_resp.status_code == 200
        svg_asset = client.get("/media/plugins/clean-svg-pack/sample_badge/icon.svg")
        assert svg_asset.status_code == 200
        assert svg_asset.headers["content-type"].startswith("image/svg+xml")
        assert svg_asset.headers["content-security-policy"] == "default-src 'none'; sandbox"
        assert svg_asset.headers["x-content-type-options"] == "nosniff"

        bad_manifest_zip = _minimal_pack_zip(
            pack_id="bad-plugin-pack",
            plugin_override={"schema_version": 99},
        )
        assert (
            client.post(
                "/api/admin/plugin-packs/upload",
                files={"file": ("bad-manifest.zip", bad_manifest_zip, "application/zip")},
                headers=auth_headers(csrf),
            ).status_code
            == 422
        )

        secret_kind_zip = _minimal_pack_zip(
            pack_id="secret-kind-pack",
            plugin_override={
                "config_schema": [
                    {"key": "tok", "kind": "secret", "label_default": "密钥"},
                ]
            },
        )
        assert (
            client.post(
                "/api/admin/plugin-packs/upload",
                files={"file": ("secret-kind.zip", secret_kind_zip, "application/zip")},
                headers=auth_headers(csrf),
            ).status_code
            == 422
        )


@pytest.mark.skipif(
    not SIBLING_PLUGINS_REPO.is_dir(),
    reason="sibling siteflow-plugins repository not present",
)
def test_sibling_siteflow_plugins_repo_upload_when_present() -> None:
    archive = _zip_directory(SIBLING_PLUGINS_REPO, prefix="siteflow-plugins-main/")
    with TestClient(app) as client:
        csrf = login(client)
        uploaded = client.post(
            "/api/admin/plugin-packs/upload",
            files={"file": ("siteflow-plugins-main.zip", archive, "application/zip")},
            headers=auth_headers(csrf),
        )
        assert uploaded.status_code == 200
        pack = uploaded.json()["pack"]
        assert pack["id"] == "siteflow-plugins"
        assert pack["plugin_count"] >= 4
