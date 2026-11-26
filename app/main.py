import mimetypes
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import store
from app.config import Config
from app.deps import ServiceError
from app.routes import router

mimetypes.add_type("font/woff2", ".woff2")

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(config: Config | None = None) -> FastAPI:
    app = FastAPI(title="SiteFlow", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.config = config or Config.load()
    store.init(app.state.config)
    app.include_router(router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.exception_handler(ServiceError)
    async def service_error_handler(request: Request, exc: ServiceError) -> JSONResponse:
        if request.url.path.startswith("/api/v1"):
            return JSONResponse(
                {
                    "ok": False,
                    "code": exc.code,
                    "error": exc.message,
                    "hint": exc.hint,
                },
                status_code=exc.status_code,
            )
        return JSONResponse({"ok": False, "error": exc.message}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        if request.url.path.startswith("/api/v1"):
            return JSONResponse(
                {
                    "ok": False,
                    "code": "validation_error",
                    "error": "请求参数校验失败",
                    "details": jsonable_encoder(exc.errors()),
                    "hint": "请检查字段名与类型，或查看 GET /api/v1/openapi.json",
                },
                status_code=422,
            )
        return await request_validation_exception_handler(request, exc)

    @app.middleware("http")
    async def subdomain_routing(request: Request, call_next):
        cfg: Config = app.state.config
        if cfg.base_domain:
            host = request.headers.get("host", "").split(":")[0].lower()
            expected_suffix = f".{cfg.base_domain}"
            if host.endswith(expected_suffix) and len(host) > len(expected_suffix):
                subdomain = host[: -len(expected_suffix)].strip(".")
                if subdomain and subdomain not in ("www", "api", "admin"):
                    path = request.scope.get("path", "/")
                    if not path.startswith(
                        ("/static/", "/api/", "/healthz", "/media/", "/projects/", "/p/", "/admin", "/login")
                    ):
                        subpath = path.lstrip("/")
                        new_path = (
                            f"/projects/{subdomain}/{subpath}" if subpath else f"/projects/{subdomain}/"
                        )
                        request.scope["path"] = new_path
        return await call_next(request)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith(("/projects/", "/p/")):
            response.headers["X-Frame-Options"] = "SAMEORIGIN"
        else:
            response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if request.url.path.startswith(("/admin", "/api/admin", "/api/deploy", "/api/v1")):
            response.headers.setdefault("Cache-Control", "no-store")
        elif request.url.path.startswith("/static/"):
            if request.query_params.get("v") and response.status_code < 400:
                response.headers.setdefault("Cache-Control", "public, max-age=31536000, immutable")
            else:
                response.headers.setdefault("Cache-Control", "no-cache")
        return response

    return app


app = create_app()
