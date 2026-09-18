import json
import re

from fastapi import Request
from fastapi.responses import HTMLResponse
from markdown_it import MarkdownIt
from sqlalchemy.orm import Session

from app.models import Project
from app.plugins.base import InvalidContent
from app.templating import templates

MAX_POSTS = 200
MAX_BODY = 200_000
_markdown = MarkdownIt("commonmark", {"html": False})


def _text(value: object, limit: int) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _slug(value: object) -> str:
    text = _text(value, 100)
    text = re.sub(r"\s+", "-", text)
    text = text.replace("/", "-").replace("\\", "-")
    return text.strip("-.")[:100]


def _tags(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_text(item, 50) for item in value[:10] if _text(item, 50)]


def default_content() -> dict:
    return {"title": "", "description": "", "posts": []}


def normalize(parsed: dict) -> dict:
    posts_out: list[dict] = []
    seen: set[str] = set()
    posts = parsed.get("posts")
    if isinstance(posts, list):
        for raw in posts[:MAX_POSTS]:
            if not isinstance(raw, dict):
                continue
            slug = _slug(raw.get("slug"))
            if not slug or slug in seen:
                continue
            seen.add(slug)
            posts_out.append(
                {
                    "slug": slug,
                    "title": _text(raw.get("title"), 200) or slug,
                    "date": _text(raw.get("date"), 20),
                    "tags": _tags(raw.get("tags")),
                    "summary": _text(raw.get("summary"), 500),
                    "body": _text(raw.get("body"), MAX_BODY),
                }
            )
    posts_out.sort(key=lambda post: (post["date"] or "", post["title"]), reverse=True)
    return {
        "title": _text(parsed.get("title"), 200),
        "description": _text(parsed.get("description"), 500),
        "posts": posts_out,
    }


def validate_content(raw: str) -> dict:
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise InvalidContent("博客内容不是合法 JSON") from exc
    if not isinstance(parsed, dict):
        raise InvalidContent("博客内容必须是 JSON 对象")
    return normalize(parsed)


class BlogApp:
    type: str = "blog"
    label: str = "博客"
    icon: str = "notebook-pen"
    leaf: bool = True
    content_editable: bool = True
    admin_template: str | None = "blog_admin.html"

    def default_content(self) -> dict:
        return default_content()

    def validate_content(self, raw: str) -> dict:
        return validate_content(raw)

    def route(self, request: Request, project: Project, path: str, db: Session):
        if not path.startswith("posts/"):
            return None
        slug = path[len("posts/") :].strip("/")
        content = validate_content(project.content)
        post = next((item for item in content["posts"] if item["slug"] == slug), None)
        if post is None:
            return None
        return templates.TemplateResponse(
            request,
            "blog_post.html",
            {"project": project, "post": post, "body_html": _markdown.render(post["body"])},
        )

    def render(self, request: Request, project: Project, db: Session) -> HTMLResponse:
        content = validate_content(project.content)
        return templates.TemplateResponse(
            request,
            "blog.html",
            {"project": project, "blog": content, "posts": content["posts"]},
        )
