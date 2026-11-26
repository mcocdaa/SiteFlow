import hmac
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app import store
from app.auth import check_csrf, extract_api_token, read_session, require_same_origin
from app.config import Config
from app.models import Project
from app.tokens import VALID_SCOPES, AuthPrincipal, verify_db_token


class ServiceError(Exception):
    def __init__(
        self,
        message: str,
        status_code: int = 400,
        code: str = "bad_request",
        hint: str = "",
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.hint = hint


@dataclass(frozen=True)
class ApiContext:
    config: Config
    principal: AuthPrincipal


def get_config(request: Request) -> Config:
    return request.app.state.config


def db_session(request: Request) -> Iterator[Session]:
    session = store.init(get_config(request))()
    try:
        yield session
    finally:
        session.close()


DbSession = Annotated[Session, Depends(db_session)]


def api_error(message: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse({"ok": False, "error": message}, status_code=status_code)


def authenticate_api(request: Request, db: DbSession) -> ApiContext:
    config = get_config(request)
    raw_token = extract_api_token(request)
    if raw_token is not None:
        if (
            config.api_token
            and raw_token
            and hmac.compare_digest(raw_token.encode(), config.api_token.encode())
        ):
            return ApiContext(
                config=config,
                principal=AuthPrincipal(
                    kind="env_token",
                    is_admin=True,
                    scopes=frozenset(VALID_SCOPES),
                    allowed_slugs=None,
                ),
            )
        principal = verify_db_token(db, raw_token)
        if principal is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "无效的 API Token")
        return ApiContext(config=config, principal=principal)

    data = read_session(config, request)
    if data is None or data.get("admin") is not True:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "需要登录")
    request.scope["siteflow_csrf"] = data.get("csrf")
    if request.method not in ("GET", "HEAD", "OPTIONS") or request.headers.get("origin"):
        require_same_origin(request)
    elif request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "跨站请求被拒绝")
    submitted = request.headers.get("x-csrf-token") or ""
    if not check_csrf(request, submitted):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF 校验失败")
    return ApiContext(
        config=config,
        principal=AuthPrincipal(
            kind="session",
            is_admin=True,
            scopes=frozenset(VALID_SCOPES),
            allowed_slugs=None,
        ),
    )


ApiAuth = Annotated[ApiContext, Depends(authenticate_api)]


def admin_api(request: Request, db: DbSession) -> Config:
    ctx = authenticate_api(request, db)
    if not ctx.principal.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "当前 API 令牌无权访问管理接口")
    return ctx.config


AdminConfig = Annotated[Config, Depends(admin_api)]


def require_scope(ctx: ApiContext, scope: str) -> None:
    if not ctx.principal.has_scope(scope):
        raise ServiceError(
            f"当前令牌缺少所需权限：{scope}",
            403,
            code="forbidden_scope",
            hint=f"请使用具备 {scope} 或 admin 权限的令牌",
        )


def require_project_access(ctx: ApiContext, db: Session, project: Project) -> None:
    if ctx.principal.allowed_slugs is None:
        return
    slugs = [project.slug, *(ancestor.slug for ancestor in store.ancestors(db, project))]
    if not ctx.principal.can_access_slugs(slugs):
        raise ServiceError(
            "当前 API 令牌无权访问该项目",
            403,
            code="forbidden_project",
            hint="请在令牌允许的项目作用域内操作",
        )
