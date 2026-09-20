import re
import secrets
import shutil
from pathlib import Path

from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Config
from app.models import Base, Project

_engine: Engine | None = None
_factory: sessionmaker[Session] | None = None
_current: Config | None = None


def _migrate(engine: Engine) -> None:
    with engine.connect() as conn:
        columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(projects)")}
        if "parent_id" not in columns:
            conn.exec_driver_sql(
                "ALTER TABLE projects ADD COLUMN parent_id INTEGER REFERENCES projects(id) ON DELETE CASCADE"
            )
        if "content" not in columns:
            conn.exec_driver_sql("ALTER TABLE projects ADD COLUMN content TEXT NOT NULL DEFAULT '{}'")
        if "password_hash" not in columns:
            conn.exec_driver_sql("ALTER TABLE projects ADD COLUMN password_hash TEXT DEFAULT NULL")
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_projects_parent_id ON projects (parent_id)")

        conn.exec_driver_sql("""
            CREATE TABLE IF NOT EXISTS daily_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                project_id INTEGER,
                pv INTEGER NOT NULL DEFAULT 0,
                uv INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.exec_driver_sql("""
            CREATE UNIQUE INDEX IF NOT EXISTS ux_daily_stats_date_project
            ON daily_stats (date, COALESCE(project_id, -1))
        """)
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_daily_stats_date ON daily_stats (date)")
        conn.commit()


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
        _migrate(_engine)
        _factory = sessionmaker(bind=_engine)
        _current = config
    return _factory


def session() -> Session:
    assert _factory is not None
    return _factory()


def _scope(stmt, parent_id: int | None):
    return stmt.where(Project.parent_id.is_(None)) if parent_id is None else stmt.where(Project.parent_id == parent_id)


def visible_projects(db: Session, parent_id: int | None = None) -> list[Project]:
    stmt = _scope(select(Project).where(Project.visible.is_(True)), parent_id).order_by(
        Project.pinned.desc(), Project.sort_order.asc(), Project.created_at.desc()
    )
    return list(db.execute(stmt).scalars())


def all_projects(db: Session, parent_id: int | None = None) -> list[Project]:
    stmt = _scope(select(Project), parent_id).order_by(
        Project.pinned.desc(), Project.sort_order.asc(), Project.created_at.desc()
    )
    return list(db.execute(stmt).scalars())


def by_slug(db: Session, slug: str) -> Project | None:
    return db.execute(select(Project).where(Project.slug == slug)).scalar_one_or_none()


def by_id(db: Session, project_id: int) -> Project | None:
    return db.execute(select(Project).where(Project.id == project_id)).scalar_one_or_none()


def ancestors(db: Session, project: Project) -> list[Project]:
    chain: list[Project] = []
    current = by_id(db, project.parent_id) if project.parent_id else None
    while current is not None:
        chain.append(current)
        current = by_id(db, current.parent_id) if current.parent_id else None
    return chain


def descendants(db: Session, project: Project) -> list[Project]:
    found: list[Project] = []
    pending = [project.id]
    while pending:
        parent = pending.pop()
        rows = list(db.execute(select(Project).where(Project.parent_id == parent)).scalars())
        found.extend(rows)
        pending.extend(row.id for row in rows)
    return found


def depth(db: Session, project: Project) -> int:
    return len(ancestors(db, project)) + 1


def is_visible(db: Session, project: Project) -> bool:
    return bool(project.visible) and all(ancestor.visible for ancestor in ancestors(db, project))


def unique_slug(db: Session, title: str) -> str:
    base = re.sub(r"[^a-z0-9-]", "", title.lower().replace(" ", "-"))
    base = re.sub(r"-+", "-", base).strip("-")[:60] or f"work-{secrets.token_hex(3)}"
    slug = base
    suffix = 2
    while by_slug(db, slug) is not None:
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


def next_sort_order(db: Session, parent_id: int | None = None) -> int:
    stmt = _scope(select(Project.sort_order), parent_id)
    rows = db.execute(stmt).scalars().all()
    return (min(rows) - 1) if rows else 0


def move(db: Session, project: Project, direction: str) -> bool:
    ordered = [row for row in all_projects(db, project.parent_id) if row.pinned == project.pinned]
    index = ordered.index(project)
    target = index - 1 if direction == "up" else index + 1
    if not 0 <= target < len(ordered):
        return False
    ordered[index], ordered[target] = ordered[target], ordered[index]
    for position, row in enumerate(ordered):
        row.sort_order = position
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
