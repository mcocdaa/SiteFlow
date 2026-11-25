from typing import Any

from sqlalchemy.orm import Session

from app.config import Config
from app.extensions import registry as _registry
from app.extensions.base import Extension, PageKind, TargetType
from app.models import Project

register = _registry.register
get = _registry.get
normalize_post_meta = _registry.normalize_post_meta
extension_catalog_item = _registry.extension_catalog_item
build_editor_bundle = _registry.build_editor_bundle


def all_extensions(
    *,
    target: TargetType | None = "blog",
    config: Config | None = None,
) -> list[Extension]:
    return _registry.all_extensions(target=target, config=config)


def normalize_extensions(
    raw: object,
    *,
    strict: bool = False,
    project_slug: str | None = None,
    target: TargetType | None = "blog",
    config: Config | None = None,
) -> dict[str, dict[str, Any]]:
    return _registry.normalize_extensions(
        raw,
        strict=strict,
        project_slug=project_slug,
        target=target,
        config=config,
    )


def active_extensions(
    content: dict[str, Any],
    *,
    target: TargetType | None = "blog",
    config: Config | None = None,
) -> list[tuple[Extension, dict[str, Any]]]:
    return _registry.active_extensions(content, target=target, config=config)


def build_admin_catalog(
    content: dict[str, Any],
    *,
    target: TargetType | None = "blog",
    config: Config | None = None,
) -> list[dict[str, Any]]:
    return _registry.build_admin_catalog(content, target=target, config=config)


def build_render_bundle(
    page: PageKind,
    project: Project,
    blog: dict[str, Any],
    posts: list[dict[str, Any]] | None = None,
    post: dict[str, Any] | None = None,
    *,
    target: TargetType | None = "blog",
    config: Config | None = None,
    is_admin: bool = False,
    db: Session | None = None,
) -> dict[str, Any]:
    return _registry.build_render_bundle(
        page,
        project,
        blog,
        posts=posts,
        post=post,
        target=target,
        config=config,
        is_admin=is_admin,
        db=db,
    )


def referenced_blog_media_urls(
    content: dict[str, Any],
    *,
    target: TargetType | None = "blog",
    config: Config | None = None,
) -> set[str]:
    return _registry.referenced_media_urls(content, target=target, config=config)
