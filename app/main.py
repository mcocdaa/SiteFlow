from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from app import store
from app.config import Config
from app.routes import router
from app.views import SANDBOX_CSP

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(config: Config | None = None) -> FastAPI:
    app = FastAPI(title="SiteFlow", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.config = config or Config.load()
    store.init(app.state.config)
    app.include_router(router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.middleware("http")
    async def subdomain_routing(request: Request, call_next):
        cfg: Config = app.state.config
        if cfg.base_domain:
            host = request.headers.get("host", "").split(":")[0].lower()
            expected_suffix = f".{cfg.base_domain}"
            if host.endswith(expected_suffix) and len(host) > len(expected_suffix):
                subdomain = host[:-len(expected_suffix)].strip(".")
                if subdomain and subdomain not in ("www", "api", "admin"):
                    path = request.scope.get("path", "/")
                    if not path.startswith(("/static/", "/api/", "/healthz", "/media/", "/projects/", "/admin", "/login")):
                        subpath = path.lstrip("/")
                        new_path = f"/projects/{subdomain}/{subpath}" if subpath else f"/projects/{subdomain}/"
                        request.scope["path"] = new_path
        return await call_next(request)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/projects/"):
            response.headers["X-Frame-Options"] = "SAMEORIGIN"
            response.headers.setdefault("Content-Security-Policy", SANDBOX_CSP)
        else:
            response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if request.url.path.startswith("/admin") or request.url.path.startswith("/api/admin"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    return app


app = create_app()
