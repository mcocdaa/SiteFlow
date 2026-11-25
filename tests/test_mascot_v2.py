import io
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.extensions.mascot import (
    DEFAULT_SYSTEM_PROMPT,
    DEFAULT_TIPS,
    MASCOT_CHARACTER_SPECS,
    MASCOT_CHARACTERS,
    MascotCharacterSpec,
    MascotExtension,
    get_character_spec,
)
from app.main import app
from app.templating import templates
from app.uploads import InvalidUpload, sanitize_svg
from tests.test_apps import create_app
from tests.test_flow import auth_headers, login

APP_DIR = Path(__file__).resolve().parent.parent / "app"
EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]")
CLEAN_GRADIENT_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    b'<defs><linearGradient id="g1" x1="0" y1="0" x2="1" y2="1">'
    b'<stop offset="0%" stop-color="#4f46e5"/><stop offset="100%" stop-color="#38bdf8"/>'
    b"</linearGradient></defs>"
    b'<circle cx="32" cy="32" r="28" fill="url(#g1)"/>'
    b"</svg>"
)


def _make_rgba_png() -> bytes:
    buf = io.BytesIO()
    img = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    for x in range(8, 24):
        for y in range(8, 24):
            img.putpixel((x, y), (79, 70, 229, 220))
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_all_seven_chibi_skins_valid_svg_and_unique_admin_ids() -> None:
    assert MASCOT_CHARACTERS == (
        "cat",
        "dog",
        "whale",
        "gemini_cat",
        "slime",
        "vocaloid",
        "dafeiyu",
    )
    assert tuple(spec.id for spec in MASCOT_CHARACTER_SPECS) == MASCOT_CHARACTERS
    dafeiyu_spec = get_character_spec("dafeiyu")
    assert isinstance(dafeiyu_spec, MascotCharacterSpec)
    assert dafeiyu_spec.kind == "pose_svg"
    pose_names = ("idle", "thinking", "speaking", "tap")
    assert set(dafeiyu_spec.pose_map()) == set(pose_names)
    assert get_character_spec("nonexistent-skin").id == "cat"

    inline_skins = ("cat", "dog", "whale", "gemini_cat", "slime", "vocaloid")
    tmpl = templates.env.from_string('{% import "_mascot_skins.html" as s %}{{ s.render_skin(c, 76) }}')

    for char in inline_skins:
        inline_spec = get_character_spec(char)
        assert inline_spec.kind == "inline_svg"
        assert inline_spec.poses == ()
        rendered = tmpl.render(c=char)
        assert f'class="sf-mascot-svg sf-mascot-skin-{char}"' in rendered
        assert 'viewBox="0 0 100 100"' in rendered
        assert "style=" not in rendered
        assert "<defs" not in rendered.lower()
        assert 'id="' not in rendered
        assert "http://" not in rendered and "https://" not in rendered
        parsed = ET.fromstring(rendered)
        assert parsed.tag == "svg"
        assert parsed.attrib.get("viewBox") == "0 0 100 100"

    dafeiyu_rendered = tmpl.render(c="dafeiyu")
    assert 'class="sf-mascot-svg sf-mascot-skin-dafeiyu sf-mascot-sprite-svg"' in dafeiyu_rendered
    assert "data-mascot-pose-img" in dafeiyu_rendered
    assert 'data-mascot-pose="idle"' in dafeiyu_rendered
    assert 'src="/static/img/mascot/dafeiyu/idle.svg?v=' in dafeiyu_rendered
    assert "style=" not in dafeiyu_rendered
    assert "http://" not in dafeiyu_rendered and "https://" not in dafeiyu_rendered

    mascot_img_dir = APP_DIR / "static" / "img" / "mascot"
    assert not (mascot_img_dir / "dafeiyu.svg").exists()
    dafeiyu_dir = mascot_img_dir / "dafeiyu"
    for pose in pose_names:
        pose_path = dafeiyu_dir / f"{pose}.svg"
        assert pose_path.is_file()
        pose_raw = pose_path.read_text(encoding="utf-8")
        pose_lower = pose_raw.lower()
        assert "<script" not in pose_lower
        assert "<image" not in pose_lower
        assert "style=" not in pose_lower
        assert "id=" not in pose_lower
        assert "<!--" not in pose_raw
        assert "<?xml" not in pose_lower
        pose_no_ns = pose_raw.replace('xmlns="http://www.w3.org/2000/svg"', "", 1).lower()
        assert "http://" not in pose_no_ns
        assert "https://" not in pose_no_ns
        assert "data:" not in pose_no_ns
        parsed_asset = ET.fromstring(pose_raw)
        assert parsed_asset.tag.endswith("svg")
        assert parsed_asset.attrib.get("viewBox")
        asset_paths = [el for el in parsed_asset.iter() if el.tag.endswith("path")]
        assert len(asset_paths) >= 100
        for el in parsed_asset.iter():
            for attr_key, attr_val in el.attrib.items():
                key_lower = attr_key.lower()
                val_lower = attr_val.lower()
                assert not key_lower.startswith("on")
                assert key_lower not in {"style", "id"}
                assert "http://" not in val_lower
                assert "https://" not in val_lower
                assert "data:" not in val_lower

    with TestClient(app) as client:
        for pose in pose_names:
            asset_resp = client.get(f"/static/img/mascot/dafeiyu/{pose}.svg")
            assert asset_resp.status_code == 200
            assert asset_resp.headers["content-type"].startswith("image/svg+xml")

        csrf = login(client)
        blog = create_app(client, csrf, "blog", "七皮肤博客").json()["project"]
        space = create_app(client, csrf, "space", "七皮肤空间").json()["project"]
        assert (
            client.post(
                f"/api/admin/projects/{blog['id']}/posts",
                json={"title": "大肥鱼测试文章", "slug": "dafeiyu-post", "body": "## 第一节\n\n正文内容"},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        for proj in (blog, space):
            admin_html = client.get(f"/admin/projects/{proj['id']}").text
            for char in MASCOT_CHARACTERS:
                assert f'data-mascot-skin-tpl="{char}"' in admin_html
                assert f"sf-mascot-skin-{char}" in admin_html
            ids = re.findall(r'(?<![A-Za-z0-9_-])id="([^"]+)"', admin_html)
            assert len(ids) == len(set(ids))

        for char in MASCOT_CHARACTERS:
            resp = client.post(
                f"/api/admin/projects/{blog['id']}/extensions/mascot/install",
                json={"enabled": True, "config": {"character": char}},
                headers=auth_headers(csrf),
            )
            assert resp.status_code == 200
            page = client.get(f"/projects/{blog['slug']}/")
            assert page.status_code == 200
            payload = _extract_mascot_payload(page.text)
            if char == "dafeiyu":
                assert 'data-mascot-kind="pose_svg"' in page.text
                assert 'class="sf-mascot-svg sf-mascot-skin-dafeiyu sf-mascot-sprite-svg"' in page.text
                assert "data-mascot-pose-img" in page.text
                assert 'data-mascot-pose="idle"' in page.text
                assert 'src="/static/img/mascot/dafeiyu/idle.svg?v=' in page.text
                assert payload["character_kind"] == "pose_svg"
                poses_payload = payload["poses"]
                assert isinstance(poses_payload, dict)
                assert set(poses_payload) == set(pose_names)
                for pose in pose_names:
                    assert str(poses_payload[pose]).startswith(f"/static/img/mascot/dafeiyu/{pose}.svg?v=")
            else:
                assert 'data-mascot-kind="inline_svg"' in page.text
                assert f'class="sf-mascot-svg sf-mascot-skin-{char}"' in page.text
                assert payload["character_kind"] == "inline_svg"
                assert payload["poses"] == {}

        assert (
            client.patch(
                f"/api/admin/projects/{blog['id']}/extensions/mascot",
                json={"config": {"character": "dafeiyu"}},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        blog_post_page = client.get(f"/projects/{blog['slug']}/posts/dafeiyu-post")
        assert blog_post_page.status_code == 200
        assert 'data-mascot-kind="pose_svg"' in blog_post_page.text
        assert 'class="sf-mascot-svg sf-mascot-skin-dafeiyu sf-mascot-sprite-svg"' in blog_post_page.text
        assert "data-mascot-pose-img" in blog_post_page.text
        assert 'data-mascot-pose="idle"' in blog_post_page.text
        assert 'src="/static/img/mascot/dafeiyu/idle.svg?v=' in blog_post_page.text
        assert "data-mascot-zoom" in blog_post_page.text
        assert "sf-mascot-fx-think" in blog_post_page.text
        assert "sf-mascot-fx-speak" in blog_post_page.text
        post_payload = _extract_mascot_payload(blog_post_page.text)
        assert post_payload["character_kind"] == "pose_svg"
        post_poses = post_payload["poses"]
        assert isinstance(post_poses, dict)
        assert set(post_poses) == set(pose_names)

        assert (
            client.post(
                f"/api/admin/projects/{space['id']}/extensions/mascot/install",
                json={"enabled": True, "config": {"character": "dafeiyu"}},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        space_page = client.get(f"/projects/{space['slug']}/")
        assert space_page.status_code == 200
        assert 'data-mascot-kind="pose_svg"' in space_page.text
        assert 'class="sf-mascot-svg sf-mascot-skin-dafeiyu sf-mascot-sprite-svg"' in space_page.text
        assert "data-mascot-pose-img" in space_page.text
        assert 'data-mascot-pose="idle"' in space_page.text
        assert 'src="/static/img/mascot/dafeiyu/idle.svg?v=' in space_page.text
        assert "data-mascot-zoom" in space_page.text
        assert "sf-mascot-fx-think" in space_page.text
        assert "sf-mascot-fx-speak" in space_page.text
        space_payload = _extract_mascot_payload(space_page.text)
        assert space_payload["character_kind"] == "pose_svg"
        space_poses = space_payload["poses"]
        assert isinstance(space_poses, dict)
        assert set(space_poses) == set(pose_names)

        assert (
            client.patch(
                f"/api/admin/projects/{blog['id']}/extensions/mascot",
                json={
                    "config": {
                        "character": "dafeiyu",
                        "custom_avatar": "https://example.com/custom-mascot.png",
                    }
                },
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        custom_page = client.get(f"/projects/{blog['slug']}/")
        assert custom_page.status_code == 200
        assert 'data-mascot-kind="custom"' in custom_page.text
        assert "data-mascot-pose-img" not in custom_page.text
        custom_payload = _extract_mascot_payload(custom_page.text)
        assert custom_payload["character_kind"] == "custom"
        assert custom_payload["poses"] == {}


def _extract_mascot_payload(html: str) -> dict[str, object]:
    match = re.search(
        r'<script type="application/json" data-mascot-config>(.*?)</script>',
        html,
        re.DOTALL,
    )
    assert match is not None
    parsed = json.loads(match.group(1))
    assert isinstance(parsed, dict)
    return parsed


def test_mascot_v3_tips_rows_comments_payload_dock_and_concise_prompt() -> None:
    ext = MascotExtension()
    schema_by_key = {field.key: field for field in ext.config_schema}
    assert schema_by_key["tips"].rows == 9
    assert schema_by_key["system_prompt"].rows == 5
    assert any(line.startswith("#") for line in DEFAULT_TIPS)
    joined_default_tips = "\n".join(DEFAULT_TIPS)
    assert "{progress}" in joined_default_tips
    assert "<%n>" not in joined_default_tips
    assert "<%n>" not in (schema_by_key["tips"].help_default or "")
    assert "{heading}" in joined_default_tips
    assert "{time}" in joined_default_tips
    assert DEFAULT_SYSTEM_PROMPT == (
        "你是站点的看板娘助手，请使用友好、简洁、准确的对应用户语言回答访客的问题。"
        "若提供了当前页面上下文，请优先结合页面内容作答。"
    )
    legacy_tips = [
        "好文章值得慢慢读，累了就歇一会儿～",
        "按 Ctrl / Cmd + F 可以快速查找关键词哦",
        "看完记得回到顶部逛逛其他文章呀！",
    ]
    assert ext.normalize_config({"tips": legacy_tips}, strict=False)["tips"] == DEFAULT_TIPS
    assert ext.normalize_config({"tips": ["自定义提示语"]}, strict=False)["tips"] == ["自定义提示语"]

    with TestClient(app) as admin_client, TestClient(app) as guest_client:
        csrf = login(admin_client)
        blog = create_app(admin_client, csrf, "blog", "参数提示语博客").json()["project"]
        pid, slug = blog["id"], blog["slug"]
        post_body = "## 章节一\n\n这是用来验证字数与章节提示语的正文内容。"
        assert (
            admin_client.post(
                f"/api/admin/projects/{pid}/posts",
                json={"title": "参数化提示语测试文章", "slug": "tips-post", "body": post_body},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )

        custom_tips = [
            "# 第一行管理员注释，不应展示给访客",
            "# 第二行注释：支持 {progress} 与 {heading}",
            "当前阅读进度 {progress}%",
            "正在浏览「{heading}」—— 来自 {site}",
            "本文共 {words} 字，{time}好！",
        ]
        inst = admin_client.post(
            f"/api/admin/projects/{pid}/extensions/mascot/install",
            json={
                "enabled": True,
                "config": {
                    "character": "dafeiyu",
                    "tips": custom_tips,
                    "chat_access": "off",
                },
            },
            headers=auth_headers(csrf),
        )
        assert inst.status_code == 200
        saved_tips = inst.json()["extension"]["config"]["tips"]
        assert saved_tips == custom_tips
        assert any(line.startswith("#") for line in saved_tips)

        guest_post_off = guest_client.get(f"/projects/{slug}/posts/tips-post")
        assert guest_post_off.status_code == 200
        assert "sf-mascot-dock" not in guest_post_off.text
        assert "data-mascot-zoom" in guest_post_off.text
        assert "sf-mascot-fx-think" in guest_post_off.text
        assert "sf-mascot-fx-speak" in guest_post_off.text
        payload_off = _extract_mascot_payload(guest_post_off.text)
        assert payload_off["chat_enabled"] is False
        assert payload_off["project_title"] == "参数提示语博客"
        assert payload_off["post_title"] == "参数化提示语测试文章"
        assert payload_off["post_words"] == len(post_body)
        assert payload_off["tips"] == [
            "当前阅读进度 {progress}%",
            "正在浏览「{heading}」—— 来自 {site}",
            "本文共 {words} 字，{time}好！",
        ]
        assert all(not str(t).startswith("#") for t in payload_off["tips"])
        assert "管理员注释" not in guest_post_off.text

        assert (
            admin_client.patch(
                f"/api/admin/projects/{pid}/extensions/mascot",
                json={"config": {"chat_access": "admin", "api_key": "sk-dock-visibility-test"}},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        guest_admin_only = guest_client.get(f"/projects/{slug}/posts/tips-post")
        assert guest_admin_only.status_code == 200
        assert "sf-mascot-dock" not in guest_admin_only.text
        assert _extract_mascot_payload(guest_admin_only.text)["chat_enabled"] is False

        admin_view = admin_client.get(f"/projects/{slug}/posts/tips-post")
        assert admin_view.status_code == 200
        assert "sf-mascot-dock" in admin_view.text
        assert "data-mascot-chat-reset" in admin_view.text
        assert "data-mascot-chat-toggle" not in admin_view.text
        assert "data-mascot-chat-close" not in admin_view.text
        assert "sf-mascot-ai-head" not in admin_view.text
        assert _extract_mascot_payload(admin_view.text)["chat_enabled"] is True

        assert (
            admin_client.patch(
                f"/api/admin/projects/{pid}/extensions/mascot",
                json={"config": {"chat_access": "public"}},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        guest_public = guest_client.get(f"/projects/{slug}/posts/tips-post")
        assert guest_public.status_code == 200
        assert "sf-mascot-dock" in guest_public.text
        assert "data-mascot-chat-reset" in guest_public.text
        assert _extract_mascot_payload(guest_public.text)["chat_enabled"] is True


def test_strict_svg_sanitizer_accepts_clean_and_rejects_dangerous() -> None:
    cleaned = sanitize_svg(CLEAN_GRADIENT_SVG)
    root = ET.fromstring(cleaned)
    assert root.tag.endswith("svg")
    assert root.attrib.get("viewBox") == "0 0 64 64"

    bad_payloads = [
        b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"><circle cx="10" cy="10" r="5"/></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><foreignObject><div>x</div></foreignObject></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><use href="#x"/></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><image href="https://evil.example/a.png"/></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><style>body{background:red}</style></svg>',
        b'<!DOCTYPE svg [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><svg>&xxe;</svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><circle fill="javascript:alert(1)" cx="5" cy="5" r="5"/></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><circle fill="url(https://evil.example/p#a)" cx="5" cy="5" r="5"/></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg">' + (b" " * (256 * 1024 + 10)) + b"</svg>",
        b'<svg xmlns="http://www.w3.org/2000/svg">\x00<circle cx="5" cy="5" r="5"/></svg>',
        b"\xff\xfe<svg></svg>",
    ]
    for payload in bad_payloads:
        with pytest.raises(InvalidUpload):
            sanitize_svg(payload)


def test_mascot_avatar_rgba_webp_svg_csp_gates_and_orphan_cleanup() -> None:
    with TestClient(app) as admin_client, TestClient(app) as guest_client:
        csrf = login(admin_client)
        blog = create_app(admin_client, csrf, "blog", "头像测试博客").json()["project"]
        pid, slug = blog["id"], blog["slug"]

        assert (
            admin_client.post(
                f"/api/admin/projects/{pid}/extensions/mascot/install",
                json={"enabled": True},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )

        bad_svg_up = admin_client.post(
            f"/api/admin/projects/{pid}/extensions/mascot/media",
            files={
                "file": (
                    "evil.svg",
                    b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
                    "image/svg+xml",
                )
            },
            data={"kind": "avatar"},
            headers=auth_headers(csrf),
        )
        assert bad_svg_up.status_code == 422

        png_up = admin_client.post(
            f"/api/admin/projects/{pid}/extensions/mascot/media",
            files={"file": ("avatar.png", _make_rgba_png(), "image/png")},
            data={"kind": "avatar"},
            headers=auth_headers(csrf),
        )
        assert png_up.status_code == 200
        webp_url = png_up.json()["url"]
        assert re.match(rf"^/media/blog/{slug}/avatar-[0-9a-f]{{16}}\.webp$", webp_url)

        webp_resp = guest_client.get(webp_url)
        assert webp_resp.status_code == 200
        assert webp_resp.headers["content-type"].startswith("image/webp")
        with Image.open(io.BytesIO(webp_resp.content)) as saved_img:
            assert saved_img.mode == "RGBA"
            corner = saved_img.getpixel((0, 0))
            center = saved_img.getpixel((16, 16))
            assert isinstance(corner, tuple) and corner[3] == 0
            assert isinstance(center, tuple) and center[3] > 100

        assert (
            admin_client.patch(
                f"/api/admin/projects/{pid}/extensions/mascot",
                json={"config": {"custom_avatar": webp_url}},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )

        svg_up = admin_client.post(
            f"/api/admin/projects/{pid}/extensions/mascot/media",
            files={"file": ("avatar.svg", CLEAN_GRADIENT_SVG, "image/svg+xml")},
            data={"kind": "avatar"},
            headers=auth_headers(csrf),
        )
        assert svg_up.status_code == 200
        svg_url = svg_up.json()["url"]
        assert re.match(rf"^/media/blog/{slug}/avatar-[0-9a-f]{{16}}\.svg$", svg_url)

        assert (
            admin_client.patch(
                f"/api/admin/projects/{pid}/extensions/mascot",
                json={"config": {"custom_avatar": svg_url}},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert guest_client.get(webp_url).status_code == 404

        svg_resp = guest_client.get(svg_url)
        assert svg_resp.status_code == 200
        assert svg_resp.headers["content-type"].startswith("image/svg+xml")
        assert svg_resp.headers["content-security-policy"] == "default-src 'none'; sandbox"
        assert svg_resp.headers["x-content-type-options"] == "nosniff"
        assert svg_resp.headers["content-disposition"] == "inline"

        blog_page = guest_client.get(f"/projects/{slug}/")
        assert blog_page.status_code == 200
        assert f'src="{svg_url}"' in blog_page.text
        assert 'referrerpolicy="no-referrer"' in blog_page.text
        assert "sf-mascot-svg" not in blog_page.text

        assert (
            admin_client.patch(
                f"/api/admin/projects/{pid}",
                json={"visible": False},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert guest_client.get(svg_url).status_code == 404
        assert admin_client.get(svg_url).status_code == 200

        assert (
            admin_client.patch(
                f"/api/admin/projects/{pid}",
                json={"visible": True, "password": "blog-avatar-pass"},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert guest_client.get(svg_url).status_code == 401
        assert (
            guest_client.post(
                f"/projects/{slug}/unlock",
                data={"password": "blog-avatar-pass"},
                follow_redirects=False,
            ).status_code
            == 303
        )
        assert guest_client.get(svg_url).status_code == 200

        assert (
            admin_client.delete(
                f"/api/admin/projects/{pid}/extensions/mascot",
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert admin_client.get(svg_url).status_code == 404


def test_mascot_secret_redaction_preservation_and_explicit_clear() -> None:
    secret = "sk-live-mascot-secret-9f8e7d6c"
    with TestClient(app) as client:
        csrf = login(client)
        blog = create_app(client, csrf, "blog", "密钥脱敏博客").json()["project"]
        space = create_app(client, csrf, "space", "密钥脱敏空间").json()["project"]

        for proj in (blog, space):
            pid = proj["id"]
            inst = client.post(
                f"/api/admin/projects/{pid}/extensions/mascot/install",
                json={
                    "enabled": True,
                    "config": {
                        "character": "gemini_cat",
                        "chat_access": "public",
                        "api_key": secret,
                    },
                },
                headers=auth_headers(csrf),
            )
            assert inst.status_code == 200
            ext_data = inst.json()["extension"]
            assert secret not in inst.text
            assert ext_data["config"]["api_key"] == ""
            assert ext_data["secrets_set"] == {"api_key": True}

        list_resp = client.get("/api/admin/projects", headers=auth_headers(csrf))
        assert list_resp.status_code == 200
        assert secret not in list_resp.text

        for proj in (blog, space):
            pid, slug = proj["id"], proj["slug"]
            detail_resp = client.get(f"/api/admin/projects/{pid}", headers=auth_headers(csrf))
            assert detail_resp.status_code == 200
            assert secret not in detail_resp.text

            exts_resp = client.get(f"/api/admin/projects/{pid}/extensions", headers=auth_headers(csrf))
            assert exts_resp.status_code == 200
            assert secret not in exts_resp.text
            mascot_item = next(e for e in exts_resp.json()["extensions"] if e["id"] == "mascot")
            assert mascot_item["secrets_set"] == {"api_key": True}

            admin_page = client.get(f"/admin/projects/{pid}")
            assert admin_page.status_code == 200
            assert secret not in admin_page.text

            public_page = client.get(f"/projects/{slug}/")
            assert public_page.status_code == 200
            assert secret not in public_page.text
            assert '"chat_enabled": true' in public_page.text

        partial = client.patch(
            f"/api/admin/projects/{blog['id']}/extensions/mascot",
            json={"config": {"greeting": "更新后的欢迎语", "api_key": ""}},
            headers=auth_headers(csrf),
        )
        assert partial.status_code == 200
        assert partial.json()["extension"]["secrets_set"] == {"api_key": True}
        assert partial.json()["extension"]["config"]["greeting"] == "更新后的欢迎语"

        blog_detail = client.get(f"/api/admin/projects/{blog['id']}", headers=auth_headers(csrf)).json()[
            "project"
        ]
        redacted_content = json.loads(blog_detail["content"])
        assert redacted_content["extensions"]["mascot"]["config"]["api_key"] == ""
        redacted_content["description"] = "保留密钥的描述更新"
        patched_blog = client.patch(
            f"/api/admin/projects/{blog['id']}",
            json={"content": json.dumps(redacted_content, ensure_ascii=False)},
            headers=auth_headers(csrf),
        )
        assert patched_blog.status_code == 200
        assert secret not in patched_blog.text
        after_content_patch = client.get(
            f"/api/admin/projects/{blog['id']}/extensions", headers=auth_headers(csrf)
        ).json()["extensions"]
        mascot_after = next(e for e in after_content_patch if e["id"] == "mascot")
        assert mascot_after["secrets_set"] == {"api_key": True}

        cleared = client.patch(
            f"/api/admin/projects/{blog['id']}/extensions/mascot",
            json={"config": {"clear_api_key": True}},
            headers=auth_headers(csrf),
        )
        assert cleared.status_code == 200
        assert cleared.json()["extension"]["secrets_set"] == {"api_key": False}
        public_after_clear = client.get(f"/projects/{blog['slug']}/")
        assert '"chat_enabled": false' in public_after_clear.text


def test_icons_zero_emoji_and_css_checkmark_hygiene() -> None:
    new_icons = (
        "sliders",
        "package",
        "download",
        "message-circle",
        "send",
        "square",
        "rotate-ccw",
        "move",
        "megaphone",
        "paintbrush",
        "bot",
        "alert-circle",
        "code",
        "layout-grid",
        "maximize",
        "minimize",
        "history",
        "brain",
        "chevron-right",
    )
    tmpl = templates.env.from_string('{% import "icons.html" as icons %}{{ icons.icon(name, 16) }}')
    puzzle_svg = tmpl.render(name="puzzle")
    for icon_name in new_icons:
        rendered = tmpl.render(name=icon_name)
        assert rendered.startswith("<svg ")
        assert rendered != puzzle_svg
    unknown_svg = tmpl.render(name="totally-nonexistent-icon")
    assert unknown_svg == puzzle_svg

    app_css = (APP_DIR / "static" / "css" / "app.css").read_text(encoding="utf-8")
    assert 'content: "✓"' not in app_css
    assert "✓" not in app_css

    emoji_hits: list[tuple[str, int, str]] = []
    for path in sorted(APP_DIR.rglob("*")):
        if not path.is_file() or "vendor" in path.parts:
            continue
        if path.suffix not in {".py", ".html", ".css", ".js"}:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            found = EMOJI_RE.findall(line)
            if found:
                emoji_hits.append((str(path.relative_to(APP_DIR)), lineno, "".join(found)))
    assert emoji_hits == []


def test_mascot_ux_tools_centered_dock_clamping_and_ai_fade() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        blog = create_app(client, csrf, "blog", "看板娘交互体验博客").json()["project"]
        pid, slug = blog["id"], blog["slug"]
        assert (
            client.post(
                f"/api/admin/projects/{pid}/posts",
                json={"title": "体验验证文章", "slug": "ux-post", "body": "正文内容"},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert (
            client.post(
                f"/api/admin/projects/{pid}/extensions/mascot/install",
                json={
                    "enabled": True,
                    "config": {
                        "character": "dafeiyu",
                        "draggable": True,
                        "position": "right",
                        "chat_access": "public",
                        "api_key": "sk-ux-test-key",
                    },
                },
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )

        for url in (f"/projects/{slug}/", f"/projects/{slug}/posts/ux-post"):
            page = client.get(url)
            assert page.status_code == 200
            assert "data-mascot-reset" not in page.text
            assert "blog.ext.mascot.reset_pos" not in page.text
            assert "bubble-align-" not in page.text
            assert "data-mascot-zoom" in page.text
            assert "data-mascot-top" in page.text
            assert "data-mascot-toggle" in page.text

    css_text = (APP_DIR / "static" / "css" / "blog_ext_mascot.css").read_text(encoding="utf-8")
    assert "bubble-align-left" not in css_text
    assert "bubble-align-right" not in css_text
    assert "dock-align-left" not in css_text
    assert "dock-align-right" not in css_text
    assert "sfMascotPop" not in css_text
    assert "--sf-bubble-shift" in css_text
    assert "--sf-bubble-arrow-x" in css_text
    assert "--sf-dock-shift" in css_text
    assert "width: 148px;" in css_text
    assert "max-width: min(260px, calc(100vw - 40px));" in css_text
    assert "max-width: min(332px, calc(100vw - 40px));" in css_text
    assert "max-width: calc(100vw - 40px);" in css_text
    assert "width: min(268px, calc(100vw - 40px));" in css_text
    assert "@starting-style" in css_text
    assert "transition-behavior: allow-discrete;" in css_text
    assert ".sf-mascot-bubble.is-faded" in css_text
    assert ".sf-mascot-bubble::before" in css_text

    js_text = (APP_DIR / "static" / "js" / "blog_ext_mascot.js").read_text(encoding="utf-8")
    assert "data-mascot-reset" not in js_text
    assert "clearCustomPosition" not in js_text
    assert "bubble-align-" not in js_text
    assert "dock-align-" not in js_text
    assert "VIEWPORT_MARGIN = 20" in js_text
    assert "document.documentElement.clientWidth" in js_text
    assert "document.documentElement.clientHeight" in js_text
    assert "computeCenteredShift" in js_text
    assert "positionDock" in js_text
    assert "AI_READ_FADE_DELAY = 8000" in js_text
    assert "AI_LEAVE_FADE_DELAY = 1600" in js_text
    assert "revealAiBubble" in js_text
    assert "ResizeObserver" in js_text

    i18n_text = (APP_DIR / "static" / "js" / "i18n.js").read_text(encoding="utf-8")
    assert "blog.ext.mascot.reset_pos" not in i18n_text

    admin_ext_js = (APP_DIR / "static" / "js" / "extensions_admin.js").read_text(encoding="utf-8")
    assert "ext-code-editor" in admin_ext_js
    assert "ext-line-gutter" in admin_ext_js
    assert "ext-line-gutter-inner" in admin_ext_js
    assert "ext-line-mirror" in admin_ext_js
    assert "data-line-editor" in admin_ext_js
    assert "syncLineNumbers" in admin_ext_js
    assert "cleanupLineEditors" in admin_ext_js

    app_css = (APP_DIR / "static" / "css" / "app.css").read_text(encoding="utf-8")
    assert ".ext-code-editor" in app_css
    assert ".ext-line-gutter" in app_css
    assert ".ext-line-gutter-inner" in app_css
    assert ".ext-line-num.is-comment" in app_css
    assert ".ext-line-num.is-active" in app_css
    assert ".ext-line-mirror" in app_css


def test_mascot_default_copy_is_scope_neutral() -> None:
    from app.extensions.mascot import _LEGACY_V4_DEFAULT_TIPS, DEFAULT_GREETING, DEFAULT_TIPS, MascotExtension

    for text in [DEFAULT_GREETING, *DEFAULT_TIPS]:
        assert "文章" not in text
        assert "博客" not in text
    assert "欢迎来逛逛" in DEFAULT_GREETING
    assert any("有什么想了解的可以问我" in line for line in DEFAULT_TIPS)
    ext = MascotExtension()
    assert ext.normalize_config({"tips": list(_LEGACY_V4_DEFAULT_TIPS)}, strict=False)["tips"] == DEFAULT_TIPS
