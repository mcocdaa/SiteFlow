import shutil
from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import urlparse

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app import store
from app.auth import csrf_for, read_session
from app.deps import AdminConfig, DbSession, api_error, get_config
from app.models import Project
from app.og import fetch_image, fetch_og
from app.templating import templates
from app.uploads import InvalidUpload, extract_site, make_cover, remove_tree, save_cover

router = APIRouter()

COVER_LIMIT = 10 * 1024 * 1024


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


def hostname_of(url: str) -> str:
    return (urlparse(url).hostname or "").replace("www.", "")


def touch(project: Project) -> None:
    project.updated_at = datetime.now(UTC).isoformat()


@router.get("/admin")
def admin_page(request: Request, db: DbSession):
    config = get_config(request)
    data = read_session(config, request)
    if data is None or data.get("admin") is not True:
        return RedirectResponse("/login", status_code=303)
    request.scope["siteflow_csrf"] = data.get("csrf")
    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "site_title": config.site_title,
            "projects": store.all_projects(db),
            "csrf": csrf_for(request),
        },
    )


@router.post("/api/admin/projects/upload")
async def upload_project(
    file: Annotated[UploadFile, File()],
    config: AdminConfig,
    db: DbSession,
):
    name = (file.filename or "").lower()
    if not name.endswith((".html", ".htm", ".zip")):
        return api_error("只支持 .html / .htm / .zip 文件")
    suffix = ".html" if name.endswith((".html", ".htm")) else ".zip"
    tmp_path = config.data / "tmp" / f"{store.unique_slug_name()}{suffix}"
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        try:
            size = 0
            with tmp_path.open("wb") as outgoing:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > config.upload_limit:
                        return api_error("文件超出大小限制", 413)
                    outgoing.write(chunk)
        finally:
            await file.close()
        title = (name.rsplit(".", 1)[0] or "未命名作品")[:200]
        slug = store.unique_slug(db, title)
        folder = config.data / "projects" / slug
        try:
            folder.mkdir(parents=True, exist_ok=True)
            if suffix == ".html":
                shutil.copyfile(tmp_path, folder / "index.html")
                entry = "index.html"
            else:
                entry = extract_site(tmp_path, folder, config)
            project = Project(
                slug=slug,
                type="zip" if suffix == ".zip" else "html",
                title=title,
                entry=entry,
                sort_order=store.next_sort_order(db),
            )
            db.add(project)
            db.commit()
        except InvalidUpload as exc:
            remove_tree(folder)
            return api_error(str(exc), 422)
        except Exception:
            remove_tree(folder)
            raise
        return {"ok": True, "project": project.as_dict()}
    finally:
        tmp_path.unlink(missing_ok=True)


@router.post("/api/admin/projects/link")
def add_link(payload: LinkPayload, config: AdminConfig, db: DbSession):
    if not payload.url.lower().startswith(("http://", "https://")):
        return api_error("链接必须以 http:// 或 https:// 开头")
    og = fetch_og(payload.url)
    title = payload.title or (og.title if og else "") or hostname_of(payload.url) or "未命名作品"
    description = payload.description or (og.description if og else "")
    slug = store.unique_slug(db, title)
    cover = ""
    if og is not None and og.image_url:
        raw = fetch_image(og.image_url)
        if raw is not None:
            cover = save_cover(config, raw, slug)
    project = Project(
        slug=slug,
        type="link",
        title=title[:200],
        description=description[:500],
        url=payload.url,
        cover=cover,
        sort_order=store.next_sort_order(db),
    )
    db.add(project)
    db.commit()
    return {"ok": True, "project": project.as_dict()}


@router.patch("/api/admin/projects/{project_id}")
def patch_project(
    project_id: int,
    payload: PatchPayload,
    _auth: AdminConfig,
    db: DbSession,
):
    project = store.by_id(db, project_id)
    if project is None:
        return api_error("作品不存在", 404)
    updates = payload.model_dump(exclude_none=True)
    url = updates.get("url")
    if url is not None and not url.lower().startswith(("http://", "https://")):
        return api_error("链接必须以 http:// 或 https:// 开头")
    for field, value in updates.items():
        setattr(project, field, value)
    touch(project)
    db.commit()
    return {"ok": True, "project": project.as_dict()}


@router.post("/api/admin/projects/{project_id}/move")
def move_project(
    project_id: int,
    payload: MovePayload,
    _auth: AdminConfig,
    db: DbSession,
):
    if payload.direction not in ("up", "down"):
        return api_error("方向必须是 up 或 down")
    project = store.by_id(db, project_id)
    if project is None:
        return api_error("作品不存在", 404)
    moved = store.move(db, project, payload.direction)
    db.commit()
    return {"ok": moved, "error": None if moved else "已经在边界"}


@router.post("/api/admin/projects/{project_id}/cover")
async def upload_cover(
    project_id: int,
    file: Annotated[UploadFile, File()],
    config: AdminConfig,
    db: DbSession,
):
    project = store.by_id(db, project_id)
    if project is None:
        return api_error("作品不存在", 404)
    raw = await file.read()
    await file.close()
    if len(raw) > COVER_LIMIT:
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
    touch(project)
    db.commit()
    if old_name and old_name != filename:
        old_path = config.data / "media" / "covers" / old_name
        if old_path.exists():
            old_path.unlink()
    return {"ok": True, "project": project.as_dict()}


@router.delete("/api/admin/projects/{project_id}")
def delete_project(project_id: int, _auth: AdminConfig, db: DbSession):
    project = store.by_id(db, project_id)
    if project is None:
        return api_error("作品不存在", 404)
    store.delete_files(config=_auth, project=project)
    db.delete(project)
    db.commit()
    return {"ok": True}
