from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app import store
from app.auth import check_csrf, require_admin, require_same_origin, verify_api_token
from app.config import Config


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


def admin_api(request: Request) -> Config:
    config = get_config(request)
    if verify_api_token(request, config):
        return config
    require_admin(request, config)
    if request.method not in ("GET", "HEAD", "OPTIONS") or request.headers.get("origin"):
        require_same_origin(request)
    elif request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "跨站请求被拒绝")
    submitted = request.headers.get("x-csrf-token") or ""
    if not check_csrf(request, submitted):
        raise HTTPException(403, "CSRF 校验失败")
    return config


AdminConfig = Annotated[Config, Depends(admin_api)]
