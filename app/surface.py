from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from fastapi import Request
from sqlalchemy.orm import Session

from app.models import Project

Audience = Literal["visitor", "plugin", "ai", "admin"]
SlotName = Literal["header", "aside", "overlay", "footer", "title_deco", "icons"]
Capability = Literal[
    "has_content",
    "has_children",
    "has_items",
    "has_posts",
    "accepts_visitor_input",
    "is_personal_profile",
    "supports_layout",
]
AUDIENCES: tuple[Audience, ...] = ("visitor", "plugin", "ai", "admin")
CAPABILITIES: frozenset[str] = frozenset(Capability.__args__)  # type: ignore[attr-defined]


@dataclass(frozen=True)
class SurfaceMeta:
    type: str
    slug: str
    title: str
    description: str
    url: str
    parent_chain: tuple[str, ...] = ()


@dataclass(frozen=True)
class SurfaceItem:
    key: str
    title: str
    url: str
    summary: str = ""
    cover: str = ""
    kind: str = ""
    tags: tuple[str, ...] = ()
    date: str = ""


class PageSurface(Protocol):
    @property
    def meta(self) -> SurfaceMeta: ...

    @property
    def capabilities(self) -> frozenset[Capability]: ...

    def context(self, audience: Audience) -> Mapping[str, Any]: ...

    def items(self, audience: Audience) -> Sequence[SurfaceItem]: ...

    def tokens(self) -> Mapping[str, str]: ...


class SurfaceProvider(Protocol):
    def surface(self, request: Request, project: Project, db: Session, *, sub: str = "") -> PageSurface: ...


@dataclass(frozen=True)
class StaticSurface:
    meta: SurfaceMeta
    capabilities: frozenset[Capability]
    contexts: Mapping[str, Mapping[str, Any]]
    item_list: tuple[SurfaceItem, ...] = ()
    token_map: Mapping[str, str] = field(default_factory=dict)
    audience_items: Mapping[str, tuple[SurfaceItem, ...]] = field(default_factory=dict)

    def context(self, audience: Audience) -> Mapping[str, Any]:
        if audience in self.contexts:
            return self.contexts[audience]
        if audience == "plugin" and "ai" in self.contexts:
            return self.contexts["ai"]
        if audience == "ai" and "plugin" in self.contexts:
            return self.contexts["plugin"]
        return self.contexts.get("visitor", {})

    def items(self, audience: Audience) -> Sequence[SurfaceItem]:
        if audience in self.audience_items:
            return self.audience_items[audience]
        if audience == "plugin" and "ai" in self.audience_items:
            return self.audience_items["ai"]
        if audience == "ai" and "plugin" in self.audience_items:
            return self.audience_items["plugin"]
        if "visitor" in self.audience_items:
            return self.audience_items["visitor"]
        return self.item_list

    def tokens(self) -> Mapping[str, str]:
        return self.token_map


def parent_chain(db: Session, project: Project) -> tuple[str, ...]:
    chain: list[str] = []
    current = project.parent_id
    while current is not None and len(chain) < 3:
        parent = db.get(Project, current)
        if parent is None:
            break
        chain.insert(0, parent.slug)
        current = parent.parent_id
    return tuple(chain)


def project_meta(
    db: Session, project: Project, *, title: str = "", description: str = "", url: str = ""
) -> SurfaceMeta:
    return SurfaceMeta(
        type=project.type,
        slug=project.slug,
        title=title or project.title,
        description=description or project.description,
        url=url or f"/projects/{project.slug}/",
        parent_chain=parent_chain(db, project),
    )
