from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse

from app import store
from app.auth import (
    apply_session,
    check_csrf,
    clear_login_failures,
    clear_session,
    create_session,
    csrf_for,
    login_allowed,
    new_session_token,
    read_session,
    record_login_failure,
    require_admin,
    require_same_origin,
    verify_password,
)
from app.deps import DbSession, get_config
from app.plugins import registry
from app.templating import placeholder_hue, templates

router = APIRouter()

SANDBOX_CSP = "sandbox allow-scripts allow-forms allow-modals allow-popups allow-downloads"

MEDIA_TYPES = {
    ".html": "text/html",
    ".htm": "text/html",
    ".css": "text/css",
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".xml": "application/xml",
}


@router.get("/healthz")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/")
def gallery(request: Request, db: DbSession):
    config = get_config(request)
    session = read_session(config, request)
    return templates.TemplateResponse(
        request,
        "gallery.html",
        {
            "site_title": config.site_title,
            "site_description": config.site_description,
            "projects": store.visible_projects(db),
            "hue": placeholder_hue,
            "is_admin": bool(session and session.get("admin") is True),
        },
    )


def safe_next(value: str | None) -> str:
    if value and value.startswith("/") and not value.startswith("//"):
        return value
    return "/admin"


def project_home(request: Request, config, project, db):
    plugin = registry.get(project.type)
    if plugin is not None:
        return plugin.render(request, project, db)
    if not project.entry:
        raise HTTPException(404)
    return RedirectResponse(f"/projects/{project.slug}/{project.entry}", status_code=302)


def find_public_project(db, slug: str):
    project = store.by_slug(db, slug)
    if project is None or project.type == "link" or not store.is_visible(db, project):
        raise HTTPException(404)
    return project


@router.get("/projects/{slug}", include_in_schema=False)
def project_root(request: Request, slug: str, db: DbSession):
    config = get_config(request)
    project = find_public_project(db, slug)
    return project_home(request, config, project, db)



@router.get("/projects/{slug}/{path:path}")
def project_file(request: Request, slug: str, path: str, db: DbSession):
    config = get_config(request)
    project = find_public_project(db, slug)
    if not path:
        return project_home(request, config, project, db)
    if project.type not in ("html", "zip"):
        raise HTTPException(404)
    if any(part.startswith(".") for part in Path(path).parts):
        raise HTTPException(404)
    root = (config.data / "projects" / slug).resolve()
    target = (root / path).resolve()
    if not target.is_relative_to(root):
        raise HTTPException(404)
    if target.is_dir():
        target = target / "index.html"
    if not target.is_file():
        raise HTTPException(404)
    media_type = MEDIA_TYPES.get(target.suffix.lower(), "application/octet-stream")
    if media_type == "text/html":
        media_type += "; charset=utf-8"
    response = FileResponse(target, media_type=media_type)
    response.headers["Content-Security-Policy"] = SANDBOX_CSP
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "public, max-age=300"
    return response


@router.get("/media/covers/{name}")
def cover_file(request: Request, name: str):
    config = get_config(request)
    if "/" in name or name.startswith("."):
        raise HTTPException(404)
    covers = (config.data / "media" / "covers").resolve()
    target = (covers / name).resolve()
    if not target.is_relative_to(covers) or not target.is_file():
        raise HTTPException(404)
    return FileResponse(target, media_type="image/webp")


@router.get("/login")
def login_page(request: Request):
    config = get_config(request)
    session = read_session(config, request)
    if session is not None and session.get("admin") is True:
        return RedirectResponse("/admin", status_code=303)
    token = new_session_token()
    response = templates.TemplateResponse(
        request,
        "login.html",
        {"site_title": config.site_title, "csrf": token, "error": None, "next": safe_next(request.query_params.get("next"))},
    )
    apply_session(config, response, token, authenticated=False)
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/login")
def login_submit(
    request: Request,
    password: str = Form(""),
    csrf: str = Form(""),
    next_url: str = Form("", alias="next"),
):
    config = get_config(request)
    require_same_origin(request)
    target = safe_next(next_url)
    if not login_allowed(request):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"site_title": config.site_title, "csrf": csrf_for(request), "error": "尝试次数过多，请稍后再试", "next": target},
            status_code=429,
        )
    submitted = request.headers.get("x-csrf-token") or csrf
    if not check_csrf(request, submitted):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"site_title": config.site_title, "csrf": csrf_for(request), "error": "会话校验失败，请重试", "next": target},
            status_code=403,
        )
    if not verify_password(config, password):
        record_login_failure(request)
        return templates.TemplateResponse(
            request,
            "login.html",
            {"site_title": config.site_title, "csrf": csrf_for(request), "error": "密码不正确", "next": target},
            status_code=401,
        )
    clear_login_failures(request)
    response = RedirectResponse(target, status_code=303)
    create_session(config, response)
    return response


@router.post("/logout")
def logout(request: Request):
    config = get_config(request)
    require_admin(request, config)
    submitted = request.headers.get("x-csrf-token") or ""
    if not check_csrf(request, submitted):
        raise HTTPException(403, "CSRF 校验失败")
    response = RedirectResponse("/", status_code=303)
    clear_session(response)
    return response
