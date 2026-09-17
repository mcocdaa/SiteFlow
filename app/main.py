from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from app import store
from app.config import Config
from app.routes import router

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(config: Config | None = None) -> FastAPI:
    app = FastAPI(title="SiteFlow", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.config = config or Config.load()
    store.init(app.state.config)
    app.include_router(router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if request.url.path.startswith("/projects/"):
            response.headers.setdefault(
                "Content-Security-Policy",
                "sandbox allow-scripts allow-forms allow-modals allow-popups allow-downloads",
            )
        if request.url.path.startswith("/admin") or request.url.path.startswith("/api/admin"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    return app


app = create_app()
