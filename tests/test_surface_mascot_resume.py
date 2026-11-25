import ast
import json
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.extensions import mascot_chat
from app.extensions.base import BaseExtension, TargetType, capabilities_for_target
from app.extensions.mascot import (
    DEFAULT_GREETING,
    DEFAULT_SYSTEM_PROMPT,
    DEFAULT_TIPS,
    MascotExtension,
    resolve_effective_config,
    resolve_effective_defaults,
)
from app.extensions.packs import PackExtension
from app.extensions.post_background import PostBackgroundExtension
from app.extensions.post_cover import PostCoverExtension
from app.extensions.registry import (
    active_extensions,
    all_extensions,
    build_admin_catalog,
    normalize_extensions,
)
from app.extensions.resume_style import ResumeStyleExtension
from app.extensions.space_background import SpaceBackgroundExtension
from app.extensions.space_banner import SpaceBannerExtension
from app.extensions.space_layout import SpaceLayoutExtension
from app.main import app
from app.models import Project
from app.plugins.base import InvalidContent
from app.plugins.resume.plugin import DEFAULT_AI_VISIBILITY
from app.plugins.resume.plugin import validate_content as validate_resume
from app.surface import Capability, StaticSurface, SurfaceMeta
from tests.test_apps import create_app
from tests.test_flow import ORIGIN, auth_headers, login
from tests.test_mascot_chat import _parse_sse_events, _patch_upstream
from tests.test_mascot_v2 import _extract_mascot_payload


def _sample_resume_payload(ai_visibility: dict[str, Any] | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {
        "basics": {
            "name": "林深",
            "label": "首席系统架构师",
            "email": "secret-lin@example.com",
            "phone": "138-0013-8000",
            "url": "https://linshen.dev",
            "summary": "专注分布式系统、零信任沙箱与高并发网关架构。",
            "location": {"city": "秘密城市上海", "region": "浦东新区", "countryCode": "CN"},
            "profiles": [{"network": "GitHub", "username": "linshen", "url": "https://github.com/linshen"}],
        },
        "work": [
            {
                "name": "星云科技",
                "position": "首席架构师",
                "startDate": "2022-03",
                "endDate": "至今",
                "summary": "主导零信任沙箱托管平台架构设计。",
                "highlights": ["日均拦截十万级异常制品"],
            }
        ],
        "education": [
            {
                "institution": "上海交通大学",
                "area": "计算机科学与技术",
                "studyType": "硕士",
                "startDate": "2014-09",
                "endDate": "2017-06",
            }
        ],
        "projects": [
            {
                "name": "SiteFlow 制品画廊",
                "description": "零构建个人作品与插件平台。",
                "keywords": ["FastAPI", "SQLite"],
                "highlights": ["实现 PageSurface 契约架构"],
            }
        ],
        "skills": [
            {"name": "系统架构", "keywords": ["Python", "Rust", "Kubernetes"]},
        ],
    }
    if ai_visibility is not None:
        data["ai_visibility"] = ai_visibility
    return data


def test_mascot_chat_resume_context_privacy_and_visibility_toggles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_key = "sk-resume-mascot-test-secret"
    with TestClient(app) as admin_client, TestClient(app) as guest_client:
        csrf = login(admin_client)
        resume = create_app(admin_client, csrf, "resume", "林深简历").json()["project"]
        pid, slug = resume["id"], resume["slug"]
        chat_url = f"/api/projects/{slug}/mascot/chat"

        save_resp = admin_client.patch(
            f"/api/admin/projects/{pid}",
            json={"content": json.dumps(_sample_resume_payload(), ensure_ascii=False)},
            headers=auth_headers(csrf),
        )
        assert save_resp.status_code == 200
        saved_content = json.loads(save_resp.json()["project"]["content"])
        assert saved_content["ai_visibility"] == DEFAULT_AI_VISIBILITY

        install_resp = admin_client.post(
            f"/api/admin/projects/{pid}/extensions/mascot/install",
            json={
                "enabled": True,
                "config": {
                    "character": "dafeiyu",
                    "chat_access": "public",
                    "api_key": secret_key,
                    "rate_limit_per_min": 60,
                },
            },
            headers=auth_headers(csrf),
        )
        assert install_resp.status_code == 200

        admin_html = admin_client.get(f"/admin/projects/{pid}").text
        assert 'data-ext-card="mascot"' in admin_html
        assert 'data-mascot-skin-tpl="dafeiyu"' in admin_html
        for key in ("contact", "location", "work", "education", "projects", "skills"):
            assert f'data-ai-vis="{key}"' in admin_html
        assert 'role="switch"' in admin_html

        public_page = guest_client.get(f"/projects/{slug}/")
        assert public_page.status_code == 200
        assert "/static/css/blog_ext_mascot.css" in public_page.text
        assert "/static/js/blog_ext_mascot.js" in public_page.text
        assert "has-mascot" in public_page.text
        assert "sf-mascot-dock" in public_page.text
        assert 'data-mascot-character="dafeiyu"' in public_page.text
        assert "secret-lin@example.com" in public_page.text
        assert "138-0013-8000" in public_page.text
        assert "秘密城市上海" in public_page.text
        assert secret_key not in public_page.text
        payload = _extract_mascot_payload(public_page.text)
        assert payload["page"] == "resume"
        assert payload["chat_enabled"] is True
        assert "简历" in str(payload["greeting"])

        captured = _patch_upstream(monkeypatch)
        chat_resp = guest_client.post(
            chat_url,
            json={"messages": [{"role": "user", "content": "介绍一下候选人的经历与技能"}]},
            headers=ORIGIN,
        )
        assert chat_resp.status_code == 200
        events = _parse_sse_events(chat_resp.text)
        assert events[-1] == "[DONE]"
        assert len(captured) == 1
        sys_prompt = captured[0]["json"]["system"]
        assert "简历" in sys_prompt
        assert "绝不编造" in sys_prompt
        assert "林深" in sys_prompt
        assert "星云科技" in sys_prompt
        assert "上海交通大学" in sys_prompt
        assert "SiteFlow 制品画廊" in sys_prompt
        assert "Kubernetes" in sys_prompt
        assert "secret-lin@example.com" not in sys_prompt
        assert "138-0013-8000" not in sys_prompt
        assert "秘密城市上海" not in sys_prompt
        assert "浦东新区" not in sys_prompt

        hidden_sections_payload = _sample_resume_payload(
            {
                "contact": False,
                "location": False,
                "work": False,
                "education": True,
                "projects": True,
                "skills": False,
            }
        )
        assert (
            admin_client.patch(
                f"/api/admin/projects/{pid}",
                json={"content": json.dumps(hidden_sections_payload, ensure_ascii=False)},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        captured_hidden = _patch_upstream(monkeypatch)
        resp_hidden = guest_client.post(
            chat_url,
            json={"messages": [{"role": "user", "content": "说说项目与工作"}]},
            headers=ORIGIN,
        )
        assert resp_hidden.status_code == 200
        sys_hidden = captured_hidden[0]["json"]["system"]
        assert "星云科技" not in sys_hidden
        assert "Kubernetes" not in sys_hidden
        assert "上海交通大学" in sys_hidden
        assert "SiteFlow 制品画廊" in sys_hidden
        assert "secret-lin@example.com" not in sys_hidden

        visitor_after_hide = guest_client.get(f"/projects/{slug}/")
        assert visitor_after_hide.status_code == 200
        assert "星云科技" in visitor_after_hide.text
        assert "Kubernetes" in visitor_after_hide.text

        open_privacy_payload = _sample_resume_payload(
            {
                "contact": True,
                "location": True,
                "work": True,
                "education": True,
                "projects": True,
                "skills": True,
            }
        )
        assert (
            admin_client.patch(
                f"/api/admin/projects/{pid}",
                json={"content": json.dumps(open_privacy_payload, ensure_ascii=False)},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        captured_open = _patch_upstream(monkeypatch)
        assert (
            guest_client.post(
                chat_url,
                json={"messages": [{"role": "user", "content": "怎么联系？"}]},
                headers=ORIGIN,
            ).status_code
            == 200
        )
        sys_open = captured_open[0]["json"]["system"]
        assert "secret-lin@example.com" in sys_open
        assert "138-0013-8000" in sys_open
        assert "秘密城市上海" in sys_open

        assert (
            admin_client.patch(
                f"/api/admin/projects/{pid}",
                json={"password": "resume-pass"},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        assert (
            guest_client.post(
                chat_url,
                json={"messages": [{"role": "user", "content": "解锁前"}]},
                headers=ORIGIN,
            ).status_code
            == 401
        )
        assert (
            guest_client.post(
                f"/projects/{slug}/unlock",
                data={"password": "resume-pass"},
                follow_redirects=False,
            ).status_code
            == 303
        )
        assert (
            guest_client.post(
                chat_url,
                json={"messages": [{"role": "user", "content": "解锁后"}]},
                headers=ORIGIN,
            ).status_code
            == 200
        )


def test_resume_ai_visibility_strict_validation() -> None:
    valid = validate_resume(
        json.dumps({"ai_visibility": {"contact": True, "work": False}}),
        strict=True,
    )
    assert valid["ai_visibility"] == {
        "contact": True,
        "location": False,
        "work": False,
        "education": True,
        "projects": True,
        "skills": True,
    }
    for bad in (
        {"ai_visibility": "invalid"},
        {"ai_visibility": ["contact"]},
        {"ai_visibility": {"contact": "true"}},
        {"ai_visibility": {"contact": 1}},
        {"ai_visibility": {"work": 0}},
        {"ai_visibility": {"skills": None}},
    ):
        with pytest.raises(InvalidContent):
            validate_resume(json.dumps(bad), strict=True)


def test_mascot_chat_has_no_page_type_branches_and_generic_context_serializer() -> None:
    source = Path("app/extensions/mascot_chat.py").read_text(encoding="utf-8")
    for literal in ('"blog"', "'blog'", '"space"', "'space'", '"resume"', "'resume'"):
        assert literal not in source
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            left_src = ast.get_source_segment(source, node.left) or ""
            assert "project.type" not in left_src

    music_surface = StaticSurface(
        meta=SurfaceMeta(
            type="music",
            slug="midnight-radio",
            title="深夜电台",
            description="城市夜景精选歌单",
            url="/projects/midnight-radio/",
        ),
        capabilities=frozenset({"has_content", "has_items"}),
        contexts={
            "ai": {
                "title": "深夜电台",
                "mood": "Lo-Fi",
                "tracks": [
                    {"title": "Moonlight", "artist": "Debussy", "tags": ["钢琴", "古典"]},
                    {"title": "Rain", "artist": "Sakamoto"},
                ],
                "notes": "长文本内容" * 1200,
            }
        },
    )
    serialized = mascot_chat._build_page_context(music_surface)
    assert "标题：深夜电台" in serialized
    assert "简介：城市夜景精选歌单" in serialized
    assert "Moonlight" in serialized
    assert "钢琴、古典" in serialized
    assert serialized.count("标题：深夜电台") == 1
    assert len(serialized) <= 3000


def test_capability_matching_and_backward_compatibility() -> None:
    blog_caps = capabilities_for_target("blog")
    space_caps = capabilities_for_target("space")
    resume_caps = capabilities_for_target("resume")
    music_caps: frozenset[Capability] = frozenset({"has_content", "has_items"})
    empty_caps: frozenset[Capability] = frozenset()

    mascot = MascotExtension()
    post_cover = PostCoverExtension()
    post_bg = PostBackgroundExtension()
    space_banner = SpaceBannerExtension()
    space_bg = SpaceBackgroundExtension()
    resume_style = ResumeStyleExtension()

    assert mascot.requires == frozenset()
    for caps in (blog_caps, space_caps, resume_caps, music_caps, empty_caps):
        assert mascot.matches_capabilities(caps) is True

    assert post_cover.requires == frozenset({"has_posts"})
    assert post_bg.requires == frozenset({"has_posts"})
    for ext in (post_cover, post_bg):
        assert ext.matches_capabilities(blog_caps) is True
        assert ext.matches_capabilities(space_caps) is False
        assert ext.matches_capabilities(resume_caps) is False
        assert ext.matches_capabilities(music_caps) is False

    assert space_banner.requires == frozenset({"has_children"})
    assert space_bg.requires == frozenset({"has_children"})
    for space_ext in (space_banner, space_bg):
        assert space_ext.matches_capabilities(space_caps) is True
        assert space_ext.matches_capabilities(blog_caps) is False
        assert space_ext.matches_capabilities(resume_caps) is False
        assert space_ext.matches_capabilities(music_caps) is False

    space_layout = SpaceLayoutExtension()
    assert space_layout.requires == frozenset({"has_items", "supports_layout"})
    assert space_layout.matches_capabilities(space_caps) is True
    assert space_layout.matches_capabilities(blog_caps) is False
    assert space_layout.matches_capabilities(resume_caps) is False
    assert space_layout.matches_capabilities(music_caps) is False

    assert resume_style.requires == frozenset({"is_personal_profile"})
    assert resume_style.matches_capabilities(resume_caps) is True
    assert resume_style.matches_capabilities(blog_caps) is False
    assert resume_style.matches_capabilities(space_caps) is False
    assert resume_style.matches_capabilities(music_caps) is False

    assert [e.id for e in all_extensions(capabilities=music_caps)] == ["mascot"]
    assert [e.id for e in all_extensions(capabilities=resume_caps)] == ["mascot", "resume_style"]
    assert [e.id for e in all_extensions(capabilities=blog_caps)] == [
        "post_cover",
        "post_background",
        "mascot",
    ]
    assert [e.id for e in all_extensions(capabilities=space_caps)] == [
        "mascot",
        "space_banner",
        "space_background",
        "space_layout",
    ]

    music_catalog = build_admin_catalog({}, capabilities=music_caps)
    assert [item["id"] for item in music_catalog] == ["mascot"]
    assert music_catalog[0]["requires"] == []

    normalized_music = normalize_extensions(
        {
            "mascot": {"installed": True, "enabled": True},
            "post_cover": {"installed": True, "enabled": True},
            "resume_style": {"installed": True, "enabled": True},
        },
        strict=False,
        capabilities=music_caps,
    )
    assert list(normalized_music.keys()) == ["mascot"]
    assert [
        ext.id for ext, _ in active_extensions({"extensions": normalized_music}, capabilities=music_caps)
    ] == ["mascot"]
    with pytest.raises(InvalidContent):
        normalize_extensions(
            {"post_cover": {"installed": True, "enabled": True}},
            strict=True,
            capabilities=resume_caps,
        )

    class LegacyBlogSpaceExt(BaseExtension):
        id = "legacy_bs"
        targets: tuple[TargetType, ...] = ("blog", "space")

    class LegacyResumeOnlyExt(BaseExtension):
        id = "legacy_ro"
        targets: tuple[TargetType, ...] = ("resume",)

    class ExcludeResumeExt(BaseExtension):
        id = "exclude_res"
        requires: frozenset[Capability] = frozenset()
        excludes: frozenset[Capability] = frozenset({"is_personal_profile"})

    legacy_bs = LegacyBlogSpaceExt()
    assert legacy_bs.matches_capabilities(blog_caps) is True
    assert legacy_bs.matches_capabilities(space_caps) is True
    assert legacy_bs.matches_capabilities(resume_caps) is False

    legacy_ro = LegacyResumeOnlyExt()
    assert legacy_ro.matches_capabilities(resume_caps) is True
    assert legacy_ro.matches_capabilities(blog_caps) is False
    assert legacy_ro.matches_capabilities(space_caps) is False

    exclude_res = ExcludeResumeExt()
    assert exclude_res.matches_capabilities(blog_caps) is True
    assert exclude_res.matches_capabilities(space_caps) is True
    assert exclude_res.matches_capabilities(music_caps) is True
    assert exclude_res.matches_capabilities(resume_caps) is False

    pack_ext = PackExtension(
        pack_id="demo-pack",
        pack_name="Demo Pack",
        local_id="badge",
        name="徽章",
        name_en="Badge",
        description="描述",
        description_en="Desc",
        version="1.0.0",
        icon="sparkles",
        targets=("resume",),
        pages=("resume",),
        slot="body_end",
        mount={"tag": "div", "class": "", "aria_label": ""},
        static_css=(),
        static_js=(),
        config_schema=(),
        defaults={},
        int_fields=set(),
    )
    assert pack_ext.requires == frozenset({"is_personal_profile"})
    assert pack_ext.matches_capabilities(resume_caps) is True
    assert pack_ext.matches_capabilities(blog_caps) is False


def test_mascot_three_tier_defaults_and_user_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    blog_def = resolve_effective_defaults("blog")
    space_def = resolve_effective_defaults("space")
    music_def = resolve_effective_defaults("music")
    unknown_def = resolve_effective_defaults("unknown_future_space")
    resume_def = resolve_effective_defaults("resume")

    assert blog_def == space_def == music_def == unknown_def
    for text in [blog_def["greeting"], blog_def["system_prompt"], *blog_def["tips"]]:
        assert "文章" not in text
        assert "博客" not in text

    assert resume_def["greeting"] != blog_def["greeting"]
    assert resume_def["tips"] != blog_def["tips"]
    assert resume_def["system_prompt"] != blog_def["system_prompt"]
    assert "经历" in resume_def["system_prompt"]
    assert "项目" in resume_def["system_prompt"]
    assert "技能" in resume_def["system_prompt"]
    assert "绝不编造" in resume_def["system_prompt"]

    ext = MascotExtension()
    default_cfg = ext.normalize_config(None)
    empty_cfg = {**default_cfg, "greeting": "", "tips": [], "system_prompt": ""}

    for cfg in (default_cfg, empty_cfg):
        res_eff = resolve_effective_config("resume", cfg)
        assert res_eff["greeting"] == resume_def["greeting"]
        assert res_eff["tips"] == resume_def["tips"]
        assert res_eff["system_prompt"] == resume_def["system_prompt"]

        blog_eff = resolve_effective_config("blog", cfg)
        space_eff = resolve_effective_config("space", cfg)
        music_eff = resolve_effective_config("music", cfg)
        assert blog_eff["greeting"] == space_eff["greeting"] == music_eff["greeting"] == DEFAULT_GREETING
        assert blog_eff["tips"] == space_eff["tips"] == music_eff["tips"] == DEFAULT_TIPS
        assert (
            blog_eff["system_prompt"]
            == space_eff["system_prompt"]
            == music_eff["system_prompt"]
            == DEFAULT_SYSTEM_PROMPT
        )

    custom_cfg = {
        **default_cfg,
        "greeting": "站长专属问候语",
        "tips": ["站长专属提示语"],
        "system_prompt": "站长专属系统提示词",
    }
    for page_type in ("resume", "blog", "space", "music"):
        eff = resolve_effective_config(page_type, custom_cfg)
        assert eff["greeting"] == "站长专属问候语"
        assert eff["tips"] == ["站长专属提示语"]
        assert eff["system_prompt"] == "站长专属系统提示词"

    resume_proj = Project(id=1, slug="my-resume", type="resume", title="简历")
    blog_proj = Project(id=2, slug="my-blog", type="blog", title="博客")
    space_proj = Project(id=3, slug="my-space", type="space", title="空间")
    resume_ctx = ext.render_page_context(page="resume", project=resume_proj, content={}, config=default_cfg)
    blog_ctx = ext.render_page_context(page="list", project=blog_proj, content={}, config=default_cfg)
    space_ctx = ext.render_page_context(page="space", project=space_proj, content={}, config=default_cfg)
    assert resume_ctx["greeting"] == resume_def["greeting"]
    assert blog_ctx["greeting"] == space_ctx["greeting"] == DEFAULT_GREETING
    assert blog_ctx["tips"] == space_ctx["tips"]
    assert resume_ctx["tips"] != blog_ctx["tips"]

    resume_custom_ctx = ext.render_page_context(
        page="resume", project=resume_proj, content={}, config=custom_cfg
    )
    assert resume_custom_ctx["greeting"] == "站长专属问候语"
    assert resume_custom_ctx["tips"] == ["站长专属提示语"]

    with TestClient(app) as client:
        csrf = login(client)
        resume = create_app(client, csrf, "resume", "自定义提示词简历").json()["project"]
        assert (
            client.post(
                f"/api/admin/projects/{resume['id']}/extensions/mascot/install",
                json={
                    "enabled": True,
                    "config": {
                        "chat_access": "public",
                        "api_key": "sk-custom-override-key",
                        "greeting": "自定义简历问候",
                        "tips": ["自定义简历提示"],
                        "system_prompt": "只用三句话介绍候选人",
                    },
                },
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )
        captured = _patch_upstream(monkeypatch)
        assert (
            client.post(
                f"/api/projects/{resume['slug']}/mascot/chat",
                json={"messages": [{"role": "user", "content": "介绍一下"}]},
                headers=ORIGIN,
            ).status_code
            == 200
        )
        assert captured[0]["json"]["system"].startswith("只用三句话介绍候选人")


def test_i18n_zh_en_keys_aligned_including_resume_ai_privacy() -> None:
    text = Path("app/static/js/i18n.js").read_text(encoding="utf-8")
    zh_match = re.search(r"zh:\s*\{(.*?)\n\s*\},\s*\n\s*en:\s*\{", text, re.DOTALL)
    en_match = re.search(r"en:\s*\{(.*?)\n\s*\}\s*\n\s*\};", text, re.DOTALL)
    assert zh_match is not None and en_match is not None
    zh_keys = set(re.findall(r'"([^"]+)":', zh_match.group(1)))
    en_keys = set(re.findall(r'"([^"]+)":', en_match.group(1)))
    assert zh_keys == en_keys
    for key in (
        "resume.ai_privacy_title",
        "resume.ai_privacy_hint",
        "resume.ai_visible",
        "resume.ai_vis_contact",
        "resume.ai_vis_location",
    ):
        assert key in zh_keys
