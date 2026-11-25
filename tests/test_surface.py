import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

from app import store
from app.main import app
from app.models import Project
from app.plugins import registry
from app.surface import AUDIENCES, CAPABILITIES, StaticSurface, SurfaceMeta, SurfaceProvider
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


def test_blog_surface_post_context() -> None:
    with TestClient(app) as client:
        csrf = login(client)
        blog = create_app(client, csrf, "blog", "博客").json()["project"]
        body = "正文" * 2000
        _save(
            client,
            csrf,
            blog["id"],
            {
                "title": "我的博客",
                "posts": [{"title": "第一篇", "slug": "first", "tags": ["t"], "body": body}],
            },
        )
        listing = _surface(blog["id"])
        assert listing.capabilities == {"has_content", "has_posts", "has_items", "supports_layout"}
        assert listing.meta.title == "我的博客"
        assert [item.url for item in listing.items("visitor")] == [f"/projects/{blog['slug']}/posts/first"]
        assert "post" not in listing.context("ai")
        post = _surface(blog["id"], sub="first")
        assert post.meta.url.endswith("/posts/first")
        assert len(post.context("ai")["post"]["body"]) == 1500
        assert post.context("visitor")["post"]["body"] == body


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
