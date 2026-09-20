import json
import re

from fastapi import Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app import store
from app.auth import read_session
from app.models import Project
from app.templating import placeholder_hue, templates

VALID_FONTS = {"sans", "serif", "mono"}
VALID_RADII = {"0px", "6px", "10px", "14px", "20px", "24px"}


def default_space_content() -> dict:
    return {
        "accent": "",
        "font_family": "",
        "radius_card": "",
    }


def validate_space_content(raw: str | dict) -> dict:
    if isinstance(raw, dict):
        parsed = raw
    else:
        try:
            parsed = json.loads(raw or "{}")
        except json.JSONDecodeError:
            return default_space_content()
    if not isinstance(parsed, dict):
        return default_space_content()

    content = default_space_content()
    accent = str(parsed.get("accent", "")).strip()
    if accent and re.match(r"^#(?:[0-9a-fA-F]{3}){1,2}$", accent):
        content["accent"] = accent

    font_family = str(parsed.get("font_family", "")).strip().lower()
    if font_family in VALID_FONTS:
        content["font_family"] = font_family

    radius_card = str(parsed.get("radius_card", "")).strip().lower()
    if radius_card in VALID_RADII:
        content["radius_card"] = radius_card

    return content


class SpaceApp:
    type: str = "space"
    label: str = "空间"
    icon: str = "layers"
    leaf: bool = False
    content_editable: bool = False
    admin_template: str | None = None

    def default_content(self) -> dict:
        return default_space_content()

    def validate_content(self, raw: str) -> dict:
        return validate_space_content(raw)

    def route(self, request: Request, project: Project, path: str, db: Session):
        return None

    def render(self, request: Request, project: Project, db: Session) -> HTMLResponse:
        config = request.app.state.config
        session = read_session(config, request)
        theme = validate_space_content(project.content)
        return templates.TemplateResponse(
            request,
            "space.html",
            {
                "site_title": config.site_title,
                "project": project,
                "theme": theme,
                "projects": store.visible_projects(db, project.id),
                "hue": placeholder_hue,
                "is_admin": bool(session and session.get("admin") is True),
            },
        )
