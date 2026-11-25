import hashlib
import json
import time
from typing import Any

from fastapi import Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from app import store, submissions
from app.auth import SESSION_CLOCK_SKEW_SECONDS, read_session
from app.config import Config
from app.extensions.registry import build_render_bundle, normalize_extensions
from app.models import Project
from app.plugins.base import InvalidContent
from app.surface import Capability, StaticSurface, project_meta
from app.templating import templates

BOTTLE_CAPABILITIES: frozenset[Capability] = frozenset({"accepts_visitor_input", "has_items"})

BOTTLE_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' https: http: data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'self'"
)

BOTTLE_COOKIE_MAX_AGE = 30 * 24 * 3600
MAX_CREDITS = 5

DEFAULT_INTRO = "把此刻的心情装进玻璃瓶，投向大海；也许在某个瞬间，远方的陌生人会拾起你的温柔。"
DEFAULT_PLACEHOLDER = "写下此刻想说的话，或一份祝福、一个小秘密…"


def default_content() -> dict[str, Any]:
    return {
        "intro": DEFAULT_INTRO,
        "placeholder": DEFAULT_PLACEHOLDER,
        "max_length": 280,
        "require_approval": True,
        "throw_to_pick": True,
        "allow_links": False,
        "throw_limit_per_hour": 3,
        "pick_limit_per_hour": 30,
    }


def _parse_int(value: object, *, label: str, low: int, high: int, default: int, strict: bool) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        if strict:
            raise InvalidContent(f"{label}必须是整数")
        return default
    if not low <= value <= high:
        if strict:
            raise InvalidContent(f"{label}必须在 {low} 到 {high} 之间")
        return max(low, min(high, value))
    return value


def _parse_bool(value: object, *, label: str, default: bool, strict: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        if strict:
            raise InvalidContent(f"{label}必须是布尔值")
        return default
    return value


def _parse_text(value: object, *, label: str, limit: int, default: str, strict: bool) -> str:
    if value is None:
        return default
    if not isinstance(value, str):
        if strict:
            raise InvalidContent(f"{label}必须是文本")
        return default
    return value.strip()[:limit]


def validate_content(
    raw: str,
    *,
    strict: bool = True,
    project_slug: str | None = None,
    config: Any = None,
) -> dict[str, Any]:
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        if strict:
            raise InvalidContent("漂流瓶配置不是合法 JSON") from exc
        return default_content()
    if not isinstance(parsed, dict):
        if strict:
            raise InvalidContent("漂流瓶配置必须是 JSON 对象")
        return default_content()
    defaults = default_content()
    result: dict[str, Any] = {
        "intro": _parse_text(
            parsed.get("intro"),
            label="海滩欢迎语",
            limit=500,
            default=defaults["intro"],
            strict=strict,
        ),
        "placeholder": _parse_text(
            parsed.get("placeholder"),
            label="输入框提示",
            limit=200,
            default=defaults["placeholder"],
            strict=strict,
        ),
        "max_length": _parse_int(
            parsed.get("max_length"),
            label="单条字数上限",
            low=50,
            high=1000,
            default=defaults["max_length"],
            strict=strict,
        ),
        "require_approval": _parse_bool(
            parsed.get("require_approval"),
            label="先审后发",
            default=defaults["require_approval"],
            strict=strict,
        ),
        "throw_to_pick": _parse_bool(
            parsed.get("throw_to_pick"),
            label="投一捞一",
            default=defaults["throw_to_pick"],
            strict=strict,
        ),
        "allow_links": _parse_bool(
            parsed.get("allow_links"),
            label="允许链接",
            default=defaults["allow_links"],
            strict=strict,
        ),
        "throw_limit_per_hour": _parse_int(
            parsed.get("throw_limit_per_hour"),
            label="每小时投递上限",
            low=1,
            high=20,
            default=defaults["throw_limit_per_hour"],
            strict=strict,
        ),
        "pick_limit_per_hour": _parse_int(
            parsed.get("pick_limit_per_hour"),
            label="每小时捞取上限",
            low=1,
            high=100,
            default=defaults["pick_limit_per_hour"],
            strict=strict,
        ),
    }
    extensions = normalize_extensions(
        parsed.get("extensions"),
        strict=strict,
        project_slug=project_slug,
        capabilities=BOTTLE_CAPABILITIES,
        config=config,
    )
    if extensions:
        result["extensions"] = extensions
    return result


def load_bottle_config(
    raw: str,
    *,
    project_slug: str | None = None,
    config: Any = None,
) -> dict[str, Any]:
    return validate_content(raw, strict=False, project_slug=project_slug, config=config)


def bottle_cookie_name(slug: str) -> str:
    digest = hashlib.sha256(slug.encode()).hexdigest()[:10]
    return f"sf_bottle_{digest}"


def _visitor_serializer(config: Config) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(config.secret, salt="siteflow-bottle-visitor")


def read_visitor_cookie(config: Config, request: Request, slug: str) -> tuple[str, int]:
    raw = request.cookies.get(bottle_cookie_name(slug))
    if not raw:
        return "", 0
    serializer = _visitor_serializer(config)
    try:
        data, issued_at = serializer.loads(raw, return_timestamp=True)
    except BadSignature:
        return "", 0
    age = time.time() - issued_at.timestamp()
    if age > BOTTLE_COOKIE_MAX_AGE or age < -SESSION_CLOCK_SKEW_SECONDS:
        return "", 0
    if not isinstance(data, dict) or data.get("slug") != slug:
        return "", 0
    token = data.get("token")
    credits_raw = data.get("credits", 0)
    if not isinstance(token, str) or not token or len(token) > 64:
        return "", 0
    if isinstance(credits_raw, bool) or not isinstance(credits_raw, int):
        credits = 0
    else:
        credits = max(0, min(MAX_CREDITS, credits_raw))
    return token, credits


def set_visitor_cookie(
    config: Config,
    response: Response,
    slug: str,
    author_token: str,
    credits: int,
) -> None:
    clamped = max(0, min(MAX_CREDITS, credits))
    signed = _visitor_serializer(config).dumps({"slug": slug, "token": author_token, "credits": clamped})
    response.set_cookie(
        bottle_cookie_name(slug),
        signed,
        max_age=BOTTLE_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=config.secure,
        path="/",
    )


class BottleApp:
    type: str = "bottle"
    label: str = "漂流瓶"
    icon: str = "bottle"
    leaf: bool = True
    content_editable: bool = True
    admin_template: str | None = "bottle_admin.html"
    capabilities: frozenset[Capability] = BOTTLE_CAPABILITIES

    def default_content(self) -> dict[str, Any]:
        return default_content()

    def validate_content(
        self,
        raw: str,
        project_slug: str | None = None,
        config: Any = None,
    ) -> dict[str, Any]:
        return validate_content(raw, strict=True, project_slug=project_slug, config=config)

    def route(self, request: Request, project: Project, path: str, db: Session):
        if path.strip("/") == "admin":
            return RedirectResponse(f"/admin/projects/{project.id}", status_code=302)
        return None

    def surface(self, request: Request, project: Project, db: Session, *, sub: str = "") -> StaticSurface:
        config = request.app.state.config
        cfg = load_bottle_config(project.content, project_slug=project.slug, config=config)
        counts = submissions.count_submissions(db, project_id=project.id, plugin_id="bottle")
        rules = {
            "max_length": cfg["max_length"],
            "require_approval": cfg["require_approval"],
            "throw_to_pick": cfg["throw_to_pick"],
            "allow_links": cfg["allow_links"],
        }
        public = {
            "title": project.title,
            "description": project.description,
            "intro": cfg["intro"],
            "approved_count": counts["approved"],
            "rules": rules,
        }
        return StaticSurface(
            meta=project_meta(db, project),
            capabilities=self.capabilities,
            contexts={
                "visitor": public,
                "ai": dict(public),
                "admin": {**public, "counts": counts, "config": cfg},
            },
        )

    def render(self, request: Request, project: Project, db: Session) -> HTMLResponse:
        config = request.app.state.config
        session = read_session(config, request)
        is_admin = bool(session and session.get("admin") is True)
        cfg = load_bottle_config(project.content, project_slug=project.slug, config=config)
        surface = self.surface(request, project, db)
        ext = build_render_bundle(
            "bottle",
            project,
            cfg,
            capabilities=surface.capabilities,
            config=config,
            is_admin=is_admin,
            db=db,
        )
        _token, credits = read_visitor_cookie(config, request, project.slug)
        approved_count = int(surface.context("visitor").get("approved_count", 0))
        parent = store.by_id(db, project.parent_id) if project.parent_id else None
        back_url = f"/projects/{parent.slug}/" if parent and store.is_visible(db, parent) else "/"
        response = templates.TemplateResponse(
            request,
            "bottle.html",
            {
                "site_title": config.site_title,
                "project": project,
                "bottle": cfg,
                "ext": ext,
                "credits": credits,
                "max_credits": MAX_CREDITS,
                "approved_count": approved_count,
                "is_admin": is_admin,
                "back_url": back_url,
            },
        )
        response.headers["Content-Security-Policy"] = BOTTLE_CSP
        return response
