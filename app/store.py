import re
import secrets
import shutil
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Config
from app.models import Base, Project

_engine: object = None
_factory: sessionmaker[Session] | None = None
_current: Config | None = None


def init(config: Config) -> sessionmaker[Session]:
    global _engine, _factory, _current
    if _factory is None or _current is None or _current.data != config.data:
        _engine = create_engine(
            f"sqlite:///{config.data / 'siteflow.db'}",
            connect_args={"check_same_thread": False},
        )
        with _engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA journal_mode=WAL")
            conn.exec_driver_sql("PRAGMA foreign_keys=ON")
            conn.exec_driver_sql("PRAGMA busy_timeout=5000")
        Base.metadata.create_all(_engine)
        _factory = sessionmaker(bind=_engine)
        _current = config
    return _factory


def session() -> Session:
    assert _factory is not None
    return _factory()


def visible_projects(db: Session) -> list[Project]:
    return list(
        db.execute(
            select(Project)
            .where(Project.visible.is_(True))
            .order_by(Project.pinned.desc(), Project.sort_order.asc(), Project.created_at.desc())
        ).scalars()
    )


def all_projects(db: Session) -> list[Project]:
    return list(
        db.execute(
            select(Project).order_by(Project.pinned.desc(), Project.sort_order.asc(), Project.created_at.desc())
        ).scalars()
    )


def by_slug(db: Session, slug: str) -> Project | None:
    return db.execute(select(Project).where(Project.slug == slug)).scalar_one_or_none()


def by_id(db: Session, project_id: int) -> Project | None:
    return db.execute(select(Project).where(Project.id == project_id)).scalar_one_or_none()


def unique_slug(db: Session, title: str) -> str:
    base = re.sub(r"[^a-z0-9-]", "", title.lower().replace(" ", "-"))
    base = re.sub(r"-+", "-", base).strip("-")[:60] or f"work-{secrets.token_hex(3)}"
    slug = base
    suffix = 2
    while by_slug(db, slug) is not None:
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


def next_sort_order(db: Session) -> int:
    rows = db.execute(select(Project.sort_order)).scalars().all()
    return (min(rows) - 1) if rows else 0


def move(db: Session, project: Project, direction: str) -> bool:
    siblings = [
        row
        for row in all_projects(db)
        if row.pinned == project.pinned and row.id != project.id
    ]
    siblings.sort(key=lambda row: (row.sort_order, row.created_at))
    ordered = [project] + siblings
    ordered.sort(key=lambda row: (row.sort_order, row.created_at, row.id))
    index = ordered.index(project)
    target = index - 1 if direction == "up" else index + 1
    if not 0 <= target < len(ordered):
        return False
    project.sort_order, ordered[target].sort_order = ordered[target].sort_order, project.sort_order
    if project.sort_order == ordered[target].sort_order:
        project.sort_order += 1 if direction == "down" else -1
    return True


def delete_files(config: Config, project: Project) -> None:
    folder = Path(config.data) / "projects" / project.slug
    if folder.exists():
        shutil.rmtree(folder)
    cover = Path(config.data) / "media" / "covers" / project.cover
    if project.cover and cover.exists():
        cover.unlink()


def unique_slug_name() -> str:
    return secrets.token_hex(8)
