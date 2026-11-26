import json
import shutil
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app import project_service, stats, store, submissions
from app.auth import csrf_for, read_session
from app.deps import AdminConfig, DbSession, ServiceError, api_error, get_config
from app.extensions.inheritance import (
    VALID_MODES,
    load_site_extensions,
    merge_layer_config,
    parse_layer_state,
    resolve_project_extension,
    save_site_extensions,
)
from app.extensions.mascot import MASCOT_CHARACTERS
from app.extensions.packs import (
    PackError,
    delete_pack,
    install_pack_from_url,
    install_pack_from_zip,
    list_packs,
    sync_pack,
)
from app.extensions.registry import (
    build_editor_bundle,
    build_project_admin_catalog,
    build_site_admin_catalog,
    redact_content_extensions,
    referenced_media_urls,
    resolved_catalog_item,
    site_catalog_item,
)
from app.extensions.registry import get as get_extension
from app.models import Project
from app.og import fetch_image, fetch_og
from app.plugins import registry
from app.plugins.base import InvalidContent
from app.plugins.blog.plugin import _slug as normalize_post_slug
from app.plugins.blog.plugin import validate_content as blog_content
from app.project_service import (
    _SLUG_RE,
    COVER_LIMIT,
    touch,
)
from app.project_service import (
    _parse_raw_content as _parse_project_content,
)
from app.project_service import (
    capabilities_of as _capabilities_of,
)
from app.project_service import (
    cleanup_unreferenced_media as _cleanup_unreferenced_media,
)
from app.project_service import (
    project_dict_redacted as _project_dict_redacted,
)
from app.templating import templates
from app.uploads import (
    InvalidUpload,
    extract_site,
    remove_tree,
    save_project_media,
)

router = APIRouter()

PACK_UPLOAD_LIMIT = 10 * 1024 * 1024


class LinkPayload(BaseModel):
    url: str
    title: str = ""
    description: str = ""
    parent_id: int | None = None


class PatchPayload(BaseModel):
    title: str | None = None
    description: str | None = None
    url: str | None = None
    pinned: bool | None = None
    visible: bool | None = None
    content: str | None = None
    password: str | None = None
    theme: dict | None = None


class MovePayload(BaseModel):
    direction: str


class AppPayload(BaseModel):
    type: str
    title: str = ""
    description: str = ""
    parent_id: int | None = None


class ExtensionInstallPayload(BaseModel):
    enabled: bool = True
    mode: str | None = None
    cascade: bool | None = None
    config: dict[str, Any] | None = None


class ExtensionPatchPayload(BaseModel):
    enabled: bool | None = None
    mode: str | None = None
    cascade: bool | None = None
    config: dict[str, Any] | None = None


class SiteExtensionPutPayload(BaseModel):
    enabled: bool | None = None
    mode: str | None = None
    cascade: bool | None = None
    config: dict[str, Any] | None = None


class PackUrlPayload(BaseModel):
    url: str


class SubmissionStatusPayload(BaseModel):
    action: str | None = None
    status: str | None = None


class SubmissionClearPayload(BaseModel):
    status: str | None = None
    plugin_id: str | None = None


class SubmissionBanPayload(BaseModel):
    ip_hash: str


hostname_of = project_service.hostname_of


def _get_extensible_project(db, project_id: int):
    project = store.by_id(db, project_id)
    if project is None:
        return None, api_error("作品不存在", 404)
    if _capabilities_of(project) is None:
        return None, api_error("该类型不支持插件", 400)
    return project, None


def _get_project_and_extension(db, config, project_id: int, ext_id: str):
    project, error = _get_extensible_project(db, project_id)
    if error is not None or project is None:
        return None, None, error
    ext = get_extension(ext_id, config=config)
    if ext is None:
        return None, None, api_error("插件不存在", 404)
    caps = _capabilities_of(project)
    if caps is None or not ext.matches_capabilities(caps):
        return None, None, api_error("该插件不适用于当前应用类型", 400)
    return project, ext, None


def _install_pack_url_sync(config, url: str):
    pack = install_pack_from_url(config, url)
    return pack, list_packs(config)


def _install_pack_zip_sync(config, raw: bytes, replace: bool):
    pack = install_pack_from_zip(config, raw, replace=replace)
    return pack, list_packs(config)


def _sync_pack_sync(config, pack_id: str):
    pack = sync_pack(config, pack_id)
    return pack, list_packs(config)


def resolve_parent(db, parent_id: int | None):
    try:
        return project_service.resolve_parent_by_id(db, parent_id), None
    except ServiceError as exc:
        return None, api_error(exc.message, exc.status_code)


def app_choices() -> list[dict]:
    return [
        {"type": plugin.type, "label": plugin.label, "icon": plugin.icon} for plugin in registry.all_apps()
    ]


def plugin_types() -> list[str]:
    return [plugin.type for plugin in registry.all_apps()]


def admin_scope(request: Request, db):
    config = get_config(request)
    data = read_session(config, request)
    if data is None or data.get("admin") is not True:
        return None, None, RedirectResponse(f"/login?next={quote(request.url.path)}", status_code=303)
    request.scope["siteflow_csrf"] = data.get("csrf")
    return config, data, None


@router.get("/admin")
def admin_page(request: Request, db: DbSession):
    config, _data, redirect = admin_scope(request, db)
    if redirect is not None:
        return redirect
    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "site_title": config.site_title,
            "projects": store.all_projects(db),
            "csrf": csrf_for(request),
            "api_token": config.api_token,
            "app_choices": app_choices(),
            "plugin_types": plugin_types(),
            "stats": stats.get_7day_stats(db, project_id=None),
            "site_ext_catalog": build_site_admin_catalog(db, config=config),
            "ext_packs": list_packs(config),
            "mascot_characters": list(MASCOT_CHARACTERS),
        },
    )


@router.get("/admin/projects/{project_id}")
def admin_project_page(request: Request, project_id: int, db: DbSession):
    config, _data, redirect = admin_scope(request, db)
    if redirect is not None:
        return redirect
    project = store.by_id(db, project_id)
    plugin = registry.get(project.type) if project is not None else None
    if project is None or plugin is None:
        raise HTTPException(404)
    parent = store.by_id(db, project.parent_id) if project.parent_id else None
    context = {
        "site_title": config.site_title,
        "csrf": csrf_for(request),
        "api_token": config.api_token,
        "project": project,
        "parent": parent,
        "depth": store.depth(db, project),
        "children": store.all_projects(db, project.id),
        "plugin_leaf": plugin.leaf,
        "can_nest": not plugin.leaf and store.depth(db, project) < 3,
        "app_choices": app_choices(),
        "plugin_types": plugin_types(),
        "stats": stats.get_7day_stats(db, project_id=project.id),
    }
    caps = _capabilities_of(project)
    if caps is not None:
        content = _parse_project_content(project, config)
        context["content"] = redact_content_extensions(content, capabilities=caps, config=config)
        context["ext_catalog"] = build_project_admin_catalog(
            db, project, capabilities=caps, config=config, content=content
        )
        context["ext_packs"] = list_packs(config)
        context["mascot_characters"] = list(MASCOT_CHARACTERS)
    elif plugin.admin_template:
        context["content"] = plugin.validate_content(project.content)
    if plugin.admin_template:
        context["submission_counts"] = submissions.count_submissions(db, project_id=project.id)
        return templates.TemplateResponse(request, plugin.admin_template, context)
    return templates.TemplateResponse(request, "admin_app.html", context)


@router.get("/admin/projects/{project_id}/posts/new")
@router.get("/admin/projects/{project_id}/posts/{post_slug}/edit")
def admin_blog_post(request: Request, project_id: int, db: DbSession, post_slug: str | None = None):
    config, _data, redirect = admin_scope(request, db)
    if redirect is not None:
        return redirect
    project = store.by_id(db, project_id)
    if project is None or project.type != "blog":
        raise HTTPException(404)
    content = blog_content(project.content, project_slug=project.slug, config=config)
    post = next((post for post in content["posts"] if post["slug"] == post_slug), None)
    if post_slug is not None and post is None:
        raise HTTPException(404)
    return templates.TemplateResponse(
        request,
        "blog_editor.html",
        {
            "site_title": config.site_title,
            "csrf": csrf_for(request),
            "project": project,
            "post": post,
            "ext_editor": build_editor_bundle(content, project=project, post=post, config=config, db=db),
            "parent": store.by_id(db, project.parent_id) if project.parent_id else None,
        },
    )


@router.post("/api/admin/projects/{project_id}/posts")
@router.patch("/api/admin/projects/{project_id}/posts/{post_slug}")
def save_blog_post(
    project_id: int, payload: dict, config: AdminConfig, db: DbSession, post_slug: str | None = None
):
    project = store.by_id(db, project_id)
    if project is None or project.type != "blog":
        return api_error("博客不存在", 404)
    try:
        if post_slug is None:
            saved = project_service.create_blog_post(db, config, project, payload)
        else:
            new_slug: str | None = None
            if "slug" in payload and payload["slug"] is not None:
                raw_slug = str(payload["slug"]).strip()
                if raw_slug:
                    new_slug = raw_slug
                else:
                    fallback = normalize_post_slug(payload.get("title"))
                    if fallback:
                        new_slug = fallback
            saved = project_service.patch_blog_post(
                db, config, project, post_slug, payload, new_slug=new_slug
            )
    except ServiceError as exc:
        status_code = 422 if exc.code == "post_slug_exists" else exc.status_code
        return api_error(exc.message, status_code)
    return {"ok": True, "post": saved}


@router.delete("/api/admin/projects/{project_id}/posts/{post_slug}")
def delete_blog_post(project_id: int, post_slug: str, config: AdminConfig, db: DbSession):
    project = store.by_id(db, project_id)
    if project is None or project.type != "blog":
        return api_error("博客不存在", 404)
    try:
        project_service.delete_blog_post(db, config, project, post_slug)
    except ServiceError as exc:
        return api_error(exc.message, exc.status_code)
    return {"ok": True}


def _save_project_extension_state(
    db,
    config,
    project: Project,
    ext,
    *,
    mode: str,
    cascade: bool | None,
    incoming_config: dict[str, Any] | None,
):
    caps = _capabilities_of(project)
    content = _parse_project_content(project, config)
    old_media = referenced_media_urls(content, capabilities=caps, config=config)
    ext_map = dict(content.get("extensions") or {})
    prev_state = parse_layer_state(ext_map.get(ext.id), is_site=False)

    if mode == "inherit":
        ext_map.pop(ext.id, None)
    else:
        try:
            sparse_cfg = merge_layer_config(
                ext,
                prev_state.config,
                incoming_config,
                strict=True,
                project_slug=project.slug,
            )
        except InvalidContent as exc:
            return api_error(str(exc), 422)
        next_cascade = False
        if caps is not None and "has_children" in caps:
            next_cascade = prev_state.cascade if cascade is None else cascade
        ext_map[ext.id] = {
            "mode": mode,
            "cascade": next_cascade,
            "config": sparse_cfg,
        }

    if ext_map:
        content["extensions"] = ext_map
    else:
        content.pop("extensions", None)
    project.content = json.dumps(content, ensure_ascii=False)
    touch(project)
    db.commit()
    _cleanup_unreferenced_media(
        config,
        project.slug,
        old_media,
        referenced_media_urls(content, capabilities=caps, config=config),
    )
    resolved = resolve_project_extension(
        db, project, ext.id, capabilities=caps, config=config, content=content
    )
    assert resolved is not None
    return {"ok": True, "extension": resolved_catalog_item(resolved)}


@router.get("/api/admin/site/extensions")
def list_site_extensions(config: AdminConfig, db: DbSession):
    return {"ok": True, "extensions": build_site_admin_catalog(db, config=config)}


@router.put("/api/admin/site/extensions/{ext_id}")
def put_site_extension(
    ext_id: str,
    payload: SiteExtensionPutPayload,
    config: AdminConfig,
    db: DbSession,
):
    ext = get_extension(ext_id, config=config)
    if ext is None:
        return api_error("插件不存在", 404)
    site_map = load_site_extensions(db)
    configured = ext.id in site_map
    prev_state = parse_layer_state(site_map.get(ext.id), is_site=True)

    if payload.mode is not None:
        if payload.mode not in VALID_MODES:
            return api_error("插件继承模式必须是 inherit、override 或 disabled", 422)
        if payload.mode == "inherit":
            site_map.pop(ext.id, None)
            save_site_extensions(db, site_map)
            db.commit()
            return {"ok": True, "extension": site_catalog_item(ext, site_map)}
        next_mode = payload.mode
    elif payload.enabled is not None:
        next_mode = "override" if payload.enabled else "disabled"
    elif configured and prev_state.mode != "inherit":
        next_mode = prev_state.mode
    else:
        next_mode = "override"

    next_cascade = prev_state.cascade if payload.cascade is None else payload.cascade
    if not configured and payload.cascade is None:
        next_cascade = True
    try:
        sparse_cfg = merge_layer_config(
            ext,
            prev_state.config,
            payload.config,
            strict=True,
            project_slug="__site__",
        )
    except InvalidContent as exc:
        return api_error(str(exc), 422)
    site_map[ext.id] = {
        "mode": next_mode,
        "enabled": next_mode == "override",
        "cascade": next_cascade,
        "config": sparse_cfg,
    }
    save_site_extensions(db, site_map)
    db.commit()
    return {"ok": True, "extension": site_catalog_item(ext, site_map)}


@router.delete("/api/admin/site/extensions/{ext_id}")
def delete_site_extension(ext_id: str, config: AdminConfig, db: DbSession):
    ext = get_extension(ext_id, config=config)
    if ext is None:
        return api_error("插件不存在", 404)
    site_map = load_site_extensions(db)
    site_map.pop(ext.id, None)
    save_site_extensions(db, site_map)
    db.commit()
    return {"ok": True, "extension": site_catalog_item(ext, site_map)}


@router.get("/api/admin/projects/{project_id}/extensions")
def list_project_extensions(project_id: int, config: AdminConfig, db: DbSession):
    project, error = _get_extensible_project(db, project_id)
    if error is not None or project is None:
        return error
    caps = _capabilities_of(project)
    content = _parse_project_content(project, config)
    return {
        "ok": True,
        "extensions": build_project_admin_catalog(
            db, project, capabilities=caps, config=config, content=content
        ),
    }


@router.post("/api/admin/projects/{project_id}/extensions/{ext_id}/install")
def install_project_extension(
    project_id: int,
    ext_id: str,
    config: AdminConfig,
    db: DbSession,
    payload: ExtensionInstallPayload | None = None,
):
    project, ext, error = _get_project_and_extension(db, config, project_id, ext_id)
    if error is not None or project is None or ext is None:
        return error
    if payload is not None and payload.mode is not None:
        if payload.mode not in VALID_MODES:
            return api_error("插件继承模式必须是 inherit、override 或 disabled", 422)
        mode = payload.mode
    else:
        enabled = payload.enabled if payload is not None else True
        mode = "override" if enabled else "disabled"
    return _save_project_extension_state(
        db,
        config,
        project,
        ext,
        mode=mode,
        cascade=payload.cascade if payload is not None else None,
        incoming_config=payload.config if payload is not None else None,
    )


@router.put("/api/admin/projects/{project_id}/extensions/{ext_id}")
def put_project_extension(
    project_id: int,
    ext_id: str,
    payload: ExtensionPatchPayload,
    config: AdminConfig,
    db: DbSession,
):
    project, ext, error = _get_project_and_extension(db, config, project_id, ext_id)
    if error is not None or project is None or ext is None:
        return error
    content = _parse_project_content(project, config)
    ext_map = content.get("extensions") if isinstance(content.get("extensions"), dict) else {}
    prev_state = parse_layer_state(ext_map.get(ext.id) if isinstance(ext_map, dict) else None, is_site=False)

    if payload.mode is not None:
        if payload.mode not in VALID_MODES:
            return api_error("插件继承模式必须是 inherit、override 或 disabled", 422)
        next_mode = payload.mode
    elif payload.enabled is not None:
        next_mode = "override" if payload.enabled else "disabled"
    elif prev_state.mode != "inherit":
        next_mode = prev_state.mode
    else:
        next_mode = "override"

    return _save_project_extension_state(
        db,
        config,
        project,
        ext,
        mode=next_mode,
        cascade=payload.cascade,
        incoming_config=payload.config,
    )


@router.patch("/api/admin/projects/{project_id}/extensions/{ext_id}")
def update_project_extension(
    project_id: int,
    ext_id: str,
    payload: ExtensionPatchPayload,
    config: AdminConfig,
    db: DbSession,
):
    project, ext, error = _get_project_and_extension(db, config, project_id, ext_id)
    if error is not None or project is None or ext is None:
        return error
    content = _parse_project_content(project, config)
    ext_map = content.get("extensions") if isinstance(content.get("extensions"), dict) else {}
    prev_state = parse_layer_state(ext_map.get(ext.id) if isinstance(ext_map, dict) else None, is_site=False)
    has_local = prev_state.mode != "inherit"
    if not has_local and payload.mode is None and payload.cascade is None:
        return api_error("请先安装该插件", 400)

    if payload.mode is not None:
        if payload.mode not in VALID_MODES:
            return api_error("插件继承模式必须是 inherit、override 或 disabled", 422)
        next_mode = payload.mode
    elif payload.enabled is not None:
        next_mode = "override" if payload.enabled else "disabled"
    elif has_local:
        next_mode = prev_state.mode
    else:
        next_mode = "override"

    return _save_project_extension_state(
        db,
        config,
        project,
        ext,
        mode=next_mode,
        cascade=payload.cascade,
        incoming_config=payload.config,
    )


@router.delete("/api/admin/projects/{project_id}/extensions/{ext_id}")
def uninstall_project_extension(
    project_id: int,
    ext_id: str,
    config: AdminConfig,
    db: DbSession,
):
    project, ext, error = _get_project_and_extension(db, config, project_id, ext_id)
    if error is not None or project is None or ext is None:
        return error
    return _save_project_extension_state(
        db,
        config,
        project,
        ext,
        mode="inherit",
        cascade=None,
        incoming_config=None,
    )


@router.post("/api/admin/projects/{project_id}/extensions/{ext_id}/media")
async def upload_project_extension_media(
    project_id: int,
    ext_id: str,
    file: Annotated[UploadFile, File()],
    config: AdminConfig,
    db: DbSession,
    kind: Annotated[str, Form()] = "",
):
    filename = file.filename or ""
    content_type = file.content_type or ""
    raw = await file.read(COVER_LIMIT + 1)
    await file.close()
    if len(raw) > COVER_LIMIT:
        return api_error("封面不能超过 10MB", 413)
    return await run_in_threadpool(
        _save_project_ext_media,
        project_id,
        ext_id,
        kind,
        raw,
        filename,
        content_type,
        config,
        db,
    )


def _save_project_ext_media(
    project_id: int,
    ext_id: str,
    kind: str,
    raw: bytes,
    filename: str,
    content_type: str,
    config,
    db,
):
    project, ext, error = _get_project_and_extension(db, config, project_id, ext_id)
    if error is not None or project is None or ext is None:
        return error
    content = _parse_project_content(project, config)
    caps = _capabilities_of(project)
    resolved = resolve_project_extension(
        db, project, ext.id, capabilities=caps, config=config, content=content
    )
    if resolved is None or (resolved.local_mode == "inherit" and not resolved.effective_enabled):
        return api_error("请先安装该插件", 400)
    cleaned_kind = kind.strip()
    if not cleaned_kind or cleaned_kind not in ext.media_kinds:
        return api_error("不支持该图片用途", 400)
    try:
        url = save_project_media(
            config,
            project.type,
            project.slug,
            cleaned_kind,
            raw,
            filename=filename,
            content_type=content_type,
        )
    except InvalidUpload as exc:
        return api_error(str(exc), 422)
    return {"ok": True, "url": url}


@router.get("/api/admin/plugin-packs")
def list_plugin_packs(config: AdminConfig):
    return {"ok": True, "packs": list_packs(config)}


@router.post("/api/admin/plugin-packs")
async def subscribe_plugin_pack(payload: PackUrlPayload, config: AdminConfig):
    try:
        pack, packs = await run_in_threadpool(_install_pack_url_sync, config, payload.url)
    except PackError as exc:
        return api_error(exc.message, exc.status_code)
    return {"ok": True, "pack": pack, "packs": packs}


@router.post("/api/admin/plugin-packs/upload")
async def upload_plugin_pack(
    file: Annotated[UploadFile, File()],
    config: AdminConfig,
    replace: Annotated[bool, Form()] = True,
):
    raw = await file.read(PACK_UPLOAD_LIMIT + 1)
    await file.close()
    if len(raw) > PACK_UPLOAD_LIMIT:
        return api_error("插件包不能超过 10MB", 413)
    try:
        pack, packs = await run_in_threadpool(_install_pack_zip_sync, config, raw, replace)
    except PackError as exc:
        return api_error(exc.message, exc.status_code)
    return {"ok": True, "pack": pack, "packs": packs}


@router.post("/api/admin/plugin-packs/{pack_id}/sync")
async def sync_plugin_pack(pack_id: str, config: AdminConfig):
    try:
        pack, packs = await run_in_threadpool(_sync_pack_sync, config, pack_id)
    except PackError as exc:
        return api_error(exc.message, exc.status_code)
    return {"ok": True, "pack": pack, "packs": packs}


@router.delete("/api/admin/plugin-packs/{pack_id}")
def delete_plugin_pack(pack_id: str, config: AdminConfig, db: DbSession):
    try:
        removed = delete_pack(config, pack_id, db)
    except PackError as exc:
        return api_error(exc.message, exc.status_code)
    return {"ok": True, "removed": removed, "packs": list_packs(config)}


@router.get("/api/admin/projects")
def list_projects(config: AdminConfig, db: DbSession, parent_id: int | None = None):
    return {
        "ok": True,
        "projects": [_project_dict_redacted(p, config) for p in store.all_projects(db, parent_id)],
    }


@router.get("/api/admin/projects/{project_id}")
def get_project_detail(project_id: int, config: AdminConfig, db: DbSession):
    project = store.by_id(db, project_id)
    if project is None:
        return api_error("作品不存在", 404)
    return {
        "ok": True,
        "project": _project_dict_redacted(project, config),
        "children": [_project_dict_redacted(c, config) for c in store.all_projects(db, project.id)],
        "stats": stats.get_7day_stats(db, project_id=project.id),
    }


@router.put("/api/admin/projects/{slug}/deploy")
@router.post("/api/admin/projects/{slug}/deploy", include_in_schema=False)
@router.post("/api/deploy/{slug}")
@router.put("/api/deploy/{slug}", include_in_schema=False)
async def deploy_project(
    slug: str,
    file: Annotated[UploadFile, File()],
    config: AdminConfig,
    db: DbSession,
    title: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
    visible: Annotated[bool | None, Form()] = None,
    parent_id: Annotated[int | None, Form()] = None,
):
    if not _SLUG_RE.match(slug):
        return api_error("无效的项目标识（仅支持小写字母、数字、连字符和下划线，长度 1-64）")
    parent, error = resolve_parent(db, parent_id)
    if error is not None:
        return error
    existing = store.by_slug(db, slug)
    if existing is not None and existing.type not in ("static", "html", "zip"):
        return api_error("该标识已被非静态项目占用", 409)
    name = (file.filename or "").lower()
    if not name.endswith((".html", ".htm", ".zip")):
        return api_error("只支持 .html / .htm / .zip 文件")
    suffix = ".html" if name.endswith((".html", ".htm")) else ".zip"
    tmp_token = store.unique_slug_name()
    tmp_path = config.data / "tmp" / f"{tmp_token}{suffix}"
    stage_dir = config.data / "tmp" / f"stage_{tmp_token}"
    backup_dir = config.data / "tmp" / f"backup_{tmp_token}"
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
        try:
            stage_dir.mkdir(parents=True, exist_ok=True)
            if suffix == ".html":
                shutil.copyfile(tmp_path, stage_dir / "index.html")
                entry = "index.html"
            else:
                entry = extract_site(tmp_path, stage_dir, config)
        except InvalidUpload as exc:
            remove_tree(stage_dir)
            return api_error(str(exc), 422)
        except Exception:
            remove_tree(stage_dir)
            raise

        folder = config.data / "projects" / slug
        folder.parent.mkdir(parents=True, exist_ok=True)
        if folder.exists():
            remove_tree(backup_dir)
            folder.rename(backup_dir)
        try:
            stage_dir.rename(folder)
        except Exception:
            if backup_dir.exists() and not folder.exists():
                backup_dir.rename(folder)
            raise
        finally:
            remove_tree(backup_dir)

        if existing is not None:
            existing.entry = entry
            if title.strip():
                existing.title = title.strip()[:200]
            if description.strip():
                existing.description = description.strip()[:500]
            if visible is not None:
                existing.visible = visible
            if parent_id is not None:
                existing.parent_id = parent.id if parent else None
            touch(existing)
            project = existing
        else:
            name_title = (name.rsplit(".", 1)[0] or slug)[:200]
            project_title = (title.strip() or name_title)[:200]
            project = Project(
                slug=slug,
                type="static",
                parent_id=parent.id if parent else None,
                title=project_title,
                description=description.strip()[:500],
                entry=entry,
                visible=True if visible is None else visible,
                sort_order=store.next_sort_order(db, parent.id if parent else None),
            )
            db.add(project)
        db.commit()
        return {"ok": True, "project": project.as_dict(), "url": f"/p/{project.slug}/"}
    finally:
        tmp_path.unlink(missing_ok=True)
        remove_tree(stage_dir)
        remove_tree(backup_dir)


@router.post("/api/admin/projects/app")
def create_app(payload: AppPayload, _auth: AdminConfig, db: DbSession):
    try:
        project = project_service.create_app_project(
            db,
            app_type=payload.type,
            title=payload.title,
            description=payload.description,
            parent_id=payload.parent_id,
        )
    except ServiceError as exc:
        return api_error(exc.message, exc.status_code)
    return {"ok": True, "project": project.as_dict()}


@router.post("/api/admin/projects/upload")
async def upload_project(
    file: Annotated[UploadFile, File()],
    config: AdminConfig,
    db: DbSession,
    parent_id: Annotated[int | None, Form()] = None,
    title: Annotated[str, Form()] = "",
):
    parent, error = resolve_parent(db, parent_id)
    if error is not None:
        return error
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
        name_title = (name.rsplit(".", 1)[0] or "未命名作品")[:200]
        project_title = (title.strip() or name_title)[:200]
        slug = store.unique_slug(db, project_title)
        folder = config.data / "projects" / slug
        try:
            folder.mkdir(parents=True, exist_ok=True)
            if suffix == ".html":
                shutil.copyfile(tmp_path, folder / "index.html")
                entry = "index.html"
            else:
                entry = extract_site(tmp_path, folder, config)
            project_type = "zip" if suffix == ".zip" else "html"
            project = Project(
                slug=slug,
                type=project_type,
                parent_id=parent.id if parent else None,
                title=project_title,
                entry=entry,
                sort_order=store.next_sort_order(db, parent.id if parent else None),
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
    try:
        project = project_service.create_link_project(
            db,
            config,
            url=payload.url,
            title=payload.title,
            description=payload.description,
            parent_id=payload.parent_id,
            fetch_og_fn=fetch_og,
            fetch_image_fn=fetch_image,
        )
    except ServiceError as exc:
        return api_error(exc.message, exc.status_code)
    return {"ok": True, "project": project.as_dict()}


@router.patch("/api/admin/projects/{project_id}")
def patch_project(
    project_id: int,
    payload: PatchPayload,
    config: AdminConfig,
    db: DbSession,
):
    try:
        project = project_service.get_project_by_id(db, project_id)
    except ServiceError as exc:
        return api_error(exc.message, exc.status_code)

    if payload.url is not None and not payload.url.lower().startswith(("http://", "https://")):
        return api_error("链接必须以 http:// 或 https:// 开头")

    incoming_content: dict[str, Any] | None = None
    plugin = registry.get(project.type)
    if payload.content is not None:
        if plugin is None or not plugin.content_editable:
            return api_error("该类型不支持内容编辑")
        if project.type in ("blog", "resume", "bottle"):
            try:
                parsed_incoming = json.loads(payload.content or "{}")
            except json.JSONDecodeError:
                if project.type == "blog":
                    msg = "博客内容不是合法 JSON"
                elif project.type == "resume":
                    msg = "简历内容不是合法 JSON"
                else:
                    msg = "漂流瓶配置不是合法 JSON"
                return api_error(msg, 422)
            if not isinstance(parsed_incoming, dict):
                if project.type == "blog":
                    msg = "博客内容必须是 JSON 对象"
                elif project.type == "resume":
                    msg = "简历内容必须是 JSON 对象"
                else:
                    msg = "漂流瓶配置必须是 JSON 对象"
                return api_error(msg, 422)
            incoming_content = parsed_incoming

    if payload.theme is not None and project.type != "space":
        return api_error("只有空间支持主题配置")

    if payload.title is not None and not payload.title.strip():
        return api_error("标题不能为空", 422)

    try:
        if payload.content is not None:
            if incoming_content is not None:
                project_service.patch_project_content(db, config, project, incoming_content, merge=False)
            elif plugin is not None:
                validated = plugin.validate_content(payload.content)
                project.content = json.dumps(validated, ensure_ascii=False)
                touch(project)
                db.commit()
        if payload.theme is not None:
            theme_dict = dict(payload.theme) if isinstance(payload.theme, dict) else {}
            project_service.patch_project_content(db, config, project, theme_dict, merge=False)
        has_meta = any(
            val is not None
            for val in (
                payload.title,
                payload.description,
                payload.url,
                payload.visible,
                payload.pinned,
                payload.password,
            )
        )
        if has_meta or (payload.content is None and payload.theme is None):
            project_service.patch_project_meta(
                db,
                config,
                project,
                title=payload.title,
                description=payload.description,
                url=payload.url,
                visible=payload.visible,
                pinned=payload.pinned,
                password=payload.password,
            )
    except ServiceError as exc:
        return api_error(exc.message, exc.status_code)
    except InvalidContent as exc:
        return api_error(str(exc), 422)
    return {"ok": True, "project": _project_dict_redacted(project, config)}


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
    raw = await file.read(COVER_LIMIT + 1)
    await file.close()
    if len(raw) > COVER_LIMIT:
        return api_error("封面不能超过 10MB", 413)
    return await run_in_threadpool(_replace_cover, project_id, raw, config, db)


def _replace_cover(project_id: int, raw: bytes, config, db):
    try:
        project = project_service.get_project_by_id(db, project_id)
        project = project_service.replace_cover(db, config, project, raw)
    except ServiceError as exc:
        return api_error(exc.message, exc.status_code)
    return {"ok": True, "project": project.as_dict()}


@router.delete("/api/admin/projects/{project_id}/cover")
def delete_cover(project_id: int, config: AdminConfig, db: DbSession):
    try:
        project = project_service.get_project_by_id(db, project_id)
        project = project_service.remove_cover(db, config, project)
    except ServiceError as exc:
        return api_error(exc.message, exc.status_code)
    return {"ok": True, "project": project.as_dict()}


@router.get("/api/admin/projects/{project_id}/submissions")
def list_project_submissions(
    project_id: int,
    _auth: AdminConfig,
    db: DbSession,
    status: str | None = None,
    plugin_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    project = store.by_id(db, project_id)
    if project is None:
        return api_error("作品不存在", 404)
    filter_status = None
    if status and status != "all":
        if status not in submissions.VALID_STATUSES:
            return api_error("不支持的审核状态")
        filter_status = status
    items = submissions.list_submissions(
        db,
        project_id=project.id,
        plugin_id=plugin_id or None,
        status=filter_status,
        limit=limit,
        offset=offset,
    )
    counts = submissions.count_submissions(db, project_id=project.id, plugin_id=plugin_id or None)
    banned_ips = submissions.list_banned_ips(db, project_id=project.id)
    return {"ok": True, "submissions": items, "counts": counts, "banned_ips": banned_ips}


@router.post("/api/admin/projects/{project_id}/submissions/{sub_id}/status")
def update_project_submission_status(
    project_id: int,
    sub_id: int,
    payload: SubmissionStatusPayload,
    _auth: AdminConfig,
    db: DbSession,
):
    project = store.by_id(db, project_id)
    if project is None:
        return api_error("作品不存在", 404)
    raw_action = (payload.action or payload.status or "").strip().lower()
    action_map = {
        "approve": "approved",
        "approved": "approved",
        "reject": "rejected",
        "rejected": "rejected",
        "pending": "pending",
        "delete": "delete",
    }
    normalized = action_map.get(raw_action)
    if normalized is None:
        return api_error("不支持的审核操作")
    if normalized == "delete":
        deleted = submissions.delete_submission(db, project_id=project.id, sub_id=sub_id)
        if not deleted:
            return api_error("提交记录不存在", 404)
        counts = submissions.count_submissions(db, project_id=project.id)
        return {"ok": True, "deleted": True, "counts": counts}
    updated = submissions.set_submission_status(
        db,
        project_id=project.id,
        sub_id=sub_id,
        status=normalized,
    )
    if updated is None:
        return api_error("提交记录不存在", 404)
    counts = submissions.count_submissions(db, project_id=project.id)
    return {"ok": True, "submission": updated, "counts": counts}


@router.post("/api/admin/projects/{project_id}/submissions/clear")
def clear_project_submissions(
    project_id: int,
    _auth: AdminConfig,
    db: DbSession,
    payload: SubmissionClearPayload | None = None,
):
    project = store.by_id(db, project_id)
    if project is None:
        return api_error("作品不存在", 404)
    filter_status = None
    plugin_id = None
    if payload is not None:
        plugin_id = payload.plugin_id or None
        if payload.status and payload.status != "all":
            if payload.status not in submissions.VALID_STATUSES:
                return api_error("不支持的审核状态")
            filter_status = payload.status
    deleted = submissions.clear_submissions(
        db,
        project_id=project.id,
        plugin_id=plugin_id,
        status=filter_status,
    )
    counts = submissions.count_submissions(db, project_id=project.id, plugin_id=plugin_id)
    return {"ok": True, "deleted": deleted, "counts": counts}


@router.post("/api/admin/projects/{project_id}/submissions/ban")
def ban_project_submission_ip(
    project_id: int,
    payload: SubmissionBanPayload,
    _auth: AdminConfig,
    db: DbSession,
):
    project = store.by_id(db, project_id)
    if project is None:
        return api_error("作品不存在", 404)
    ip_hash = payload.ip_hash.strip().lower()
    if not submissions.is_valid_ip_hash(ip_hash):
        return api_error("无效的 IP 哈希格式")
    submissions.ban_ip_hash(db, project_id=project.id, ip_hash=ip_hash)
    banned_ips = submissions.list_banned_ips(db, project_id=project.id)
    return {"ok": True, "ip_hash": ip_hash, "banned_ips": banned_ips}


@router.delete("/api/admin/projects/{project_id}/submissions/ban/{ip_hash}")
def unban_project_submission_ip(
    project_id: int,
    ip_hash: str,
    _auth: AdminConfig,
    db: DbSession,
):
    project = store.by_id(db, project_id)
    if project is None:
        return api_error("作品不存在", 404)
    cleaned = ip_hash.strip().lower()
    if not submissions.is_valid_ip_hash(cleaned):
        return api_error("无效的 IP 哈希格式")
    removed = submissions.unban_ip_hash(db, project_id=project.id, ip_hash=cleaned)
    banned_ips = submissions.list_banned_ips(db, project_id=project.id)
    return {"ok": True, "unbanned": removed, "banned_ips": banned_ips}


@router.delete("/api/admin/projects/{project_id}")
def delete_project(project_id: int, _auth: AdminConfig, db: DbSession):
    try:
        project = project_service.get_project_by_id(db, project_id)
        project_service.delete_project_cascade(db, _auth, project)
    except ServiceError as exc:
        return api_error(exc.message, exc.status_code)
    return {"ok": True}
