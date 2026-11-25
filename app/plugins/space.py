import json
import re
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app import store
from app.auth import read_session
from app.extensions.registry import build_render_bundle, normalize_extensions
from app.models import Project
from app.surface import Capability, StaticSurface, SurfaceItem, project_meta
from app.templating import placeholder_hue, templates

VALID_FONTS = {"sans", "serif", "mono"}
VALID_RADII = {"0px", "6px", "10px", "14px", "20px", "24px"}
SPACE_CAPABILITIES: frozenset[Capability] = frozenset({"has_children", "has_items", "supports_layout"})


def default_space_content() -> dict[str, Any]:
    return {
        "accent": "",
        "font_family": "",
        "radius_card": "",
    }


def validate_space_content(
    raw: str | dict,
    *,
    strict: bool = False,
    project_slug: str | None = None,
    config: Any = None,
) -> dict[str, Any]:
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

    extensions = normalize_extensions(
        parsed.get("extensions"),
        strict=strict,
        project_slug=project_slug,
        capabilities=SPACE_CAPABILITIES,
        config=config,
    )
    if extensions:
        content["extensions"] = extensions

    return content


class SpaceApp:
    type: str = "space"
    label: str = "空间"
    icon: str = "layers"
    leaf: bool = False
    content_editable: bool = False
    admin_template: str | None = None
    capabilities: frozenset[Capability] = SPACE_CAPABILITIES

    def default_content(self) -> dict[str, Any]:
        return default_space_content()

    def validate_content(
        self,
        raw: str,
        project_slug: str | None = None,
        config: Any = None,
    ) -> dict[str, Any]:
        return validate_space_content(raw, strict=False, project_slug=project_slug, config=config)

    def route(self, request: Request, project: Project, path: str, db: Session):
        return None

    def surface(self, request: Request, project: Project, db: Session, *, sub: str = "") -> StaticSurface:
        config = request.app.state.config
        content = validate_space_content(project.content, project_slug=project.slug, config=config)
        children = store.visible_projects(db, project.id)
        items = tuple(
            SurfaceItem(
                key=child.slug,
                title=child.title,
                url=f"/projects/{child.slug}/",
                summary=child.description,
                cover=child.cover,
                kind=child.type,
            )
            for child in children
        )
        visitor = {
            "title": project.title,
            "description": project.description,
            "children": [child.title for child in children],
        }
        tokens = {
            name: content[key]
            for name, key in (
                ("--accent", "accent"),
                ("--font-family", "font_family"),
                ("--radius-card", "radius_card"),
            )
            if content[key]
        }
        return StaticSurface(
            meta=project_meta(db, project),
            capabilities=self.capabilities,
            contexts={"visitor": visitor, "ai": visitor, "admin": {**visitor, "theme": content}},
            item_list=items,
            token_map=tokens,
        )

    def render(self, request: Request, project: Project, db: Session) -> HTMLResponse:
        config = request.app.state.config
        session = read_session(config, request)
        is_admin = bool(session and session.get("admin") is True)
        content = validate_space_content(project.content, project_slug=project.slug, config=config)
        ext = build_render_bundle(
            "space",
            project,
            content,
            capabilities=self.capabilities,
            config=config,
            is_admin=is_admin,
            db=db,
        )
        return templates.TemplateResponse(
            request,
            "space.html",
            {
                "site_title": config.site_title,
                "project": project,
                "theme": content,
                "ext": ext,
                "projects": store.visible_projects(db, project.id),
                "hue": placeholder_hue,
                "is_admin": is_admin,
            },
        )
