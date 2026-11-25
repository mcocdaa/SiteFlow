import json
import re
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import read_session
from app.extensions.registry import (
    build_render_bundle,
    normalize_extensions,
    normalize_post_meta,
)
from app.models import Project
from app.plugins.base import InvalidContent
from app.plugins.blog.markdown import BLOG_CSP, render_inline_math, render_markdown
from app.surface import StaticSurface, SurfaceItem, project_meta
from app.templating import templates

MAX_POSTS = 200
MAX_BODY = 200_000
MAX_AI_BODY = 1500


def _text(value: object, limit: int) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _slug(value: object) -> str:
    text = _text(value, 100)
    text = re.sub(r"[\s%?#]+", "-", text)
    text = text.replace("/", "-").replace("\\", "-")
    return text.strip("-.")[:100]


def _tags(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_text(item, 50) for item in value[:10] if _text(item, 50)]


def default_content() -> dict:
    return {"title": "", "description": "", "posts": []}


def normalize(
    parsed: dict,
    strict: bool = False,
    project_slug: str | None = None,
    config: Any = None,
) -> dict:
    posts_out: list[dict[str, Any]] = []
    seen: set[str] = set()
    posts = parsed.get("posts")
    if strict and (not isinstance(posts, list) or len(posts) > MAX_POSTS):
        raise InvalidContent("文章列表格式不正确或超过 200 篇")
    if isinstance(posts, list):
        for raw in posts[:MAX_POSTS]:
            if not isinstance(raw, dict):
                if strict:
                    raise InvalidContent("文章格式不正确")
                continue
            title = _text(raw.get("title"), 200)
            if strict and not title:
                raise InvalidContent("文章标题不能为空")
            slug = _slug(raw.get("slug")) or _slug(title)
            if strict and len(str(raw.get("body", ""))) > MAX_BODY:
                raise InvalidContent("文章正文不能超过 200000 字")
            if strict and (not slug or slug in seen):
                raise InvalidContent("文章网址标识不能为空或重复，请修改后重试")
            if not slug or slug in seen:
                continue
            seen.add(slug)
            post_item: dict[str, Any] = {
                "slug": slug,
                "title": _text(raw.get("title"), 200) or slug,
                "date": _text(raw.get("date"), 20),
                "tags": _tags(raw.get("tags")),
                "summary": _text(raw.get("summary"), 500),
                "body": _text(raw.get("body"), MAX_BODY),
            }
            meta = normalize_post_meta(
                raw.get("meta"),
                strict=strict,
                project_slug=project_slug,
                config=config,
            )
            if meta:
                post_item["meta"] = meta
            posts_out.append(post_item)
    posts_out.sort(key=lambda post: (post["date"] or "", post["title"]), reverse=True)
    extensions = normalize_extensions(
        parsed.get("extensions"),
        strict=strict,
        project_slug=project_slug,
        target="blog",
        config=config,
    )
    result: dict[str, Any] = {
        "title": _text(parsed.get("title"), 200),
        "description": _text(parsed.get("description"), 500),
        "posts": posts_out,
    }
    if extensions:
        result["extensions"] = extensions
    return result


def validate_content(
    raw: str,
    strict: bool = False,
    project_slug: str | None = None,
    config: Any = None,
) -> dict:
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise InvalidContent("博客内容不是合法 JSON") from exc
    if not isinstance(parsed, dict):
        raise InvalidContent("博客内容必须是 JSON 对象")
    if strict and "posts" not in parsed:
        parsed["posts"] = []
    return normalize(parsed, strict=strict, project_slug=project_slug, config=config)


class BlogApp:
    type: str = "blog"
    label: str = "博客"
    icon: str = "notebook-pen"
    leaf: bool = True
    content_editable: bool = True
    admin_template: str | None = "blog_admin.html"

    def default_content(self) -> dict:
        return default_content()

    def validate_content(
        self,
        raw: str,
        project_slug: str | None = None,
        config: Any = None,
    ) -> dict:
        return validate_content(raw, strict=True, project_slug=project_slug, config=config)

    def surface(self, request: Request, project: Project, db: Session, *, sub: str = "") -> StaticSurface:
        config = request.app.state.config
        content = validate_content(project.content, project_slug=project.slug, config=config)
        posts = content["posts"]
        base = f"/projects/{project.slug}/"
        items = tuple(
            SurfaceItem(
                key=post["slug"],
                title=post["title"],
                url=f"{base}posts/{post['slug']}",
                summary=post["summary"],
                kind="post",
                tags=tuple(post["tags"]),
            )
            for post in posts
        )
        blog = {
            "title": content["title"] or project.title,
            "description": content["description"] or project.description,
        }
        current = next((post for post in posts if post["slug"] == sub), None) if sub else None
        visitor: dict[str, Any] = dict(blog)
        ai: dict[str, Any] = dict(blog)
        admin: dict[str, Any] = {**blog, "posts": posts}
        if current is not None:
            visitor["post"] = current
            admin["post"] = current
            ai["post"] = {
                "title": current["title"],
                "date": current["date"],
                "tags": current["tags"],
                "summary": current["summary"],
                "body": current["body"][:MAX_AI_BODY],
            }
        return StaticSurface(
            meta=project_meta(
                db,
                project,
                title=blog["title"],
                description=blog["description"],
                url=f"{base}posts/{current['slug']}" if current else base,
            ),
            capabilities=frozenset({"has_content", "has_posts", "has_items", "supports_layout"}),
            contexts={"visitor": visitor, "ai": ai, "admin": admin},
            item_list=items,
        )

    def route(self, request: Request, project: Project, path: str, db: Session):
        clean = path.strip("/")
        if clean == "admin":
            return RedirectResponse(f"/admin/projects/{project.id}", status_code=302)
        if clean.startswith("post/"):
            post_slug = clean[len("post/") :].strip("/")
            return RedirectResponse(f"/projects/{project.slug}/posts/{post_slug}", status_code=302)
        if not path.startswith("posts/"):
            return None
        slug = path[len("posts/") :].strip("/")
        config = request.app.state.config
        session = read_session(config, request)
        is_admin = bool(session and session.get("admin") is True)
        content = validate_content(project.content, project_slug=project.slug, config=config)
        posts = content["posts"]
        index = next((position for position, item in enumerate(posts) if item["slug"] == slug), None)
        if index is None:
            return None
        post = posts[index]
        prev_post = posts[index - 1] if index > 0 else None
        next_post = posts[index + 1] if index + 1 < len(posts) else None
        rendered = render_markdown(post["body"])
        ext = build_render_bundle(
            "post",
            project,
            content,
            post=post,
            target="blog",
            config=config,
            is_admin=is_admin,
        )
        response = templates.TemplateResponse(
            request,
            "blog_post.html",
            {
                "project": project,
                "post": post,
                "body_html": rendered.html,
                "toc": rendered.toc,
                "toc_title": rendered.toc_title,
                "has_math": rendered.has_math,
                "ext": ext,
                "prev_post": prev_post,
                "next_post": next_post,
            },
        )
        response.headers["Content-Security-Policy"] = BLOG_CSP
        return response

    def render(self, request: Request, project: Project, db: Session) -> HTMLResponse:
        config = request.app.state.config
        session = read_session(config, request)
        is_admin = bool(session and session.get("admin") is True)
        content = validate_content(project.content, project_slug=project.slug, config=config)
        display_posts: list[dict[str, Any]] = []
        has_math = False
        for post in content["posts"]:
            item = dict(post)
            if item["summary"]:
                summary_html, post_has_math = render_inline_math(item["summary"])
                item["summary_html"] = summary_html
                if post_has_math:
                    has_math = True
            display_posts.append(item)
        ext = build_render_bundle(
            "list",
            project,
            content,
            posts=content["posts"],
            target="blog",
            config=config,
            is_admin=is_admin,
        )
        response = templates.TemplateResponse(
            request,
            "blog.html",
            {
                "project": project,
                "blog": content,
                "posts": display_posts,
                "has_math": has_math,
                "ext": ext,
            },
        )
        response.headers["Content-Security-Policy"] = BLOG_CSP
        return response
