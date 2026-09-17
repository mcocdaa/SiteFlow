from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app import store
from app.auth import check_csrf, require_admin, require_same_origin
from app.config import Config


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
    require_admin(request, config)
    require_same_origin(request)
    submitted = request.headers.get("x-csrf-token") or ""
    if not check_csrf(request, submitted):
        raise HTTPException(403, "CSRF 校验失败")
    return config


AdminConfig = Annotated[Config, Depends(admin_api)]
