from fastapi import Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app import store
from app.auth import read_session
from app.models import Project
from app.templating import placeholder_hue, templates


class SpaceApp:
    type: str = "space"
    label: str = "空间"
    icon: str = "layers"
    leaf: bool = False
    content_editable: bool = False
    admin_template: str | None = None

    def default_content(self) -> dict:
        return {}

    def validate_content(self, raw: str) -> dict:
        return {}

    def route(self, request: Request, project: Project, path: str, db: Session):
        return None

    def render(self, request: Request, project: Project, db: Session) -> HTMLResponse:
        config = request.app.state.config
        session = read_session(config, request)
        return templates.TemplateResponse(
            request,
            "space.html",
            {
                "site_title": config.site_title,
                "project": project,
                "projects": store.visible_projects(db, project.id),
                "hue": placeholder_hue,
                "is_admin": bool(session and session.get("admin") is True),
            },
        )
