import json
import re
import secrets
import shutil
from datetime import UTC, datetime
from typing import Annotated, Any
from urllib.parse import quote, urlparse

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app import stats, store
from app.auth import csrf_for, hash_project_password, read_session
from app.deps import AdminConfig, DbSession, api_error, get_config
from app.extensions.base import TargetType, capabilities_for_target
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
    build_admin_catalog,
    build_editor_bundle,
    extension_catalog_item,
    merge_content_extension_secrets,
    redact_content_extensions,
    referenced_media_urls,
)
from app.extensions.registry import get as get_extension
from app.models import Project
from app.og import fetch_image, fetch_og
from app.plugins import registry
from app.plugins.base import InvalidContent
from app.plugins.blog.plugin import validate_content as blog_content
from app.plugins.resume.plugin import validate_content as resume_content
from app.plugins.space import validate_space_content
from app.surface import Capability
from app.templating import templates
from app.uploads import (
    InvalidUpload,
    delete_project_media_url,
    extract_site,
    make_cover,
    remove_tree,
    save_cover,
    save_project_media,
)

router = APIRouter()

COVER_LIMIT = 10 * 1024 * 1024
PACK_UPLOAD_LIMIT = 10 * 1024 * 1024
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


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
    config: dict[str, Any] | None = None


class ExtensionPatchPayload(BaseModel):
    enabled: bool | None = None
    config: dict[str, Any] | None = None


class PackUrlPayload(BaseModel):
    url: str


def _target_of(project: Project) -> TargetType | None:
    if project.type == "blog":
        return "blog"
    if project.type == "space":
        return "space"
    if project.type == "resume":
        return "resume"
    return None


def _capabilities_of(project: Project) -> frozenset[Capability] | None:
    plugin = registry.get(project.type)
    if plugin is None:
        return None
    caps = getattr(plugin, "capabilities", None)
    if isinstance(caps, frozenset):
        return caps
    target = _target_of(project)
    return capabilities_for_target(target) if target is not None else None


def _parse_project_content(project: Project, config, *, strict: bool = False) -> dict[str, Any]:
    if project.type == "blog":
        return blog_content(project.content, strict=strict, project_slug=project.slug, config=config)
    if project.type == "space":
        return validate_space_content(
            project.content,
            strict=strict,
            project_slug=project.slug,
            config=config,
        )
    if project.type == "resume":
        return resume_content(project.content, strict=strict, project_slug=project.slug, config=config)
    return {}


def _project_dict_redacted(project: Project, config) -> dict[str, Any]:
    data = project.as_dict()
    caps = _capabilities_of(project)
    if caps is None or not project.content:
        return data
    try:
        parsed = json.loads(project.content)
    except (TypeError, ValueError):
        return data
    if not isinstance(parsed, dict) or "extensions" not in parsed:
        return data
    redacted = redact_content_extensions(parsed, capabilities=caps, config=config)
    data["content"] = json.dumps(redacted, ensure_ascii=False)
    return data


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


def _cleanup_unreferenced_media(
    config,
    project_slug: str,
    old_media: set[str],
    new_media: set[str],
) -> None:
    for stale_url in old_media - new_media:
        delete_project_media_url(config, project_slug, stale_url)


def _install_pack_url_sync(config, url: str):
    pack = install_pack_from_url(config, url)
    return pack, list_packs(config)


def _install_pack_zip_sync(config, raw: bytes, replace: bool):
    pack = install_pack_from_zip(config, raw, replace=replace)
    return pack, list_packs(config)


def _sync_pack_sync(config, pack_id: str):
    pack = sync_pack(config, pack_id)
    return pack, list_packs(config)


def hostname_of(url: str) -> str:
    return (urlparse(url).hostname or "").replace("www.", "")


def touch(project: Project) -> None:
    project.updated_at = datetime.now(UTC).isoformat()


def resolve_parent(db, parent_id: int | None):
    if parent_id is None:
        return None, None
    parent = store.by_id(db, parent_id)
    if parent is None:
        return None, api_error("父级不存在", 404)
    plugin = registry.get(parent.type)
    if plugin is None or plugin.leaf:
        return None, api_error("只有可包含子项的应用可以嵌套")
    if store.depth(db, parent) >= 3:
        return None, api_error("已达最大嵌套深度（3 层）")
    return parent, None


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
        context["ext_catalog"] = build_admin_catalog(content, capabilities=caps, config=config)
        context["ext_packs"] = list_packs(config)
        context["mascot_characters"] = list(MASCOT_CHARACTERS)
    elif plugin.admin_template:
        context["content"] = plugin.validate_content(project.content)
    if plugin.admin_template:
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
            "ext_editor": build_editor_bundle(content, project=project, post=post, config=config),
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
    content = blog_content(project.content, project_slug=project.slug, config=config)
    old_media = referenced_media_urls(content, target="blog", config=config)
    posts = content["posts"]
    index = next((i for i, post in enumerate(posts) if post["slug"] == post_slug), None)
    if post_slug is not None and index is None:
        return api_error("文章不存在，请返回文章列表", 404)
    candidate = dict(payload)
    if index is None:
        posts.append(candidate)
    else:
        existing_meta = posts[index].get("meta")
        if isinstance(existing_meta, dict):
            incoming_meta = candidate.get("meta")
            if incoming_meta is None:
                candidate["meta"] = dict(existing_meta)
            elif isinstance(incoming_meta, dict):
                merged_meta = dict(existing_meta)
                for key, value in incoming_meta.items():
                    if value == "" or value is None:
                        merged_meta.pop(key, None)
                    else:
                        merged_meta[key] = value
                candidate["meta"] = merged_meta
        posts[index] = candidate
    try:
        validated = blog_content(
            json.dumps(content, ensure_ascii=False),
            strict=True,
            project_slug=project.slug,
            config=config,
        )
        saved = blog_content(
            json.dumps({"posts": [candidate]}, ensure_ascii=False),
            strict=True,
            project_slug=project.slug,
            config=config,
        )["posts"][0]
    except InvalidContent as exc:
        return api_error(str(exc), 422)
    project.content = json.dumps(validated, ensure_ascii=False)
    touch(project)
    db.commit()
    _cleanup_unreferenced_media(
        config,
        project.slug,
        old_media,
        referenced_media_urls(validated, target="blog", config=config),
    )
    return {"ok": True, "post": saved}


@router.delete("/api/admin/projects/{project_id}/posts/{post_slug}")
def delete_blog_post(project_id: int, post_slug: str, config: AdminConfig, db: DbSession):
    project = store.by_id(db, project_id)
    if project is None or project.type != "blog":
        return api_error("博客不存在", 404)
    content = blog_content(project.content, project_slug=project.slug, config=config)
    old_media = referenced_media_urls(content, target="blog", config=config)
    if not any(post["slug"] == post_slug for post in content["posts"]):
        return api_error("文章不存在，请返回文章列表", 404)
    content["posts"] = [post for post in content["posts"] if post["slug"] != post_slug]
    project.content = json.dumps(content, ensure_ascii=False)
    touch(project)
    db.commit()
    _cleanup_unreferenced_media(
        config,
        project.slug,
        old_media,
        referenced_media_urls(content, target="blog", config=config),
    )
    return {"ok": True}


@router.get("/api/admin/projects/{project_id}/extensions")
def list_project_extensions(project_id: int, config: AdminConfig, db: DbSession):
    project, error = _get_extensible_project(db, project_id)
    if error is not None or project is None:
        return error
    caps = _capabilities_of(project)
    content = _parse_project_content(project, config)
    return {"ok": True, "extensions": build_admin_catalog(content, capabilities=caps, config=config)}


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
    caps = _capabilities_of(project)
    content = _parse_project_content(project, config)
    old_media = referenced_media_urls(content, capabilities=caps, config=config)
    ext_map = dict(content.get("extensions") or {})
    existing_state = ext_map.get(ext.id)
    raw_existing_cfg = existing_state.get("config") if isinstance(existing_state, dict) else None
    existing_cfg: dict[str, Any] = raw_existing_cfg if isinstance(raw_existing_cfg, dict) else {}
    enabled = payload.enabled if payload is not None else True
    if payload is not None and payload.config is not None:
        raw_cfg: object = ext.merge_config(existing_cfg, payload.config)
    else:
        raw_cfg = existing_cfg or None
    try:
        normalized_cfg = ext.normalize_config(raw_cfg, strict=True, project_slug=project.slug)
    except InvalidContent as exc:
        return api_error(str(exc), 422)
    ext_map[ext.id] = {"installed": True, "enabled": enabled, "config": normalized_cfg}
    content["extensions"] = ext_map
    project.content = json.dumps(content, ensure_ascii=False)
    touch(project)
    db.commit()
    _cleanup_unreferenced_media(
        config,
        project.slug,
        old_media,
        referenced_media_urls(content, capabilities=caps, config=config),
    )
    return {"ok": True, "extension": extension_catalog_item(ext, content)}


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
    caps = _capabilities_of(project)
    content = _parse_project_content(project, config)
    ext_map = dict(content.get("extensions") or {})
    state = ext_map.get(ext.id)
    if not isinstance(state, dict) or state.get("installed") is not True:
        return api_error("请先安装该插件", 400)
    old_media = referenced_media_urls(content, capabilities=caps, config=config)
    enabled = state.get("enabled") is True if payload.enabled is None else payload.enabled
    raw_existing_cfg = state.get("config")
    existing_cfg: dict[str, Any] = raw_existing_cfg if isinstance(raw_existing_cfg, dict) else {}
    if payload.config is not None:
        merged_cfg = ext.merge_config(existing_cfg, payload.config)
        try:
            normalized_cfg = ext.normalize_config(merged_cfg, strict=True, project_slug=project.slug)
        except InvalidContent as exc:
            return api_error(str(exc), 422)
    else:
        normalized_cfg = ext.normalize_config(existing_cfg, strict=False, project_slug=project.slug)
    ext_map[ext.id] = {"installed": True, "enabled": enabled, "config": normalized_cfg}
    content["extensions"] = ext_map
    project.content = json.dumps(content, ensure_ascii=False)
    touch(project)
    db.commit()
    _cleanup_unreferenced_media(
        config,
        project.slug,
        old_media,
        referenced_media_urls(content, capabilities=caps, config=config),
    )
    return {"ok": True, "extension": extension_catalog_item(ext, content)}


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
    caps = _capabilities_of(project)
    content = _parse_project_content(project, config)
    old_media = referenced_media_urls(content, capabilities=caps, config=config)
    ext_map = dict(content.get("extensions") or {})
    ext_map.pop(ext.id, None)
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
    return {"ok": True, "extension": extension_catalog_item(ext, content)}


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
    ext_map = content.get("extensions")
    state = ext_map.get(ext.id) if isinstance(ext_map, dict) else None
    if not isinstance(state, dict) or state.get("installed") is not True:
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
    visible: Annotated[bool, Form()] = True,
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
                visible=visible,
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
    plugin = registry.get(payload.type)
    if plugin is None:
        return api_error("不支持的应用类型")
    parent, error = resolve_parent(db, payload.parent_id)
    if error is not None:
        return error
    title = (payload.title.strip() or plugin.label)[:200]
    content = json.dumps(plugin.default_content(), ensure_ascii=False)
    project = Project(
        slug=store.unique_slug(db, title),
        type=payload.type,
        parent_id=parent.id if parent else None,
        title=title,
        description=payload.description.strip()[:500],
        content=content,
        sort_order=store.next_sort_order(db, parent.id if parent else None),
    )
    db.add(project)
    db.commit()
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
    if not payload.url.lower().startswith(("http://", "https://")):
        return api_error("链接必须以 http:// 或 https:// 开头")
    parent, error = resolve_parent(db, payload.parent_id)
    if error is not None:
        return error
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
        parent_id=parent.id if parent else None,
        title=title[:200],
        description=description[:500],
        url=payload.url,
        cover=cover,
        sort_order=store.next_sort_order(db, parent.id if parent else None),
    )
    db.add(project)
    db.commit()
    return {"ok": True, "project": project.as_dict()}


@router.patch("/api/admin/projects/{project_id}")
def patch_project(
    project_id: int,
    payload: PatchPayload,
    config: AdminConfig,
    db: DbSession,
):
    project = store.by_id(db, project_id)
    if project is None:
        return api_error("作品不存在", 404)
    updates = payload.model_dump(exclude_none=True)
    url = updates.get("url")
    if url is not None and not url.lower().startswith(("http://", "https://")):
        return api_error("链接必须以 http:// 或 https:// 开头")
    old_ext_media: set[str] | None = None
    ext_target = _target_of(project)
    ext_caps = _capabilities_of(project)
    content = updates.pop("content", None)
    if content is not None:
        plugin = registry.get(project.type)
        if plugin is None or not plugin.content_editable:
            return api_error("该类型不支持内容编辑")
        try:
            if ext_target in ("blog", "resume"):
                existing_parsed = _parse_project_content(project, config)
                old_ext_media = referenced_media_urls(
                    existing_parsed,
                    capabilities=ext_caps,
                    config=config,
                )
                try:
                    incoming_parsed = json.loads(content or "{}")
                except json.JSONDecodeError as exc:
                    msg = "博客内容不是合法 JSON" if ext_target == "blog" else "简历内容不是合法 JSON"
                    raise InvalidContent(msg) from exc
                if not isinstance(incoming_parsed, dict):
                    msg = "博客内容必须是 JSON 对象" if ext_target == "blog" else "简历内容必须是 JSON 对象"
                    raise InvalidContent(msg)
                if "extensions" not in incoming_parsed:
                    if existing_parsed.get("extensions"):
                        incoming_parsed["extensions"] = existing_parsed["extensions"]
                else:
                    incoming_parsed = merge_content_extension_secrets(
                        existing_parsed,
                        incoming_parsed,
                        capabilities=ext_caps,
                        config=config,
                    )
                merged_raw = json.dumps(incoming_parsed, ensure_ascii=False)
                if ext_target == "blog":
                    validated = blog_content(
                        merged_raw,
                        strict=True,
                        project_slug=project.slug,
                        config=config,
                    )
                else:
                    validated = resume_content(
                        merged_raw,
                        strict=True,
                        project_slug=project.slug,
                        config=config,
                    )
            else:
                validated = plugin.validate_content(content)
        except InvalidContent as exc:
            return api_error(str(exc), 422)
        project.content = json.dumps(validated, ensure_ascii=False)
    if project.type == "blog" and ("title" in updates or "description" in updates):
        blog = blog_content(project.content, project_slug=project.slug, config=config)
        for field, limit in (("title", 200), ("description", 500)):
            if field in updates:
                value = updates[field].strip()[:limit]
                if field == "title" and not value:
                    return api_error("标题不能为空", 422)
                updates[field] = value
                blog[field] = value
        project.content = json.dumps(blog, ensure_ascii=False)
    theme = updates.pop("theme", None)
    if theme is not None:
        if project.type != "space":
            return api_error("只有空间支持主题配置")
        existing_space = validate_space_content(project.content, project_slug=project.slug, config=config)
        merged_space = dict(theme) if isinstance(theme, dict) else {}
        if existing_space.get("extensions") and "extensions" not in merged_space:
            merged_space["extensions"] = existing_space["extensions"]
        validated_theme = validate_space_content(
            merged_space,
            project_slug=project.slug,
            config=config,
        )
        project.content = json.dumps(validated_theme, ensure_ascii=False)
    password = updates.pop("password", None)
    if password is not None:
        p_clean = password.strip()
        if p_clean in ("", "none", "clear"):
            project.password_hash = None
        else:
            project.password_hash = hash_project_password(p_clean)
    for field, value in updates.items():
        setattr(project, field, value)
    touch(project)
    db.commit()
    if old_ext_media is not None and ext_caps is not None:
        new_ext_media = referenced_media_urls(
            _parse_project_content(project, config),
            capabilities=ext_caps,
            config=config,
        )
        _cleanup_unreferenced_media(config, project.slug, old_ext_media, new_ext_media)
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
    project = store.by_id(db, project_id)
    if project is None:
        return api_error("作品不存在", 404)
    filename = f"{project.slug}-{secrets.token_hex(6)}.webp"
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


@router.delete("/api/admin/projects/{project_id}/cover")
def delete_cover(project_id: int, config: AdminConfig, db: DbSession):
    project = store.by_id(db, project_id)
    if project is None:
        return api_error("作品不存在", 404)
    old_name = project.cover
    project.cover = ""
    touch(project)
    db.commit()
    if old_name:
        (config.data / "media" / "covers" / old_name).unlink(missing_ok=True)
    return {"ok": True, "project": project.as_dict()}


@router.delete("/api/admin/projects/{project_id}")
def delete_project(project_id: int, _auth: AdminConfig, db: DbSession):
    project = store.by_id(db, project_id)
    if project is None:
        return api_error("作品不存在", 404)
    config = _auth
    rows = [*reversed(store.descendants(db, project)), project]
    store.delete_stats(db, [row.id for row in rows])
    for row in rows:
        store.delete_files(config, row)
        db.delete(row)
        db.flush()
    db.commit()
    return {"ok": True}
