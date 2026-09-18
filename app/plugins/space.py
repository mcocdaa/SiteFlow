from fastapi import Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app import store
from app.auth import read_session
from app.models import Project
from app.templating import placeholder_hue, templates


class SpaceApp:
    type = "space"
    label = "空间"
    icon = "layers"
    leaf = False
    content_editable = False

    def default_content(self) -> dict:
        return {}

    def validate_content(self, raw: str) -> dict:
        return {}

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
