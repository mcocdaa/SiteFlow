import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

from app import store
from app.main import app
from app.models import Project
from app.plugins import registry
from app.surface import AUDIENCES, CAPABILITIES, StaticSurface, SurfaceItem, SurfaceMeta, SurfaceProvider
from tests.test_apps import create_app
from tests.test_flow import auth_headers, login


def _surface(project_id: int, sub: str = "") -> Any:
    config = app.state.config
    request: Any = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(config=config)))
    with store.init(config)() as db:
        project = db.get(Project, project_id)
        assert project is not None
        plugin = registry.get(project.type)
        assert plugin is not None
        provider: SurfaceProvider = plugin  # type: ignore[assignment]
        return provider.surface(request, project, db, sub=sub)


def _save(client: TestClient, csrf: str, project_id: int, content: dict) -> None:
    response = client.patch(
        f"/api/admin/projects/{project_id}",
        json={"content": json.dumps(content)},
        headers=auth_headers(csrf),
    )
    assert response.status_code == 200, response.text


def test_all_apps_provide_surface_capabilities() -> None:
    for plugin in registry.all_apps():
        assert callable(getattr(plugin, "surface", None)), plugin.type


def test_space_surface() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        space = create_app(client, csrf, "space", "主空间").json()["project"]
        child = create_app(client, csrf, "blog", "子博客", parent_id=space["id"]).json()["project"]
        surface = _surface(space["id"])
        assert surface.capabilities == {"has_children", "has_items", "supports_layout"}
        assert surface.capabilities <= CAPABILITIES
        assert surface.meta.type == "space"
        assert [item.key for item in surface.items("visitor")] == [child["slug"]]
        assert surface.context("ai")["children"] == ["子博客"]
        child_surface = _surface(child["id"])
        assert child_surface.meta.parent_chain == (space["slug"],)
        for audience in AUDIENCES:
            assert surface.context(audience)["title"] == "主空间"


def test_space_surface_external_link_urls() -> None:
    public_external_url = "https://open.example.com/docs"
    locked_external_url = "https://secret.example.com/vault"
    with TestClient(app) as client:
        csrf = login(client)
        space = create_app(client, csrf, "space", "外链测试空间").json()["project"]
        unlocked_resp = client.post(
            "/api/admin/projects/link",
            json={
                "url": public_external_url,
                "title": "公开外链文档",
                "description": "公开外部地址",
                "parent_id": space["id"],
            },
            headers=auth_headers(csrf),
        )
        assert unlocked_resp.status_code == 200, unlocked_resp.text
        unlocked_link = unlocked_resp.json()["project"]

        locked_resp = client.post(
            "/api/admin/projects/link",
            json={
                "url": locked_external_url,
                "title": "加锁外链入口",
                "description": "受密码保护的外链",
                "parent_id": space["id"],
            },
            headers=auth_headers(csrf),
        )
        assert locked_resp.status_code == 200, locked_resp.text
        locked_link = locked_resp.json()["project"]
        assert (
            client.patch(
                f"/api/admin/projects/{locked_link['id']}",
                json={"password": "LinkPass99"},
                headers=auth_headers(csrf),
            ).status_code
            == 200
        )

        assert client.get(f"/projects/{unlocked_link['slug']}/", follow_redirects=False).status_code == 404

        surface = _surface(space["id"])
        for audience in ("visitor", "ai", "plugin"):
            items_by_key = {item.key: item for item in surface.items(audience)}
            assert items_by_key[unlocked_link["slug"]].url == public_external_url
            assert items_by_key[locked_link["slug"]].url == f"/projects/{locked_link['slug']}/"
            assert all(locked_external_url not in item.url for item in surface.items(audience))
            assert locked_external_url not in json.dumps(surface.context(audience), ensure_ascii=False)


def test_blog_surface_post_context() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        blog = create_app(client, csrf, "blog", "博客").json()["project"]
        body = "正文" * 2000
        long_excerpt_body = "第一段用于自动摘录的正文内容。" + "详情" * 120
        _save(
            client,
            csrf,
            blog["id"],
            {
                "title": "我的博客",
                "posts": [
                    {
                        "title": "第一篇",
                        "slug": "first",
                        "date": "2026-11-24",
                        "tags": ["t"],
                        "summary": "手动摘要",
                        "body": body,
                    },
                    {
                        "title": "无摘要篇",
                        "slug": "second",
                        "date": "2026-11-20",
                        "tags": ["随笔"],
                        "body": long_excerpt_body,
                    },
                ],
            },
        )
        listing = _surface(blog["id"])
        assert listing.capabilities == {"has_content", "has_posts", "has_items", "supports_layout"}
        assert listing.meta.title == "我的博客"
        assert [item.url for item in listing.items("visitor")] == [
            f"/projects/{blog['slug']}/posts/first",
            f"/projects/{blog['slug']}/posts/second",
        ]
        assert [item.date for item in listing.items("visitor")] == ["2026-11-24", "2026-11-20"]
        assert [item.date for item in listing.items("ai")] == ["2026-11-24", "2026-11-20"]
        assert listing.items("visitor")[1].summary == ""
        ai_second_summary = listing.items("ai")[1].summary
        assert ai_second_summary.startswith("第一段用于自动摘录的正文内容。")
        assert ai_second_summary.endswith("…")
        assert len(ai_second_summary) <= 160
        assert "post" not in listing.context("ai")
        post = _surface(blog["id"], sub="first")
        assert post.meta.url.endswith("/posts/first")
        assert len(post.context("ai")["post"]["body"]) == 1500
        assert post.context("visitor")["post"]["body"] == body


def test_resume_surface_items_respect_ai_visibility() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        resume = create_app(client, csrf, "resume", "隐私简历").json()["project"]
        _save(
            client,
            csrf,
            resume["id"],
            {
                "basics": {"name": "李雷", "email": "lilei@example.com"},
                "work": [{"name": "星云科技", "position": "架构师", "summary": "负责网关"}],
                "education": [{"institution": "复旦大学", "area": "软件工程"}],
                "projects": [{"name": "SiteFlow", "description": "制品画廊"}],
                "skills": [{"name": "Python", "keywords": ["FastAPI"]}],
                "ai_visibility": {
                    "contact": False,
                    "location": False,
                    "work": False,
                    "education": True,
                    "projects": True,
                    "skills": False,
                },
            },
        )
        surface = _surface(resume["id"])
        assert [item.kind for item in surface.items("visitor")] == ["work", "education", "projects", "skills"]
        assert [item.kind for item in surface.items("admin")] == ["work", "education", "projects", "skills"]
        assert [item.kind for item in surface.items("ai")] == ["education", "projects"]
        assert [item.kind for item in surface.items("plugin")] == ["education", "projects"]
        ai_titles = [item.title for item in surface.items("ai")]
        assert "星云科技" not in ai_titles
        assert "Python" not in ai_titles


def test_resume_ai_context_hides_contact() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        resume = create_app(client, csrf, "resume", "简历").json()["project"]
        _save(
            client,
            csrf,
            resume["id"],
            {
                "basics": {"name": "张三", "email": "a@example.com", "phone": "123", "summary": "工程师"},
                "work": [{"name": "公司", "position": "开发", "summary": "写代码"}],
            },
        )
        surface = _surface(resume["id"])
        assert surface.capabilities == {"has_content", "is_personal_profile", "has_items"}
        assert surface.context("visitor")["basics"]["email"] == "a@example.com"
        ai = surface.context("ai")
        plugin_ctx = surface.context("plugin")
        assert plugin_ctx == ai
        assert "email" not in ai["basics"] and "phone" not in ai["basics"]
        assert "a@example.com" not in json.dumps(ai, ensure_ascii=False)
        assert ai["basics"]["name"] == "张三"
        assert [item.title for item in surface.items("ai")] == ["公司"]
        assert [item.title for item in surface.items("plugin")] == ["公司"]

        admin_html = client.get(f"/admin/projects/{resume['id']}").text
        resume_part = admin_html.split('id="resume-extensions"')[0]
        assert "插件隐私控制" in resume_part
        assert "联系方式对插件可见" in resume_part
        assert "所在地对插件可见" in resume_part
        assert "对插件可见" in resume_part
        assert "看板娘" not in resume_part
        assert "AI 隐私控制" not in resume_part


def test_static_surface_plugin_and_ai_audience_fallback() -> None:
    meta = SurfaceMeta(type="custom", slug="demo", title="Demo", description="", url="/projects/demo/")
    ai_only = StaticSurface(
        meta=meta,
        capabilities=frozenset(),
        contexts={"visitor": {"k": "v"}, "ai": {"k": "filtered_ai"}},
    )
    assert ai_only.context("plugin") == {"k": "filtered_ai"}
    assert ai_only.context("ai") == {"k": "filtered_ai"}
    assert ai_only.context("admin") == {"k": "v"}

    plugin_only = StaticSurface(
        meta=meta,
        capabilities=frozenset(),
        contexts={"visitor": {"k": "v"}, "plugin": {"k": "filtered_plugin"}},
    )
    assert plugin_only.context("ai") == {"k": "filtered_plugin"}
    assert plugin_only.context("plugin") == {"k": "filtered_plugin"}

    visitor_only = StaticSurface(
        meta=meta,
        capabilities=frozenset(),
        contexts={"visitor": {"k": "v"}},
    )
    assert visitor_only.context("plugin") == {"k": "v"}
    assert visitor_only.context("ai") == {"k": "v"}

    base_item = SurfaceItem(key="pub", title="公开条目", url="/p/pub")
    filtered_item = SurfaceItem(key="ai", title="精简条目", url="/p/ai")
    ai_items_surface = StaticSurface(
        meta=meta,
        capabilities=frozenset(),
        contexts={},
        item_list=(base_item,),
        audience_items={"visitor": (base_item,), "ai": (filtered_item,)},
    )
    assert ai_items_surface.items("visitor") == (base_item,)
    assert ai_items_surface.items("admin") == (base_item,)
    assert ai_items_surface.items("ai") == (filtered_item,)
    assert ai_items_surface.items("plugin") == (filtered_item,)

    plugin_items_surface = StaticSurface(
        meta=meta,
        capabilities=frozenset(),
        contexts={},
        audience_items={"visitor": (base_item,), "plugin": (filtered_item,)},
    )
    assert plugin_items_surface.items("ai") == (filtered_item,)
    assert plugin_items_surface.items("plugin") == (filtered_item,)

    fallback_items_surface = StaticSurface(
        meta=meta,
        capabilities=frozenset(),
        contexts={},
        item_list=(base_item,),
    )
    assert fallback_items_surface.items("ai") == (base_item,)
    assert fallback_items_surface.items("plugin") == (base_item,)


def test_resume_plugin_has_no_mascot_coupling() -> None:
    resume_root = Path("app/plugins/resume")
    checked = 0
    for path in sorted(resume_root.rglob("*")):
        if not path.is_file() or path.suffix not in {".py", ".html", ".js", ".css"}:
            continue
        checked += 1
        text = path.read_text(encoding="utf-8")
        assert "mascot" not in text.lower(), path
        assert "看板娘" not in text, path
    assert checked >= 3


def test_surface_module_has_no_page_type_branches() -> None:
    source = Path("app/surface.py").read_text(encoding="utf-8")
    for name in ("space", "blog", "resume", "mascot"):
        assert f'"{name}"' not in source
