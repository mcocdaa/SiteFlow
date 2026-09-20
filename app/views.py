from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy import select

from app import stats, store
from app.auth import (
    apply_session,
    check_csrf,
    clear_login_failures,
    clear_session,
    create_session,
    csrf_for,
    login_allowed,
    make_project_token,
    new_session_token,
    project_cookie_name,
    read_session,
    record_login_failure,
    require_admin,
    require_same_origin,
    set_project_cookie,
    verify_password,
    verify_project_password,
    verify_project_token,
)
from app.deps import DbSession, get_config
from app.models import Project
from app.plugins import registry
from app.svg_cover import generate_svg_cover
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
    ".wasm": "application/wasm",
    ".map": "application/json",
    ".avif": "image/avif",
    ".webmanifest": "application/manifest+json",
}


@router.get("/healthz")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/")
def gallery(request: Request, db: DbSession):
    config = get_config(request)
    session = read_session(config, request)
    stats.record_visit(db, request, project_id=None)
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


def check_project_access(request: Request, config, project) -> bool:
    if not project.password_hash:
        return True
    session = read_session(config, request)
    if session and session.get("admin") is True:
        return True
    token = request.cookies.get(project_cookie_name(project.slug))
    return bool(token and verify_project_token(config, project.slug, token))


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
    if not check_project_access(request, config, project):
        return templates.TemplateResponse(
            request,
            "project_gate.html",
            {"site_title": config.site_title, "project": project, "error": None},
        )
    stats.record_visit(db, request, project_id=project.id)
    return project_home(request, config, project, db)


@router.post("/projects/{slug}/unlock")
def unlock_project(request: Request, slug: str, db: DbSession, password: str = Form("")):
    config = get_config(request)
    project = find_public_project(db, slug)
    if not project.password_hash:
        return RedirectResponse(f"/projects/{slug}/", status_code=303)
    if not verify_project_password(project.password_hash, password):
        return templates.TemplateResponse(
            request,
            "project_gate.html",
            {"site_title": config.site_title, "project": project, "error": "密码不正确，请重新输入"},
            status_code=401,
        )
    token = make_project_token(config, slug)
    response = RedirectResponse(f"/projects/{slug}/", status_code=303)
    set_project_cookie(config, response, slug, token)
    return response


@router.get("/projects/{slug}/{path:path}")
def project_file(request: Request, slug: str, path: str, db: DbSession):
    config = get_config(request)
    project = find_public_project(db, slug)

    if not check_project_access(request, config, project):
        is_html_req = not path or path.endswith((".html", ".htm"))
        if is_html_req:
            return templates.TemplateResponse(
                request,
                "project_gate.html",
                {"site_title": config.site_title, "project": project, "error": None},
            )
        raise HTTPException(401, "需要访问密码")

    if not path:
        stats.record_visit(db, request, project_id=project.id)
        return project_home(request, config, project, db)

    plugin = registry.get(project.type)
    if plugin is not None:
        response = plugin.route(request, project, path, db)
        if response is None:
            raise HTTPException(404)
        return response

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

    stat_res = target.stat()
    etag = f'"{stat_res.st_mtime_ns:x}-{stat_res.st_size:x}"'
    is_html = target.name == "index.html" or target.suffix.lower() in (".html", ".htm")
    cache_control = "no-cache, must-revalidate" if is_html else "public, max-age=86400"

    if is_html:
        stats.record_visit(db, request, project_id=project.id)

    if_none_match = request.headers.get("if-none-match")
    if if_none_match and (if_none_match.strip() == etag or if_none_match.strip() == f"W/{etag}"):
        res = Response(status_code=304)
        res.headers["ETag"] = etag
        res.headers["Cache-Control"] = cache_control
        res.headers["Content-Security-Policy"] = SANDBOX_CSP
        res.headers["X-Frame-Options"] = "SAMEORIGIN"
        res.headers["X-Content-Type-Options"] = "nosniff"
        return res

    media_type = MEDIA_TYPES.get(target.suffix.lower(), "application/octet-stream")
    if media_type == "text/html":
        media_type += "; charset=utf-8"
    response = FileResponse(target, media_type=media_type)
    response.headers["ETag"] = etag
    response.headers["Content-Security-Policy"] = SANDBOX_CSP
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Cache-Control"] = cache_control
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

    stat_res = target.stat()
    etag = f'"{stat_res.st_mtime_ns:x}-{stat_res.st_size:x}"'
    cache_control = "public, max-age=86400"
    if_none_match = request.headers.get("if-none-match")
    if if_none_match and (if_none_match.strip() == etag or if_none_match.strip() == f"W/{etag}"):
        res = Response(status_code=304)
        res.headers["ETag"] = etag
        res.headers["Cache-Control"] = cache_control
        return res

    response = FileResponse(target, media_type="image/webp")
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = cache_control
    return response


@router.get("/media/placeholder/{slug}.svg")
def placeholder_svg(slug: str, db: DbSession):
    project = store.by_slug(db, slug)
    title = project.title if project else slug
    ptype = project.type if project else "html"
    svg = generate_svg_cover(slug, title, ptype)
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/api/qrcode")
def qrcode_image(url: str):
    import io

    import qrcode
    import qrcode.image.svg

    if not url:
        raise HTTPException(400, "url parameter is required")
    img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage)
    buf = io.BytesIO()
    img.save(buf)
    return Response(
        content=buf.getvalue(),
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=3600"},
    )


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


@router.get("/api/search")
def search_projects(request: Request, db: DbSession, q: str = ""):
    config = get_config(request)
    is_admin = bool(read_session(config, request))
    stmt = select(Project)
    if not is_admin:
        stmt = stmt.where(Project.visible.is_(True))
    candidates = list(db.execute(stmt.order_by(Project.pinned.desc(), Project.created_at.desc())).scalars())
    all_projects = candidates if is_admin else [p for p in candidates if store.is_visible(db, p)]

    query = q.strip().lower()
    results = []
    space_map = {p.id: p.title for p in all_projects if p.type == "space"}

    for p in all_projects:
        match = True
        if query:
            searchable = f"{p.title} {p.slug} {p.description or ''} {p.type}".lower()
            match = query in searchable
        if match:
            results.append({
                "id": p.id,
                "title": p.title,
                "slug": p.slug,
                "description": p.description or "",
                "type": p.type,
                "url": p.url if p.type == "link" else f"/projects/{p.slug}/",
                "space": space_map.get(p.parent_id, "") if p.parent_id else "",
                "pinned": p.pinned,
                "is_locked": bool(p.password_hash),
            })
            if len(results) >= 20:
                break

    return JSONResponse(results)

