from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, File, Form, Request, Response, UploadFile, status
from fastapi import routing as fastapi_routing
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app import og, project_service, store, tokens
from app.deps import ApiAuth, ApiContext, DbSession, ServiceError, require_project_access, require_scope
from app.models import Project

router = APIRouter(prefix="/api/v1", tags=["api-v1"])


class CreateAppPayload(BaseModel):
    type: str
    title: str = ""
    description: str = ""
    parent_slug: str | None = None
    slug: str | None = None


class CreateLinkPayload(BaseModel):
    url: str
    title: str = ""
    description: str = ""
    parent_slug: str | None = None
    slug: str | None = None


class PatchProjectPayload(BaseModel):
    title: str | None = None
    description: str | None = None
    url: str | None = None
    visible: bool | None = None
    pinned: bool | None = None
    parent_slug: str | None = None
    password: str | None = None


class BlogPostCreatePayload(BaseModel):
    title: str
    slug: str | None = None
    date: str | None = None
    tags: list[str] = Field(default_factory=list)
    summary: str = ""
    body: str = ""
    meta: dict[str, Any] | None = None


class BlogPostUpsertPayload(BaseModel):
    title: str
    date: str | None = None
    tags: list[str] = Field(default_factory=list)
    summary: str = ""
    body: str = ""
    meta: dict[str, Any] | None = None


class BlogPostPatchPayload(BaseModel):
    title: str | None = None
    date: str | None = None
    tags: list[str] | None = None
    summary: str | None = None
    body: str | None = None
    meta: dict[str, Any] | None = None
    new_slug: str | None = None


class ExtensionStatePayload(BaseModel):
    mode: Literal["inherit", "override", "disabled"] | None = None
    enabled: bool | None = None
    cascade: bool | None = None
    config: dict[str, Any] | None = None


class SubmissionStatusPayload(BaseModel):
    action: str | None = None
    status: str | None = None


class TokenCreatePayload(BaseModel):
    name: str
    scopes: list[str]
    allowed_slugs: list[str] = Field(default_factory=list)
    expires_at: str = ""


def _project_summary_with_parent(db: Session, project: Project) -> dict[str, Any]:
    parent = store.by_id(db, project.parent_id) if project.parent_id is not None else None
    return project_service.project_summary(
        project,
        parent_slug=parent.slug if parent is not None else None,
    )


def _get_accessible_project(auth: ApiContext, db: Session, slug: str) -> Project:
    project = project_service.get_project_by_slug(db, slug)
    require_project_access(auth, db, project)
    return project


def _resolve_accessible_parent(
    auth: ApiContext,
    db: Session,
    parent_slug: str | None,
) -> Project | None:
    if parent_slug is None or parent_slug == "":
        return None
    raw_parent = store.by_slug(db, parent_slug)
    if raw_parent is not None:
        require_project_access(auth, db, raw_parent)
    return project_service.resolve_parent_by_slug(db, parent_slug)


def _ensure_create_scope(
    auth: ApiContext,
    *,
    parent: Project | None,
    slug: str | None,
) -> None:
    if auth.principal.allowed_slugs is None:
        return
    if parent is not None:
        return
    if slug and slug in auth.principal.allowed_slugs:
        return
    raise ServiceError(
        "当前 API 令牌无权在该作用域外创建项目",
        403,
        code="forbidden_project",
        hint="请在令牌允许的父级空间下创建，或显式指定允许列表中的 slug",
    )


def _require_global_admin(auth: ApiContext) -> None:
    require_scope(auth, "admin")
    if not auth.principal.is_admin:
        raise ServiceError(
            "受限项目作用域的令牌无权管理全站 API 令牌",
            403,
            code="forbidden_project",
            hint="仅全站管理员令牌或管理员会话可管理 API 令牌",
        )


def _deploy_static_sync(
    auth: ApiContext,
    db: Session,
    slug: str,
    raw_bytes: bytes,
    filename: str,
    title: str,
    description: str,
    visible: bool | None,
    parent_slug: str | None,
) -> tuple[dict[str, Any], bool, str]:
    clean_slug = project_service.validate_slug(slug)
    parent = _resolve_accessible_parent(auth, db, parent_slug)
    existing = store.by_slug(db, clean_slug)
    if existing is not None:
        require_project_access(auth, db, existing)

    def _allowed_parent_check(resolved_parent: Project | None) -> None:
        if auth.principal.allowed_slugs is None:
            return
        if resolved_parent is not None:
            require_project_access(auth, db, resolved_parent)
            return
        if clean_slug not in auth.principal.allowed_slugs:
            raise ServiceError(
                "当前 API 令牌无权在该作用域外创建项目",
                403,
                code="forbidden_project",
                hint="请在令牌允许的父级空间下部署，或使用允许列表中的 slug",
            )

    project, created = project_service.deploy_static_bytes(
        db,
        auth.config,
        slug=clean_slug,
        raw_bytes=raw_bytes,
        filename=filename,
        title=title,
        description=description,
        visible=visible,
        parent_id=parent.id if parent is not None else None,
        allowed_parent_check=_allowed_parent_check,
    )
    return _project_summary_with_parent(db, project), created, project.slug


def _replace_cover_sync(auth: ApiContext, db: Session, slug: str, raw: bytes) -> dict[str, Any]:
    project = _get_accessible_project(auth, db, slug)
    updated = project_service.replace_cover(db, auth.config, project, raw)
    return _project_summary_with_parent(db, updated)


def _upload_blog_media_sync(
    auth: ApiContext,
    db: Session,
    slug: str,
    raw: bytes,
    kind: str,
    filename: str,
    content_type: str,
) -> dict[str, str]:
    project = _get_accessible_project(auth, db, slug)
    return project_service.upload_blog_media(
        auth.config,
        project,
        raw,
        kind=kind,
        filename=filename,
        content_type=content_type,
    )


@router.get("/whoami")
def whoami(auth: ApiAuth) -> dict[str, Any]:
    principal = auth.principal
    return {
        "ok": True,
        "api_version": "1",
        "site_title": auth.config.site_title,
        "principal": {
            "kind": principal.kind,
            "is_admin": principal.is_admin,
            "scopes": sorted(principal.scopes),
            "allowed_slugs": (
                sorted(principal.allowed_slugs) if principal.allowed_slugs is not None else None
            ),
            "token_id": principal.token_id,
            "name": principal.name,
            "prefix": principal.prefix,
        },
    }


def _collect_v1_routes(app_routes: Sequence[Any]) -> list[Any]:
    iter_contexts = getattr(fastapi_routing, "iter_route_contexts", None)
    if callable(iter_contexts):
        return [
            ctx
            for ctx in iter_contexts(app_routes)
            if isinstance(getattr(ctx, "route", None), APIRoute)
            and isinstance(getattr(ctx, "path", None), str)
            and ctx.path.startswith("/api/v1/")
        ]
    return [
        route for route in app_routes if isinstance(route, APIRoute) and route.path.startswith("/api/v1/")
    ]


@router.get("/openapi.json")
def v1_openapi(request: Request, auth: ApiAuth) -> dict[str, Any]:
    require_scope(auth, "read")
    v1_routes = _collect_v1_routes(request.app.routes)
    schema = get_openapi(
        title="SiteFlow API v1",
        version="1.0.0",
        openapi_version="3.1.0",
        description="面向 Agent 与自动化工具的 SiteFlow 标准化 REST API",
        routes=v1_routes,
    )
    components = schema.setdefault("components", {})
    security_schemes = components.setdefault("securitySchemes", {})
    security_schemes["BearerAuth"] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "SiteFlow API Token (sft_...)",
    }
    security_schemes["ApiKeyAuth"] = {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
    }
    schema["security"] = [{"BearerAuth": []}, {"ApiKeyAuth": []}]
    return schema


@router.get("/projects")
def list_projects(
    auth: ApiAuth,
    db: DbSession,
    view: Literal["flat", "tree"] = "flat",
    type: str | None = None,
    parent_slug: str | None = None,
) -> dict[str, Any]:
    require_scope(auth, "read")
    if parent_slug and (parent_row := store.by_slug(db, parent_slug)) is not None:
        require_project_access(auth, db, parent_row)
    projects = project_service.list_projects_view(
        db,
        view=view,
        project_type=type,
        parent_slug=parent_slug,
        allowed_slugs=auth.principal.allowed_slugs,
    )
    return {"ok": True, "view": view, "projects": projects}


@router.post("/projects/app", status_code=status.HTTP_201_CREATED)
def create_app_project(
    payload: CreateAppPayload,
    auth: ApiAuth,
    db: DbSession,
) -> dict[str, Any]:
    require_scope(auth, "projects:write")
    parent = _resolve_accessible_parent(auth, db, payload.parent_slug)
    _ensure_create_scope(auth, parent=parent, slug=payload.slug)
    project = project_service.create_app_project(
        db,
        app_type=payload.type,
        title=payload.title,
        description=payload.description,
        parent_id=parent.id if parent is not None else None,
        slug=payload.slug,
    )
    return {"ok": True, "project": _project_summary_with_parent(db, project)}


@router.post("/projects/link", status_code=status.HTTP_201_CREATED)
def create_link_project(
    payload: CreateLinkPayload,
    auth: ApiAuth,
    db: DbSession,
) -> dict[str, Any]:
    require_scope(auth, "projects:write")
    parent = _resolve_accessible_parent(auth, db, payload.parent_slug)
    _ensure_create_scope(auth, parent=parent, slug=payload.slug)
    project = project_service.create_link_project(
        db,
        auth.config,
        url=payload.url,
        title=payload.title,
        description=payload.description,
        parent_id=parent.id if parent is not None else None,
        slug=payload.slug,
        fetch_og_fn=og.fetch_og,
        fetch_image_fn=og.fetch_image,
    )
    return {"ok": True, "project": _project_summary_with_parent(db, project)}


@router.get("/projects/{slug}")
def get_project(slug: str, auth: ApiAuth, db: DbSession) -> dict[str, Any]:
    require_scope(auth, "read")
    project = _get_accessible_project(auth, db, slug)
    return {"ok": True, **project_service.project_detail(db, auth.config, project)}


@router.patch("/projects/{slug}")
def patch_project(
    slug: str,
    payload: PatchProjectPayload,
    auth: ApiAuth,
    db: DbSession,
) -> dict[str, Any]:
    require_scope(auth, "projects:write")
    fields = payload.model_fields_set
    if "password" in fields:
        require_scope(auth, "admin")
    project = _get_accessible_project(auth, db, slug)

    update_parent = "parent_slug" in fields
    parent_id: int | None = None
    if update_parent:
        if payload.parent_slug is None or payload.parent_slug == "":
            if auth.principal.allowed_slugs is not None and project.slug not in auth.principal.allowed_slugs:
                raise ServiceError(
                    "当前 API 令牌无权将项目迁出允许的作用域",
                    403,
                    code="forbidden_project",
                    hint="不能将子项目移回根目录以脱离父空间作用域",
                )
            parent_id = None
        else:
            target_parent = store.by_slug(db, payload.parent_slug)
            if target_parent is None:
                raise ServiceError(
                    "父级不存在",
                    404,
                    code="parent_not_found",
                    hint="请检查 parent_slug 是否正确",
                )
            require_project_access(auth, db, target_parent)
            parent_id = target_parent.id

    password_arg: str | None = None
    if "password" in fields:
        password_arg = "" if payload.password is None else payload.password

    updated = project_service.patch_project_meta(
        db,
        auth.config,
        project,
        title=payload.title if "title" in fields else None,
        description=payload.description if "description" in fields else None,
        url=payload.url if "url" in fields else None,
        visible=payload.visible if "visible" in fields else None,
        pinned=payload.pinned if "pinned" in fields else None,
        parent_id=parent_id,
        update_parent=update_parent,
        password=password_arg,
    )
    return {"ok": True, "project": _project_summary_with_parent(db, updated)}


@router.delete("/projects/{slug}")
def delete_project(slug: str, auth: ApiAuth, db: DbSession) -> dict[str, Any]:
    require_scope(auth, "projects:write")
    project = _get_accessible_project(auth, db, slug)
    project_service.delete_project_cascade(db, auth.config, project)
    return {"ok": True, "deleted": True, "slug": slug}


@router.get("/projects/{slug}/content")
def get_project_content(slug: str, auth: ApiAuth, db: DbSession) -> dict[str, Any]:
    require_scope(auth, "read")
    project = _get_accessible_project(auth, db, slug)
    return {
        "ok": True,
        "slug": project.slug,
        "type": project.type,
        "content": project_service.parsed_project_content(project, auth.config, redact=True),
    }


@router.patch("/projects/{slug}/content")
def patch_project_content(
    slug: str,
    payload: dict[str, Any],
    auth: ApiAuth,
    db: DbSession,
) -> dict[str, Any]:
    require_scope(auth, "content:write")
    project = _get_accessible_project(auth, db, slug)
    if "extensions" in payload:
        require_scope(auth, "extensions:write")
    if project.type == "blog" and "posts" in payload:
        require_scope(auth, "posts:write")
    updated_content = project_service.patch_project_content(
        db,
        auth.config,
        project,
        payload,
        merge=True,
    )
    return {
        "ok": True,
        "slug": project.slug,
        "type": project.type,
        "content": updated_content,
    }


@router.put("/projects/{slug}/deploy")
async def deploy_project(
    slug: str,
    file: Annotated[UploadFile, File()],
    response: Response,
    auth: ApiAuth,
    db: DbSession,
    title: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
    visible: Annotated[bool | None, Form()] = None,
    parent_slug: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    require_scope(auth, "deploy:write")
    project_service.validate_slug(slug)
    filename = file.filename or ""
    if not Path(filename).name.lower().endswith((".html", ".htm", ".zip")):
        await file.close()
        raise ServiceError(
            "只支持 .html / .htm / .zip 文件",
            400,
            code="unsupported_file_type",
            hint="请上传 .html、.htm 或 .zip 格式文件",
        )
    chunks: list[bytes] = []
    total = 0
    try:
        while chunk := await file.read(1024 * 1024):
            total += len(chunk)
            if total > auth.config.upload_limit:
                raise ServiceError("文件超出大小限制", 413, code="file_too_large")
            chunks.append(chunk)
    finally:
        await file.close()
    raw_bytes = b"".join(chunks)
    summary, created, project_slug = await run_in_threadpool(
        _deploy_static_sync,
        auth,
        db,
        slug,
        raw_bytes,
        filename,
        title,
        description,
        visible,
        parent_slug,
    )
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return {
        "ok": True,
        "created": created,
        "project": summary,
        "url": f"/p/{project_slug}/",
    }


@router.post("/projects/{slug}/cover")
async def upload_project_cover(
    slug: str,
    file: Annotated[UploadFile, File()],
    auth: ApiAuth,
    db: DbSession,
) -> dict[str, Any]:
    require_scope(auth, "projects:write")
    raw = await file.read(project_service.COVER_LIMIT + 1)
    await file.close()
    if len(raw) > project_service.COVER_LIMIT:
        raise ServiceError("封面不能超过 10MB", 413, code="file_too_large")
    summary = await run_in_threadpool(_replace_cover_sync, auth, db, slug, raw)
    return {"ok": True, "project": summary}


@router.delete("/projects/{slug}/cover")
def delete_project_cover(slug: str, auth: ApiAuth, db: DbSession) -> dict[str, Any]:
    require_scope(auth, "projects:write")
    project = _get_accessible_project(auth, db, slug)
    updated = project_service.remove_cover(db, auth.config, project)
    return {"ok": True, "project": _project_summary_with_parent(db, updated)}


@router.get("/blogs/{slug}/posts")
def list_blog_posts(
    slug: str,
    auth: ApiAuth,
    db: DbSession,
    tag: str | None = None,
    q: str | None = None,
    include_body: bool = False,
) -> dict[str, Any]:
    require_scope(auth, "read")
    project = _get_accessible_project(auth, db, slug)
    posts = project_service.list_blog_posts(
        auth.config,
        project,
        tag=tag,
        q=q,
        include_body=include_body,
    )
    return {"ok": True, "slug": project.slug, "posts": posts, "total": len(posts)}


@router.post("/blogs/{slug}/posts", status_code=status.HTTP_201_CREATED)
def create_blog_post(
    slug: str,
    payload: BlogPostCreatePayload,
    auth: ApiAuth,
    db: DbSession,
) -> dict[str, Any]:
    require_scope(auth, "posts:write")
    project = _get_accessible_project(auth, db, slug)
    data = payload.model_dump(exclude_none=True)
    saved = project_service.create_blog_post(db, auth.config, project, data)
    return {"ok": True, "post": saved}


@router.get("/blogs/{slug}/posts/{post_slug}")
def get_blog_post(
    slug: str,
    post_slug: str,
    auth: ApiAuth,
    db: DbSession,
) -> dict[str, Any]:
    require_scope(auth, "read")
    project = _get_accessible_project(auth, db, slug)
    post = project_service.get_blog_post(auth.config, project, post_slug)
    return {"ok": True, "post": post}


@router.put("/blogs/{slug}/posts/{post_slug}")
def upsert_blog_post(
    slug: str,
    post_slug: str,
    payload: BlogPostUpsertPayload,
    response: Response,
    auth: ApiAuth,
    db: DbSession,
) -> dict[str, Any]:
    require_scope(auth, "posts:write")
    project = _get_accessible_project(auth, db, slug)
    data: dict[str, Any] = {
        "title": payload.title,
        "tags": payload.tags,
        "summary": payload.summary,
        "body": payload.body,
    }
    if payload.date is not None:
        data["date"] = payload.date
    if "meta" in payload.model_fields_set:
        data["meta"] = payload.meta
    saved, created = project_service.upsert_blog_post(db, auth.config, project, post_slug, data)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return {"ok": True, "created": created, "post": saved}


@router.patch("/blogs/{slug}/posts/{post_slug}")
def patch_blog_post(
    slug: str,
    post_slug: str,
    payload: BlogPostPatchPayload,
    auth: ApiAuth,
    db: DbSession,
) -> dict[str, Any]:
    require_scope(auth, "posts:write")
    project = _get_accessible_project(auth, db, slug)
    fields = payload.model_fields_set
    patch_dict: dict[str, Any] = {}
    for field_name in ("title", "date", "tags", "summary", "body", "meta"):
        if field_name in fields:
            patch_dict[field_name] = getattr(payload, field_name)
    new_slug = payload.new_slug if "new_slug" in fields else None
    saved = project_service.patch_blog_post(
        db,
        auth.config,
        project,
        post_slug,
        patch_dict,
        new_slug=new_slug,
    )
    return {"ok": True, "post": saved}


@router.delete("/blogs/{slug}/posts/{post_slug}")
def delete_blog_post(
    slug: str,
    post_slug: str,
    auth: ApiAuth,
    db: DbSession,
) -> dict[str, Any]:
    require_scope(auth, "posts:write")
    project = _get_accessible_project(auth, db, slug)
    project_service.delete_blog_post(db, auth.config, project, post_slug)
    return {"ok": True, "deleted": True, "slug": post_slug}


@router.post("/blogs/{slug}/media")
async def upload_blog_media(
    slug: str,
    file: Annotated[UploadFile, File()],
    auth: ApiAuth,
    db: DbSession,
    kind: Annotated[str, Form()] = "image",
) -> dict[str, Any]:
    require_scope(auth, "posts:write")
    filename = file.filename or ""
    content_type = file.content_type or ""
    raw = await file.read(project_service.COVER_LIMIT + 1)
    await file.close()
    if len(raw) > project_service.COVER_LIMIT:
        raise ServiceError("图片不能超过 10MB", 413, code="file_too_large")
    result = await run_in_threadpool(
        _upload_blog_media_sync,
        auth,
        db,
        slug,
        raw,
        kind,
        filename,
        content_type,
    )
    return {"ok": True, "url": result["url"], "markdown": result["markdown"]}


@router.get("/projects/{slug}/extensions")
def list_project_extensions(slug: str, auth: ApiAuth, db: DbSession) -> dict[str, Any]:
    require_scope(auth, "read")
    project = _get_accessible_project(auth, db, slug)
    extensions = project_service.list_project_extensions_v1(db, auth.config, project)
    return {"ok": True, "slug": project.slug, "extensions": extensions}


@router.put("/projects/{slug}/extensions/{ext_id}")
def put_project_extension(
    slug: str,
    ext_id: str,
    payload: ExtensionStatePayload,
    auth: ApiAuth,
    db: DbSession,
) -> dict[str, Any]:
    require_scope(auth, "extensions:write")
    project = _get_accessible_project(auth, db, slug)
    extension = project_service.set_project_extension_state_v1(
        db,
        auth.config,
        project,
        ext_id,
        mode=payload.mode,
        enabled=payload.enabled,
        cascade=payload.cascade,
        incoming_config=payload.config,
    )
    return {"ok": True, "extension": extension}


@router.get("/projects/{slug}/submissions")
def list_project_submissions(
    slug: str,
    auth: ApiAuth,
    db: DbSession,
    status: str | None = None,
    plugin_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    require_scope(auth, "read")
    project = _get_accessible_project(auth, db, slug)
    result = project_service.list_project_submissions_v1(
        db,
        project,
        status=status,
        plugin_id=plugin_id,
        limit=limit,
        offset=offset,
    )
    return {"ok": True, "slug": project.slug, **result}


@router.post("/projects/{slug}/submissions/{sub_id}/status")
def update_project_submission_status(
    slug: str,
    sub_id: int,
    payload: SubmissionStatusPayload,
    auth: ApiAuth,
    db: DbSession,
) -> dict[str, Any]:
    require_scope(auth, "submissions:write")
    project = _get_accessible_project(auth, db, slug)
    result = project_service.update_submission_status_v1(
        db,
        project,
        sub_id,
        action=payload.action,
        status=payload.status,
    )
    return {"ok": True, **result}


@router.get("/tokens")
def list_api_tokens(auth: ApiAuth, db: DbSession) -> dict[str, Any]:
    _require_global_admin(auth)
    return {
        "ok": True,
        "tokens": tokens.list_tokens(db),
        "valid_scopes": list(tokens.VALID_SCOPES),
    }


@router.post("/tokens", status_code=status.HTTP_201_CREATED)
def create_api_token(
    payload: TokenCreatePayload,
    auth: ApiAuth,
    db: DbSession,
) -> dict[str, Any]:
    _require_global_admin(auth)
    try:
        meta, plaintext = tokens.create_token(
            db,
            name=payload.name,
            scopes=payload.scopes,
            allowed_slugs=payload.allowed_slugs,
            expires_at=payload.expires_at,
        )
    except tokens.TokenError as exc:
        raise ServiceError(
            str(exc),
            422,
            code="invalid_token",
            hint="请检查令牌名称、scopes、allowed_slugs 与 expires_at 格式",
        ) from exc
    return {"ok": True, "token": meta, "plaintext": plaintext}


@router.delete("/tokens/{token_id}")
def delete_api_token(token_id: int, auth: ApiAuth, db: DbSession) -> dict[str, Any]:
    _require_global_admin(auth)
    revoked = tokens.revoke_token(db, token_id)
    if not revoked:
        raise ServiceError(
            "令牌不存在",
            404,
            code="token_not_found",
            hint="请检查令牌 ID 是否正确",
        )
    return {"ok": True, "revoked": True, "id": token_id}
