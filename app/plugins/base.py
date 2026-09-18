from typing import Protocol

from fastapi import Request, Response
from sqlalchemy.orm import Session

from app.models import Project


class InvalidContent(ValueError):
    pass


class AppPlugin(Protocol):
    type: str
    label: str
    icon: str
    leaf: bool
    content_editable: bool
    admin_template: str | None

    def default_content(self) -> dict: ...

    def validate_content(self, raw: str) -> dict: ...

    def render(self, request: Request, project: Project, db: Session) -> Response: ...

    def route(self, request: Request, project: Project, path: str, db: Session) -> Response | None: ...
