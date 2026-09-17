from pathlib import Path
from typing import Annotated

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app import store
from app.auth import (
    check_csrf,
    clear_login_failures,
    clear_session,
    create_session,
    csrf_for,
    login_allowed,
    read_session,
    record_login_failure,
    require_admin,
    require_same_origin,
    verify_password,
)
from app.config import Config
from app.models import Project
from app.og import fetch_og
from app.uploads import InvalidUpload, extract_site, make_cover, remove_tree

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
router = APIRouter()

SANDBOX_CSP = "sandbox allow-scripts allow-forms allow-modals allow-popups allow-downloads"


def get_config(request: Request) -> Config:
    return request.app.state.config


def placeholder_hue(slug: str) -> int:
    return sum(slug.encode()) % 360


@router.get("/healthz")
def health(request: Request) -> dict[str, str]:
    return {"status": "ok"}


@router.get("/")
def gallery(request: Request):
    config = get_config(request)
    db = store.init(config)()
    projects = store.visible_projects(db)
    return templates.TemplateResponse(
        request,
        "gallery.html",
        {
            "site_title": config.site_title,
            "site_description": config.site_description,
            "projects": projects,
            "hue": placeholder_hue,
        },
    )


@router.get("/projects/{slug}", include_in_schema=False)
def project_root(request: Request, slug: str):
    config = get_config(request)
    db = store.init(config)()
    project = store.by_slug(db, slug)
    if project is None or project.type == "link" or not project.visible:
        raise HTTPException(404)
    if project.type == "link":
        return RedirectResponse(project.url, status_code=302)
    if not project.entry:
        raise HTTPException(404)
    return RedirectResponse(f"/projects/{slug}/{project.entry}", status_code=302)


@router.get("/projects/{slug}/{path:path}")
def project_file(request: Request, slug: str, path: str):
    config = get_config(request)
    db = store.init(config)()
    project = store.by_slug(db, slug)
    if project is None or project.type == "link" or not project.visible:
        raise HTTPException(404)
    root = (config.data / "projects" / slug).resolve()
    target = (root / path).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise HTTPException(404)
    if any(part.startswith(".") for part in Path(path).parts):
        raise HTTPException(404)
    media_type = {
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
    }.get(target.suffix.lower(), "application/octet-stream")
    if media_type == "text/html":
        media_type += "; charset=utf-8"
    response = FileResponse(target, media_type=media_type)
    response.headers["Content-Security-Policy"] = (
        "sandbox allow-scripts allow-forms allow-modals allow-popups allow-downloads"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "public, max-age=300"
    return response


@router.get("/media/covers/{name}")
def cover_file(request: Request, name: str):
    config = get_config(request)
    if "/" in name or name.startswith("."):
        raise HTTPException(404)
    target = (config.data / "media" / "covers" / name).resolve()
    if not target.is_relative_to((config.data / "media" / "covers").resolve()) or not target.is_file():
        raise HTTPException(404)
    return FileResponse(target, media_type="image/webp")


@router.get("/login")
def login_page(request: Request):
    config = get_config(request)
    cookie_response = RedirectResponse("/login")
    token = create_session(config, cookie_response, authenticated=False)
    response = templates.TemplateResponse(
        request,
        "login.html",
        {"site_title": config.site_title, "csrf": token, "error": None},
    )
    response.headers["set-cookie"] = cookie_response.headers["set-cookie"]
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/login")
def login_submit(request: Request, password: str = Form(""), csrf: str = Form("")):
    config = get_config(request)
    require_same_origin(request)
    if not login_allowed(request):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"site_title": config.site_title, "csrf": csrf_for(request), "error": "尝试次数过多，请稍后再试"},
            status_code=429,
        )
    submitted = request.headers.get("x-csrf-token") or csrf
    if not check_csrf(request, submitted):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"site_title": config.site_title, "csrf": csrf_for(request), "error": "会话校验失败，请重试"},
            status_code=403,
        )
    if not verify_password(config, password):
        record_login_failure(request)
        return templates.TemplateResponse(
            request,
            "login.html",
            {"site_title": config.site_title, "csrf": csrf_for(request), "error": "密码不正确"},
            status_code=401,
        )
    clear_login_failures(request)
    response = RedirectResponse("/admin", status_code=303)
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


@router.get("/admin")
def admin_page(request: Request):
    config = get_config(request)
    data = read_session(config, request)
    if data is None or data.get("admin") is not True:
        return RedirectResponse("/login", status_code=303)
    request.scope["siteflow_csrf"] = data.get("csrf")
    db = store.init(config)()
    projects = store.all_projects(db)
    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "site_title": config.site_title,
            "projects": projects,
            "csrf": csrf_for(request),
        },
    )


class LinkPayload(BaseModel):
    url: str
    title: str = ""
    description: str = ""


class PatchPayload(BaseModel):
    title: str | None = None
    description: str | None = None
    url: str | None = None
    pinned: bool | None = None
    visible: bool | None = None


class MovePayload(BaseModel):
    direction: str


def api_error(message: str, status_code: int = 400):
    return JSONResponse({"ok": False, "error": message}, status_code=status_code)


def admin_api(request: Request):
    config = get_config(request)
    require_admin(request, config)
    require_same_origin(request)
    submitted = request.headers.get("x-csrf-token") or ""
    if not check_csrf(request, submitted):
        raise HTTPException(403, "CSRF 校验失败")
    return config


@router.post("/api/admin/projects/upload")
async def upload_project(request: Request, file: Annotated[UploadFile, File()]):
    config = admin_api(request)
    name = (file.filename or "").lower()
    if not name.endswith((".html", ".htm", ".zip")):
        return api_error("只支持 .html / .htm / .zip 文件")
    suffix = ".html" if name.endswith((".html", ".htm")) else ".zip"
    tmp_dir = config.data / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = tmp_dir / f"{store.unique_slug_name()}{suffix}"
    size = 0
    try:
        with tmp_path.open("wb") as outgoing:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > config.upload_limit:
                    return api_error("文件超出大小限制", 413)
                outgoing.write(chunk)
    finally:
        await file.close()
    db = store.init(config)()
    project = None
    try:
        title = (name.rsplit(".", 1)[0] or "未命名作品")[:200]
        slug = store.unique_slug(db, title)
        folder = config.data / "projects" / slug
        entry = ""
        project_type = "zip" if suffix == ".zip" else "html"
        try:
            if project_type == "html":
                folder.mkdir(parents=True, exist_ok=True)
                (folder / "index.html").write_bytes(tmp_path.read_bytes())
                entry = "index.html"
            else:
                folder.mkdir(parents=True, exist_ok=True)
                entry = extract_site(tmp_path, folder, config)
            project = Project(
                slug=slug,
                type=project_type,
                title=title,
                entry=entry,
                sort_order=store.next_sort_order(db),
            )
            db.add(project)
            db.commit()
        except InvalidUpload as exc:
            remove_tree(folder)
            return api_error(str(exc), 422)
    finally:
        tmp_path.unlink(missing_ok=True)
    return {"ok": True, "project": project.as_dict() if project else None}


@router.post("/api/admin/projects/link")
async def add_link(request: Request, payload: LinkPayload):
    config = admin_api(request)
    if payload.url and not payload.url.lower().startswith(("http://", "https://")):
        return api_error("链接必须以 http:// 或 https:// 开头")
    db = store.init(config)()
    title = payload.title
    description = payload.description
    cover = ""
    og = fetch_og(payload.url)
    if og is not None:
        title = title or (og.title or urlparse_hostname(payload.url))[:200]
        description = description or og.description[:500]
        if og.image_url:
            cover = download_cover(config, og.image_url, slug=None)
    if not title:
        title = urlparse_hostname(payload.url) or "未命名作品"
    project = Project(
        slug=store.unique_slug(db, title),
        type="link",
        title=title[:200],
        description=description,
        url=payload.url,
        cover=cover or "",
        sort_order=store.next_sort_order(db),
    )
    db.add(project)
    db.commit()
    return {"ok": True, "project": project.as_dict()}


def urlparse_hostname(url: str) -> str:
    from urllib.parse import urlparse

    return (urlparse(url).hostname or "").replace("www.", "")


def download_cover(config: Config, image_url: str, slug: str | None) -> str:
    import httpx

    try:
        response = httpx.get(image_url, timeout=5.0, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError:
        return ""
    filename = f"{slug or store.unique_slug_name()}.webp"
    destination = config.data / "media" / "covers" / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        make_cover(response.content, destination)
    except InvalidUpload:
        return ""
    return filename


@router.patch("/api/admin/projects/{project_id}")
async def patch_project(request: Request, project_id: int, payload: PatchPayload):
    config = admin_api(request)
    db = store.init(config)()
    project = store.by_id(db, project_id)
    if project is None:
        return api_error("作品不存在", 404)
    updates = payload.model_dump(exclude_none=True)
    if "url" in updates and not updates["url"].lower().startswith(("http://", "https://")):
        return api_error("链接必须以 http:// 或 https:// 开头")
    for field, value in updates.items():
        setattr(project, field, value)
    from datetime import UTC, datetime

    project.updated_at = datetime.now(UTC).isoformat()
    db.commit()
    return {"ok": True, "project": project.as_dict()}


@router.post("/api/admin/projects/{project_id}/move")
async def move_project(request: Request, project_id: int, payload: MovePayload):
    config = admin_api(request)
    if payload.direction not in ("up", "down"):
        return api_error("方向必须是 up 或 down")
    db = store.init(config)()
    project = store.by_id(db, project_id)
    if project is None:
        return api_error("作品不存在", 404)
    moved = store.move(db, project, payload.direction)
    db.commit()
    return {"ok": moved, "error": None if moved else "已经在边界"}


@router.post("/api/admin/projects/{project_id}/cover")
async def upload_cover(request: Request, project_id: int, file: Annotated[UploadFile, File()]):
    config = admin_api(request)
    db = store.init(config)()
    project = store.by_id(db, project_id)
    if project is None:
        return api_error("作品不存在", 404)
    raw = await file.read()
    await file.close()
    if len(raw) > 10 * 1024 * 1024:
        return api_error("封面不能超过 10MB", 413)
    filename = f"{project.slug}.webp"
    destination = config.data / "media" / "covers" / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        make_cover(raw, destination)
    except InvalidUpload as exc:
        return api_error(str(exc), 422)
    old_name = project.cover
    project.cover = filename
    from datetime import UTC, datetime

    project.updated_at = datetime.now(UTC).isoformat()
    db.commit()
    if old_name and old_name != filename:
        old_path = config.data / "media" / "covers" / old_name
        if old_path.exists():
            old_path.unlink()
    return {"ok": True, "project": project.as_dict()}


@router.delete("/api/admin/projects/{project_id}")
async def delete_project(request: Request, project_id: int):
    config = admin_api(request)
    db = store.init(config)()
    project = store.by_id(db, project_id)
    if project is None:
        return api_error("作品不存在", 404)
    store.delete_files(config, project)
    db.delete(project)
    db.commit()
    return {"ok": True}
