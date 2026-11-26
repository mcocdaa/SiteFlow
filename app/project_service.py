import json
import re
import secrets
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import stats, store, submissions
from app.auth import hash_project_password
from app.config import Config
from app.deps import ServiceError
from app.extensions.base import TargetType, capabilities_for_target
from app.extensions.inheritance import (
    VALID_MODES,
    merge_layer_config,
    parse_layer_state,
    resolve_project_extension,
)
from app.extensions.registry import (
    build_project_admin_catalog,
    merge_content_extension_secrets,
    redact_content_extensions,
    referenced_media_urls,
    resolved_catalog_item,
)
from app.extensions.registry import get as get_extension
from app.models import Project
from app.og import OpenGraph, fetch_image, fetch_og
from app.plugins import registry
from app.plugins.base import InvalidContent
from app.plugins.blog.plugin import _slug as normalize_post_slug
from app.plugins.blog.plugin import validate_content as blog_content
from app.plugins.bottle.plugin import validate_content as bottle_content
from app.plugins.resume.plugin import validate_content as resume_content
from app.plugins.space import validate_space_content
from app.surface import Capability
from app.uploads import (
    InvalidUpload,
    delete_project_media_url,
    extract_site,
    make_cover,
    remove_tree,
    save_blog_media,
    save_cover,
)

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
COVER_LIMIT = 10 * 1024 * 1024
BLOG_UPLOAD_KINDS = frozenset({"image", "cover", "bg"})
CONTENT_EDITABLE_TYPES = frozenset({"blog", "resume", "bottle", "space"})


def touch(project: Project) -> None:
    project.updated_at = datetime.now(UTC).isoformat()


def hostname_of(url: str) -> str:
    return (urlparse(url).hostname or "").replace("www.", "")


def _target_of(project: Project) -> TargetType | None:
    if project.type == "blog":
        return "blog"
    if project.type == "space":
        return "space"
    if project.type == "resume":
        return "resume"
    return None


def capabilities_of(project: Project) -> frozenset[Capability] | None:
    plugin = registry.get(project.type)
    if plugin is None:
        return None
    caps = getattr(plugin, "capabilities", None)
    if isinstance(caps, frozenset):
        return caps
    target = _target_of(project)
    return capabilities_for_target(target) if target is not None else None


def cleanup_unreferenced_media(
    config: Config,
    project_slug: str,
    old_media: set[str],
    new_media: set[str],
) -> None:
    for stale_url in old_media - new_media:
        delete_project_media_url(config, project_slug, stale_url)


def validate_slug(slug: str) -> str:
    if not isinstance(slug, str) or not _SLUG_RE.match(slug):
        raise ServiceError(
            "无效的项目标识（仅支持小写字母、数字、连字符和下划线，长度 1-64）",
            400,
            code="invalid_slug",
            hint="slug 须以小写字母或数字开头，仅含小写字母、数字、连字符和下划线，长度 1-64",
        )
    return slug


def _validate_post_slug(post_slug: str, *, status_code: int = 400) -> str:
    cleaned = post_slug.strip() if isinstance(post_slug, str) else ""
    normalized = normalize_post_slug(cleaned)
    if not cleaned or not normalized or normalized != cleaned or ".." in cleaned:
        raise ServiceError(
            "文章网址标识不能为空或包含非法字符",
            status_code,
            code="invalid_post_slug",
            hint="post_slug 不能为空，且不能包含空白、斜杠、.. 或特殊 URL 字符",
        )
    return cleaned


def _require_blog(project: Project) -> None:
    if project.type != "blog":
        raise ServiceError(
            "目标项目不是博客",
            400,
            code="not_a_blog",
            hint="仅 blog 类型项目支持文章与博客媒体操作",
        )


def _validate_parent(db: Session, parent: Project) -> Project:
    plugin = registry.get(parent.type)
    if plugin is None or plugin.leaf:
        raise ServiceError(
            "只有可包含子项的应用可以嵌套",
            400,
            code="invalid_parent",
            hint="父级必须是空间（space）类型",
        )
    if store.depth(db, parent) >= 3:
        raise ServiceError(
            "已达最大嵌套深度（3 层）",
            400,
            code="max_depth_exceeded",
            hint="最多支持 3 层嵌套结构",
        )
    return parent


def _subtree_max_relative_depth(db: Session, root: Project) -> int:
    max_rel = 0
    queue: list[tuple[int, int]] = [(root.id, 0)]
    seen: set[int] = {root.id}
    while queue:
        curr_id, rel = queue.pop(0)
        children = list(db.execute(select(Project).where(Project.parent_id == curr_id)).scalars())
        for child in children:
            if child.id in seen:
                continue
            seen.add(child.id)
            next_rel = rel + 1
            max_rel = max(max_rel, next_rel)
            queue.append((child.id, next_rel))
    return max_rel


def get_project_by_slug(db: Session, slug: str) -> Project:
    project = store.by_slug(db, slug)
    if project is None:
        raise ServiceError(
            "作品不存在",
            404,
            code="not_found",
            hint="请检查项目 slug 是否正确",
        )
    return project


def get_project_by_id(db: Session, project_id: int) -> Project:
    project = store.by_id(db, project_id)
    if project is None:
        raise ServiceError(
            "作品不存在",
            404,
            code="not_found",
            hint="请检查项目 ID 是否正确",
        )
    return project


def resolve_parent_by_id(db: Session, parent_id: int | None) -> Project | None:
    if parent_id is None:
        return None
    parent = store.by_id(db, parent_id)
    if parent is None:
        raise ServiceError(
            "父级不存在",
            404,
            code="parent_not_found",
            hint="请检查父级 ID 是否正确",
        )
    return _validate_parent(db, parent)


def resolve_parent_by_slug(db: Session, parent_slug: str | None) -> Project | None:
    if parent_slug is None or parent_slug == "":
        return None
    parent = store.by_slug(db, parent_slug)
    if parent is None:
        raise ServiceError(
            "父级不存在",
            404,
            code="parent_not_found",
            hint="请检查父级空间 slug 是否正确",
        )
    return _validate_parent(db, parent)


def _parse_raw_content(project: Project, config: Config, *, strict: bool = False) -> dict[str, Any]:
    if project.type == "blog":
        return blog_content(project.content, strict=strict, project_slug=project.slug, config=config)
    if project.type == "space":
        return validate_space_content(
            project.content,
            strict=strict,
            project_slug=project.slug,
            config=config,
        )
    if project.type == "resume":
        return resume_content(project.content, strict=strict, project_slug=project.slug, config=config)
    if project.type == "bottle":
        return bottle_content(project.content, strict=strict, project_slug=project.slug, config=config)
    return {}


def parsed_project_content(
    project: Project,
    config: Config,
    *,
    redact: bool = True,
) -> dict[str, Any]:
    parsed = _parse_raw_content(project, config, strict=False)
    if not redact:
        return parsed
    caps = capabilities_of(project)
    if caps is None:
        return parsed
    return redact_content_extensions(parsed, capabilities=caps, config=config)


def project_dict_redacted(project: Project, config: Config) -> dict[str, Any]:
    data = project.as_dict()
    caps = capabilities_of(project)
    if caps is None or not project.content:
        return data
    try:
        parsed = json.loads(project.content)
    except (TypeError, ValueError):
        return data
    if not isinstance(parsed, dict) or "extensions" not in parsed:
        return data
    redacted = redact_content_extensions(parsed, capabilities=caps, config=config)
    data["content"] = json.dumps(redacted, ensure_ascii=False)
    return data


def project_summary(project: Project, *, parent_slug: str | None = None) -> dict[str, Any]:
    return {
        "id": project.id,
        "slug": project.slug,
        "type": project.type,
        "parent_id": project.parent_id,
        "parent_slug": parent_slug,
        "title": project.title,
        "description": project.description,
        "url": project.url,
        "entry": project.entry,
        "cover": project.cover,
        "pinned": bool(project.pinned),
        "visible": bool(project.visible),
        "has_password": bool(project.password_hash),
        "sort_order": project.sort_order,
        "public_url": f"/projects/{project.slug}/",
        "created_at": project.created_at,
        "updated_at": project.updated_at,
    }


def project_detail(db: Session, config: Config, project: Project) -> dict[str, Any]:
    parent = store.by_id(db, project.parent_id) if project.parent_id else None
    parent_slug = parent.slug if parent is not None else None
    children = store.all_projects(db, project.id)
    return {
        "project": project_summary(project, parent_slug=parent_slug),
        "content": parsed_project_content(project, config, redact=True),
        "children": [project_summary(child, parent_slug=project.slug) for child in children],
        "stats": stats.get_7day_stats(db, project_id=project.id),
    }


def list_projects_view(
    db: Session,
    *,
    view: str = "flat",
    project_type: str | None = None,
    parent_slug: str | None = None,
    allowed_slugs: frozenset[str] | None = None,
) -> list[dict[str, Any]]:
    if view not in ("flat", "tree"):
        raise ServiceError(
            "不支持的列表视图模式，仅支持 flat 或 tree",
            400,
            code="invalid_view",
            hint="请将 view 设置为 flat 或 tree",
        )
    rows = list(
        db.execute(
            select(Project).order_by(
                Project.pinned.desc(),
                Project.sort_order.asc(),
                Project.created_at.desc(),
            )
        ).scalars()
    )
    by_id_map = {row.id: row for row in rows}
    by_slug_map = {row.slug: row for row in rows}

    parent_row: Project | None = None
    if parent_slug is not None and parent_slug != "":
        parent_row = by_slug_map.get(parent_slug)
        if parent_row is None:
            raise ServiceError(
                "父级不存在",
                404,
                code="parent_not_found",
                hint="请检查 parent_slug 是否正确",
            )

    def _is_allowed(row: Project) -> bool:
        if allowed_slugs is None:
            return True
        curr: Project | None = row
        seen_ids: set[int] = set()
        while curr is not None and curr.id not in seen_ids:
            if curr.slug in allowed_slugs:
                return True
            seen_ids.add(curr.id)
            curr = by_id_map.get(curr.parent_id) if curr.parent_id is not None else None
        return False

    allowed_rows = [row for row in rows if _is_allowed(row)]

    def _parent_slug_of(row: Project) -> str | None:
        if row.parent_id is None:
            return None
        parent = by_id_map.get(row.parent_id)
        return parent.slug if parent is not None else None

    if view == "flat":
        filtered = allowed_rows
        if parent_row is not None:
            filtered = [row for row in filtered if row.parent_id == parent_row.id]
        if project_type:
            filtered = [row for row in filtered if row.type == project_type]
        return [project_summary(row, parent_slug=_parent_slug_of(row)) for row in filtered]

    allowed_ids = {row.id for row in allowed_rows}
    children_by_parent: dict[int | None, list[Project]] = {}
    for row in allowed_rows:
        children_by_parent.setdefault(row.parent_id, []).append(row)

    def _build_node(row: Project) -> dict[str, Any] | None:
        child_nodes: list[dict[str, Any]] = []
        for child in children_by_parent.get(row.id, []):
            built = _build_node(child)
            if built is not None:
                child_nodes.append(built)
        if project_type and row.type != project_type and not child_nodes:
            return None
        node = project_summary(row, parent_slug=_parent_slug_of(row))
        node["children"] = child_nodes
        return node

    if parent_row is not None:
        roots = children_by_parent.get(parent_row.id, [])
    else:
        roots = [row for row in allowed_rows if row.parent_id is None or row.parent_id not in allowed_ids]

    tree: list[dict[str, Any]] = []
    for root in roots:
        built_root = _build_node(root)
        if built_root is not None:
            tree.append(built_root)
    return tree


def create_app_project(
    db: Session,
    *,
    app_type: str,
    title: str = "",
    description: str = "",
    parent_id: int | None = None,
    slug: str | None = None,
) -> Project:
    plugin = registry.get(app_type)
    if plugin is None:
        raise ServiceError(
            "不支持的应用类型",
            400,
            code="unsupported_app_type",
            hint="支持的应用类型：space、resume、blog、bottle",
        )
    parent = resolve_parent_by_id(db, parent_id)
    clean_title = (title.strip() or plugin.label)[:200]
    clean_desc = description.strip()[:500]
    if slug is not None and slug != "":
        resolved_slug = validate_slug(slug)
        if store.by_slug(db, resolved_slug) is not None:
            raise ServiceError(
                "项目标识已存在",
                409,
                code="slug_exists",
                hint="请更换 slug 或更新现有项目",
            )
    else:
        resolved_slug = store.unique_slug(db, clean_title)
    content = json.dumps(plugin.default_content(), ensure_ascii=False)
    project = Project(
        slug=resolved_slug,
        type=app_type,
        parent_id=parent.id if parent else None,
        title=clean_title,
        description=clean_desc,
        content=content,
        sort_order=store.next_sort_order(db, parent.id if parent else None),
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def create_link_project(
    db: Session,
    config: Config,
    *,
    url: str,
    title: str = "",
    description: str = "",
    parent_id: int | None = None,
    slug: str | None = None,
    fetch_og_fn: Callable[[str], OpenGraph | None] = fetch_og,
    fetch_image_fn: Callable[[str], bytes | None] = fetch_image,
) -> Project:
    clean_url = url.strip()
    if not clean_url.lower().startswith(("http://", "https://")):
        raise ServiceError(
            "链接必须以 http:// 或 https:// 开头",
            400,
            code="invalid_url",
            hint="请提供以 http:// 或 https:// 开头的有效外链地址",
        )
    parent = resolve_parent_by_id(db, parent_id)
    resolved_slug: str | None = None
    if slug is not None and slug != "":
        resolved_slug = validate_slug(slug)
        if store.by_slug(db, resolved_slug) is not None:
            raise ServiceError(
                "项目标识已存在",
                409,
                code="slug_exists",
                hint="请更换 slug 或更新现有项目",
            )
    og = fetch_og_fn(clean_url)
    clean_title = title.strip() or (og.title if og else "") or hostname_of(clean_url) or "未命名作品"
    clean_desc = description.strip() or (og.description if og else "")
    if resolved_slug is None:
        resolved_slug = store.unique_slug(db, clean_title)
    cover = ""
    if og is not None and og.image_url:
        raw = fetch_image_fn(og.image_url)
        if raw is not None:
            cover = save_cover(config, raw, resolved_slug)
    project = Project(
        slug=resolved_slug,
        type="link",
        parent_id=parent.id if parent else None,
        title=clean_title[:200],
        description=clean_desc[:500],
        url=clean_url,
        cover=cover,
        sort_order=store.next_sort_order(db, parent.id if parent else None),
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def patch_project_meta(
    db: Session,
    config: Config,
    project: Project,
    *,
    title: str | None = None,
    description: str | None = None,
    url: str | None = None,
    visible: bool | None = None,
    pinned: bool | None = None,
    parent_id: int | None = None,
    update_parent: bool = False,
    password: str | None = None,
) -> Project:
    if url is not None and not url.lower().startswith(("http://", "https://")):
        raise ServiceError(
            "链接必须以 http:// 或 https:// 开头",
            400,
            code="invalid_url",
            hint="请提供以 http:// 或 https:// 开头的有效链接",
        )

    new_parent_id = project.parent_id
    if update_parent:
        if parent_id is None:
            new_parent_id = None
        else:
            if parent_id == project.id:
                raise ServiceError(
                    "不能将项目移动到自身之下",
                    400,
                    code="parent_cycle",
                    hint="请选择其他父级空间或置空以移回根目录",
                )
            target_parent = store.by_id(db, parent_id)
            if target_parent is None:
                raise ServiceError(
                    "父级不存在",
                    404,
                    code="parent_not_found",
                    hint="请检查父级 ID 是否正确",
                )
            desc_ids = {row.id for row in store.descendants(db, project)}
            if parent_id in desc_ids:
                raise ServiceError(
                    "不能将项目移动到其子项之下（会形成循环）",
                    400,
                    code="parent_cycle",
                    hint="目标父级不能是当前项目的后代",
                )
            _validate_parent(db, target_parent)
            subtree_height = _subtree_max_relative_depth(db, project)
            if store.depth(db, target_parent) + 1 + subtree_height > 3:
                raise ServiceError(
                    "已达最大嵌套深度（3 层）",
                    400,
                    code="max_depth_exceeded",
                    hint="移动后子树总深度不能超过 3 层",
                )
            new_parent_id = target_parent.id

    clean_title: str | None = None
    if title is not None:
        clean_title = title.strip()[:200]
        if not clean_title:
            raise ServiceError("标题不能为空", 422, code="empty_title")

    clean_desc: str | None = None
    if description is not None:
        clean_desc = description.strip()[:500]

    if project.type == "blog" and (clean_title is not None or clean_desc is not None):
        blog = blog_content(project.content, project_slug=project.slug, config=config)
        if clean_title is not None:
            blog["title"] = clean_title
        if clean_desc is not None:
            blog["description"] = clean_desc
        project.content = json.dumps(blog, ensure_ascii=False)

    if clean_title is not None:
        project.title = clean_title
    if clean_desc is not None:
        project.description = clean_desc
    if url is not None:
        project.url = url
    if visible is not None:
        project.visible = bool(visible)
    if pinned is not None:
        project.pinned = bool(pinned)
    if update_parent and new_parent_id != project.parent_id:
        project.parent_id = new_parent_id
        project.sort_order = store.next_sort_order(db, new_parent_id)
    if password is not None:
        p_clean = password.strip()
        if p_clean in ("", "none", "clear"):
            project.password_hash = None
        else:
            project.password_hash = hash_project_password(p_clean)

    touch(project)
    db.commit()
    db.refresh(project)
    return project


def _invalid_object_message(project_type: str) -> str:
    if project_type == "blog":
        return "博客内容必须是 JSON 对象"
    if project_type == "resume":
        return "简历内容必须是 JSON 对象"
    if project_type == "bottle":
        return "漂流瓶配置必须是 JSON 对象"
    return "空间配置必须是 JSON 对象"


def patch_project_content(
    db: Session,
    config: Config,
    project: Project,
    incoming: dict[str, Any],
    *,
    merge: bool = True,
) -> dict[str, Any]:
    if project.type not in CONTENT_EDITABLE_TYPES:
        raise ServiceError(
            "该类型不支持内容编辑",
            400,
            code="unsupported_content_type",
            hint="仅 blog、resume、bottle、space 类型支持内容编辑",
        )
    if not isinstance(incoming, dict):
        raise ServiceError(_invalid_object_message(project.type), 422, code="invalid_content")

    ext_caps = capabilities_of(project)
    existing_parsed = _parse_raw_content(project, config, strict=False)
    old_media = referenced_media_urls(existing_parsed, capabilities=ext_caps, config=config)

    if merge:
        candidate: dict[str, Any] = dict(existing_parsed)
        for key, value in incoming.items():
            if (
                project.type == "resume"
                and key == "basics"
                and isinstance(value, dict)
                and isinstance(existing_parsed.get("basics"), dict)
            ):
                existing_basics = existing_parsed["basics"]
                merged_basics = dict(existing_basics)
                merged_basics.update(value)
                if isinstance(existing_basics.get("location"), dict) and isinstance(
                    value.get("location"), dict
                ):
                    merged_loc = dict(existing_basics["location"])
                    merged_loc.update(value["location"])
                    merged_basics["location"] = merged_loc
                candidate["basics"] = merged_basics
            elif (
                project.type == "resume"
                and key == "ai_visibility"
                and isinstance(value, dict)
                and isinstance(existing_parsed.get("ai_visibility"), dict)
            ):
                merged_vis = dict(existing_parsed["ai_visibility"])
                merged_vis.update(value)
                candidate["ai_visibility"] = merged_vis
            else:
                candidate[key] = value
    else:
        candidate = dict(incoming)
        if project.type == "resume":
            existing_basics = existing_parsed.get("basics")
            existing_image = existing_basics.get("image") if isinstance(existing_basics, dict) else ""
            if isinstance(existing_image, str) and existing_image:
                incoming_basics = candidate.get("basics")
                if isinstance(incoming_basics, dict) and "image" not in incoming_basics:
                    candidate["basics"] = {**incoming_basics, "image": existing_image}

    if "extensions" not in incoming:
        if existing_parsed.get("extensions"):
            candidate["extensions"] = existing_parsed["extensions"]
        else:
            candidate.pop("extensions", None)
    else:
        candidate = merge_content_extension_secrets(
            existing_parsed,
            candidate,
            capabilities=ext_caps,
            config=config,
        )

    try:
        merged_raw = json.dumps(candidate, ensure_ascii=False)
        if project.type == "blog":
            validated = blog_content(
                merged_raw,
                strict=True,
                project_slug=project.slug,
                config=config,
            )
        elif project.type == "resume":
            validated = resume_content(
                merged_raw,
                strict=True,
                project_slug=project.slug,
                config=config,
            )
        elif project.type == "bottle":
            validated = bottle_content(
                merged_raw,
                strict=True,
                project_slug=project.slug,
                config=config,
            )
        else:
            validated = validate_space_content(
                candidate,
                strict=True,
                project_slug=project.slug,
                config=config,
            )
    except InvalidContent as exc:
        raise ServiceError(str(exc), 422, code="invalid_content") from exc

    project.content = json.dumps(validated, ensure_ascii=False)
    touch(project)
    db.commit()
    new_media = referenced_media_urls(validated, capabilities=ext_caps, config=config)
    cleanup_unreferenced_media(config, project.slug, old_media, new_media)
    if ext_caps is None:
        return validated
    return redact_content_extensions(validated, capabilities=ext_caps, config=config)


def delete_project_cascade(db: Session, config: Config, project: Project) -> None:
    rows = [*reversed(store.descendants(db, project)), project]
    project_ids = [row.id for row in rows]
    store.delete_stats(db, project_ids)
    submissions.delete_project_submissions(db, project_ids, commit=False)
    for row in rows:
        store.delete_files(config, row)
        db.delete(row)
        db.flush()
    db.commit()


def replace_cover(db: Session, config: Config, project: Project, raw: bytes) -> Project:
    if len(raw) > COVER_LIMIT:
        raise ServiceError("封面不能超过 10MB", 413, code="file_too_large")
    filename = f"{project.slug}-{secrets.token_hex(6)}.webp"
    destination = config.data / "media" / "covers" / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        make_cover(raw, destination)
    except InvalidUpload as exc:
        raise ServiceError(str(exc), 422, code="invalid_image") from exc
    old_name = project.cover
    project.cover = filename
    touch(project)
    db.commit()
    db.refresh(project)
    if old_name and old_name != filename:
        old_path = config.data / "media" / "covers" / old_name
        if old_path.exists():
            old_path.unlink()
    return project


def remove_cover(db: Session, config: Config, project: Project) -> Project:
    old_name = project.cover
    project.cover = ""
    touch(project)
    db.commit()
    db.refresh(project)
    if old_name:
        (config.data / "media" / "covers" / old_name).unlink(missing_ok=True)
    return project


def _decorate_post(project: Project, post: dict[str, Any], *, include_body: bool = True) -> dict[str, Any]:
    out: dict[str, Any] = {
        "slug": post["slug"],
        "title": post["title"],
        "date": post["date"],
        "tags": list(post["tags"]),
        "summary": post["summary"],
        "url": f"/projects/{project.slug}/posts/{post['slug']}",
    }
    if include_body:
        out["body"] = post["body"]
    if "meta" in post and isinstance(post["meta"], dict):
        out["meta"] = dict(post["meta"])
    return out


def list_blog_posts(
    config: Config,
    project: Project,
    *,
    tag: str | None = None,
    q: str | None = None,
    include_body: bool = False,
) -> list[dict[str, Any]]:
    _require_blog(project)
    content = blog_content(project.content, project_slug=project.slug, config=config)
    tag_clean = tag.strip().lower() if isinstance(tag, str) and tag.strip() else ""
    q_clean = q.strip().lower() if isinstance(q, str) and q.strip() else ""
    items: list[dict[str, Any]] = []
    for post in content["posts"]:
        if tag_clean and not any(t.lower() == tag_clean for t in post.get("tags", [])):
            continue
        if q_clean:
            haystack = " ".join(
                [
                    post.get("title", ""),
                    post.get("slug", ""),
                    post.get("summary", ""),
                    post.get("body", ""),
                    " ".join(post.get("tags", [])),
                ]
            ).lower()
            if q_clean not in haystack:
                continue
        items.append(_decorate_post(project, post, include_body=include_body))
    return items


def get_blog_post(config: Config, project: Project, post_slug: str) -> dict[str, Any]:
    _require_blog(project)
    content = blog_content(project.content, project_slug=project.slug, config=config)
    post = next((item for item in content["posts"] if item["slug"] == post_slug), None)
    if post is None:
        raise ServiceError(
            "文章不存在，请返回文章列表",
            404,
            code="post_not_found",
            hint="请检查文章 slug 是否存在",
        )
    return _decorate_post(project, post, include_body=True)


def _merge_post_meta(existing_meta: object, incoming_meta: object) -> Any:
    if incoming_meta is None:
        return dict(existing_meta) if isinstance(existing_meta, dict) else None
    if not isinstance(incoming_meta, dict):
        return incoming_meta
    merged = dict(existing_meta) if isinstance(existing_meta, dict) else {}
    for key, value in incoming_meta.items():
        if value == "" or value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    return merged


def _persist_blog_posts(
    db: Session,
    config: Config,
    project: Project,
    content: dict[str, Any],
    candidate: dict[str, Any],
    old_media: set[str],
) -> dict[str, Any]:
    try:
        validated = blog_content(
            json.dumps(content, ensure_ascii=False),
            strict=True,
            project_slug=project.slug,
            config=config,
        )
        saved = blog_content(
            json.dumps({"posts": [candidate]}, ensure_ascii=False),
            strict=True,
            project_slug=project.slug,
            config=config,
        )["posts"][0]
    except InvalidContent as exc:
        raise ServiceError(str(exc), 422, code="invalid_post") from exc
    project.content = json.dumps(validated, ensure_ascii=False)
    touch(project)
    db.commit()
    cleanup_unreferenced_media(
        config,
        project.slug,
        old_media,
        referenced_media_urls(validated, target="blog", config=config),
    )
    return _decorate_post(project, saved, include_body=True)


def create_blog_post(
    db: Session,
    config: Config,
    project: Project,
    data: dict[str, Any],
) -> dict[str, Any]:
    _require_blog(project)
    if not isinstance(data, dict):
        raise ServiceError("文章格式不正确", 422, code="invalid_post")
    content = blog_content(project.content, project_slug=project.slug, config=config)
    old_media = referenced_media_urls(content, target="blog", config=config)
    candidate = dict(data)
    raw_title = candidate.get("title")
    title_clean = raw_title.strip() if isinstance(raw_title, str) else ""
    if not title_clean:
        raise ServiceError("文章标题不能为空", 422, code="invalid_post", hint="请提供非空的 title 字段")
    raw_date = candidate.get("date")
    if raw_date is None or (isinstance(raw_date, str) and not raw_date.strip()):
        candidate["date"] = datetime.now(UTC).strftime("%Y-%m-%d")
    target_slug = normalize_post_slug(candidate.get("slug")) or normalize_post_slug(title_clean)
    if not target_slug:
        raise ServiceError("文章网址标识不能为空或重复，请修改后重试", 422, code="invalid_post_slug")
    if any(post["slug"] == target_slug for post in content["posts"]):
        raise ServiceError(
            "文章网址标识已存在",
            409,
            code="post_slug_exists",
            hint="请更换 slug，或改用幂等 PUT 更新 / PATCH 局部修改",
        )
    content["posts"].append(candidate)
    return _persist_blog_posts(db, config, project, content, candidate, old_media)


def upsert_blog_post(
    db: Session,
    config: Config,
    project: Project,
    post_slug: str,
    data: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    _require_blog(project)
    if not isinstance(data, dict):
        raise ServiceError("文章格式不正确", 422, code="invalid_post")
    cleaned_slug = _validate_post_slug(post_slug, status_code=400)
    content = blog_content(project.content, project_slug=project.slug, config=config)
    old_media = referenced_media_urls(content, target="blog", config=config)
    posts = content["posts"]
    index = next((i for i, post in enumerate(posts) if post["slug"] == cleaned_slug), None)
    created = index is None

    candidate = dict(data)
    candidate["slug"] = cleaned_slug
    raw_title = candidate.get("title")
    if not isinstance(raw_title, str) or not raw_title.strip():
        raise ServiceError("文章标题不能为空", 422, code="invalid_post", hint="请提供非空的 title 字段")

    if created:
        raw_date = candidate.get("date")
        if raw_date is None or (isinstance(raw_date, str) and not raw_date.strip()):
            candidate["date"] = datetime.now(UTC).strftime("%Y-%m-%d")
        posts.append(candidate)
    else:
        existing = posts[index]
        if "date" not in data or data.get("date") is None:
            candidate["date"] = existing.get("date", "")
        merged_meta = _merge_post_meta(existing.get("meta"), data.get("meta") if "meta" in data else None)
        if merged_meta is not None:
            candidate["meta"] = merged_meta
        posts[index] = candidate

    saved = _persist_blog_posts(db, config, project, content, candidate, old_media)
    return saved, created


def patch_blog_post(
    db: Session,
    config: Config,
    project: Project,
    post_slug: str,
    patch: dict[str, Any],
    *,
    new_slug: str | None = None,
) -> dict[str, Any]:
    _require_blog(project)
    if not isinstance(patch, dict):
        raise ServiceError("文章格式不正确", 422, code="invalid_post")
    content = blog_content(project.content, project_slug=project.slug, config=config)
    old_media = referenced_media_urls(content, target="blog", config=config)
    posts = content["posts"]
    index = next((i for i, post in enumerate(posts) if post["slug"] == post_slug), None)
    if index is None:
        raise ServiceError(
            "文章不存在，请返回文章列表",
            404,
            code="post_not_found",
            hint="请检查文章 slug 是否存在",
        )
    existing = posts[index]
    candidate: dict[str, Any] = dict(existing)
    if isinstance(existing.get("tags"), list):
        candidate["tags"] = list(existing["tags"])
    if isinstance(existing.get("meta"), dict):
        candidate["meta"] = dict(existing["meta"])

    for field in ("title", "date", "tags", "summary", "body"):
        if field in patch:
            candidate[field] = patch[field]

    if "meta" in patch:
        merged_meta = _merge_post_meta(existing.get("meta"), patch["meta"])
        if merged_meta is None:
            candidate.pop("meta", None)
        else:
            candidate["meta"] = merged_meta

    if new_slug is not None:
        cleaned_new = _validate_post_slug(new_slug, status_code=422)
        if cleaned_new != post_slug and any(
            i != index and post["slug"] == cleaned_new for i, post in enumerate(posts)
        ):
            raise ServiceError(
                "文章网址标识已存在",
                409,
                code="post_slug_exists",
                hint="请更换新的文章 slug",
            )
        candidate["slug"] = cleaned_new

    posts[index] = candidate
    return _persist_blog_posts(db, config, project, content, candidate, old_media)


def delete_blog_post(db: Session, config: Config, project: Project, post_slug: str) -> None:
    _require_blog(project)
    content = blog_content(project.content, project_slug=project.slug, config=config)
    old_media = referenced_media_urls(content, target="blog", config=config)
    if not any(post["slug"] == post_slug for post in content["posts"]):
        raise ServiceError(
            "文章不存在，请返回文章列表",
            404,
            code="post_not_found",
            hint="请检查文章 slug 是否存在",
        )
    content["posts"] = [post for post in content["posts"] if post["slug"] != post_slug]
    project.content = json.dumps(content, ensure_ascii=False)
    touch(project)
    db.commit()
    cleanup_unreferenced_media(
        config,
        project.slug,
        old_media,
        referenced_media_urls(content, target="blog", config=config),
    )


def upload_blog_media(
    config: Config,
    project: Project,
    raw: bytes,
    *,
    kind: str = "image",
    filename: str = "",
    content_type: str = "",
) -> dict[str, str]:
    _require_blog(project)
    cleaned_kind = kind.strip() if isinstance(kind, str) else ""
    if cleaned_kind not in BLOG_UPLOAD_KINDS:
        raise ServiceError(
            "不支持的图片用途，仅支持 image、cover 或 bg",
            400,
            code="invalid_media_kind",
            hint="kind 可选值：image、cover、bg",
        )
    if len(raw) > COVER_LIMIT:
        raise ServiceError("图片不能超过 10MB", 413, code="file_too_large")
    try:
        url = save_blog_media(
            config,
            project.slug,
            cleaned_kind,
            raw,
            filename=filename,
            content_type=content_type,
        )
    except InvalidUpload as exc:
        raise ServiceError(str(exc), 422, code="invalid_image") from exc
    return {"url": url, "markdown": f"![]({url})"}


def deploy_static_bytes(
    db: Session,
    config: Config,
    *,
    slug: str,
    raw_bytes: bytes,
    filename: str,
    title: str = "",
    description: str = "",
    visible: bool | None = None,
    parent_id: int | None = None,
    allowed_parent_check: Callable[[Project | None], None] | None = None,
) -> tuple[Project, bool]:
    clean_slug = validate_slug(slug)
    if len(raw_bytes) > config.upload_limit:
        raise ServiceError("文件超出大小限制", 413, code="file_too_large")
    base_name = Path(filename or "").name
    lower_name = base_name.lower()
    if not lower_name.endswith((".html", ".htm", ".zip")):
        raise ServiceError(
            "只支持 .html / .htm / .zip 文件",
            400,
            code="unsupported_file_type",
            hint="请上传 .html、.htm 或 .zip 格式文件",
        )
    parent = resolve_parent_by_id(db, parent_id)
    existing = store.by_slug(db, clean_slug)
    if existing is not None:
        if existing.type not in ("static", "html", "zip"):
            raise ServiceError(
                "该标识已被非静态项目占用",
                409,
                code="slug_type_conflict",
                hint="请更换其他 slug，或确认目标项目为静态制品",
            )
    elif allowed_parent_check is not None:
        allowed_parent_check(parent)

    suffix = ".html" if lower_name.endswith((".html", ".htm")) else ".zip"
    tmp_token = store.unique_slug_name()
    tmp_path = config.data / "tmp" / f"{tmp_token}{suffix}"
    stage_dir = config.data / "tmp" / f"stage_{tmp_token}"
    backup_dir = config.data / "tmp" / f"backup_{tmp_token}"
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        tmp_path.write_bytes(raw_bytes)
        try:
            stage_dir.mkdir(parents=True, exist_ok=True)
            if suffix == ".html":
                shutil.copyfile(tmp_path, stage_dir / "index.html")
                entry = "index.html"
            else:
                entry = extract_site(tmp_path, stage_dir, config)
        except InvalidUpload as exc:
            remove_tree(stage_dir)
            raise ServiceError(str(exc), 422, code="invalid_upload") from exc
        except Exception:
            remove_tree(stage_dir)
            raise

        folder = config.data / "projects" / clean_slug
        folder.parent.mkdir(parents=True, exist_ok=True)
        if folder.exists():
            remove_tree(backup_dir)
            folder.rename(backup_dir)
        try:
            stage_dir.rename(folder)
        except Exception:
            if backup_dir.exists() and not folder.exists():
                backup_dir.rename(folder)
            raise
        finally:
            remove_tree(backup_dir)

        created = existing is None
        if existing is not None:
            existing.entry = entry
            if title.strip():
                existing.title = title.strip()[:200]
            if description.strip():
                existing.description = description.strip()[:500]
            if visible is not None:
                existing.visible = visible
            if parent_id is not None:
                new_parent_id = parent.id if parent else None
                if existing.parent_id != new_parent_id:
                    existing.parent_id = new_parent_id
                    existing.sort_order = store.next_sort_order(db, new_parent_id)
            touch(existing)
            project = existing
        else:
            name_title = (base_name.rsplit(".", 1)[0] or clean_slug)[:200]
            project_title = (title.strip() or name_title)[:200]
            project = Project(
                slug=clean_slug,
                type="static",
                parent_id=parent.id if parent else None,
                title=project_title,
                description=description.strip()[:500],
                entry=entry,
                visible=True if visible is None else visible,
                sort_order=store.next_sort_order(db, parent.id if parent else None),
            )
            db.add(project)
        db.commit()
        db.refresh(project)
        return project, created
    finally:
        tmp_path.unlink(missing_ok=True)
        remove_tree(stage_dir)
        remove_tree(backup_dir)


def list_project_extensions_v1(
    db: Session,
    config: Config,
    project: Project,
) -> list[dict[str, Any]]:
    caps = capabilities_of(project)
    if caps is None:
        raise ServiceError(
            "该类型不支持插件",
            400,
            code="extensions_unsupported",
            hint="仅具备扩展能力的应用类型支持插件管理",
        )
    content = _parse_raw_content(project, config, strict=False)
    return build_project_admin_catalog(
        db,
        project,
        capabilities=caps,
        config=config,
        content=content,
    )


def set_project_extension_state_v1(
    db: Session,
    config: Config,
    project: Project,
    ext_id: str,
    *,
    mode: str | None = None,
    enabled: bool | None = None,
    cascade: bool | None = None,
    incoming_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    caps = capabilities_of(project)
    if caps is None:
        raise ServiceError(
            "该类型不支持插件",
            400,
            code="extensions_unsupported",
            hint="仅具备扩展能力的应用类型支持插件管理",
        )
    ext = get_extension(ext_id, config=config)
    if ext is None:
        raise ServiceError(
            "插件不存在",
            404,
            code="extension_not_found",
            hint="请先查询该项目可用插件列表确认插件 ID",
        )
    if not ext.matches_capabilities(caps):
        raise ServiceError(
            "该插件不适用于当前应用类型",
            400,
            code="extension_incompatible",
            hint="请选择适用于当前项目类型的插件",
        )

    content = _parse_raw_content(project, config, strict=False)
    old_media = referenced_media_urls(content, capabilities=caps, config=config)
    ext_map = dict(content.get("extensions") or {})
    prev_state = parse_layer_state(ext_map.get(ext.id), is_site=False)

    if mode is not None:
        if mode not in VALID_MODES:
            raise ServiceError(
                "插件继承模式必须是 inherit、override 或 disabled",
                422,
                code="invalid_extension_mode",
                hint="mode 可选值：inherit、override、disabled",
            )
        next_mode = mode
    elif enabled is not None:
        next_mode = "override" if enabled else "disabled"
    elif prev_state.mode != "inherit":
        next_mode = prev_state.mode
    else:
        next_mode = "override"

    if next_mode == "inherit":
        ext_map.pop(ext.id, None)
    else:
        try:
            sparse_cfg = merge_layer_config(
                ext,
                prev_state.config,
                incoming_config,
                strict=True,
                project_slug=project.slug,
            )
        except InvalidContent as exc:
            raise ServiceError(str(exc), 422, code="invalid_extension_config") from exc
        next_cascade = False
        if "has_children" in caps:
            next_cascade = prev_state.cascade if cascade is None else bool(cascade)
        ext_map[ext.id] = {
            "mode": next_mode,
            "cascade": next_cascade,
            "config": sparse_cfg,
        }

    if ext_map:
        content["extensions"] = ext_map
    else:
        content.pop("extensions", None)
    project.content = json.dumps(content, ensure_ascii=False)
    touch(project)
    db.commit()
    cleanup_unreferenced_media(
        config,
        project.slug,
        old_media,
        referenced_media_urls(content, capabilities=caps, config=config),
    )
    resolved = resolve_project_extension(
        db,
        project,
        ext.id,
        capabilities=caps,
        config=config,
        content=content,
    )
    assert resolved is not None
    return resolved_catalog_item(resolved)


def list_project_submissions_v1(
    db: Session,
    project: Project,
    *,
    status: str | None = None,
    plugin_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    filter_status: str | None = None
    if status and status != "all":
        if status not in submissions.VALID_STATUSES:
            raise ServiceError(
                "不支持的审核状态",
                400,
                code="invalid_submission_status",
                hint="可选状态：pending、approved、rejected、all",
            )
        filter_status = status
    clean_plugin = plugin_id.strip() if isinstance(plugin_id, str) and plugin_id.strip() else None
    items = submissions.list_submissions(
        db,
        project_id=project.id,
        plugin_id=clean_plugin,
        status=filter_status,
        limit=limit,
        offset=offset,
    )
    counts = submissions.count_submissions(db, project_id=project.id, plugin_id=clean_plugin)
    banned_ips = submissions.list_banned_ips(db, project_id=project.id)
    return {"submissions": items, "counts": counts, "banned_ips": banned_ips}


def update_submission_status_v1(
    db: Session,
    project: Project,
    sub_id: int,
    *,
    action: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    raw_action = (action or status or "").strip().lower()
    action_map = {
        "approve": "approved",
        "approved": "approved",
        "reject": "rejected",
        "rejected": "rejected",
        "pending": "pending",
        "delete": "delete",
    }
    normalized = action_map.get(raw_action)
    if normalized is None:
        raise ServiceError(
            "不支持的审核操作",
            400,
            code="invalid_submission_action",
            hint="支持操作：approve、reject、pending、delete",
        )
    if normalized == "delete":
        deleted = submissions.delete_submission(db, project_id=project.id, sub_id=sub_id)
        if not deleted:
            raise ServiceError(
                "提交记录不存在",
                404,
                code="submission_not_found",
                hint="请检查提交记录 ID 是否属于该项目",
            )
        counts = submissions.count_submissions(db, project_id=project.id)
        return {"deleted": True, "counts": counts}
    updated = submissions.set_submission_status(
        db,
        project_id=project.id,
        sub_id=sub_id,
        status=normalized,
    )
    if updated is None:
        raise ServiceError(
            "提交记录不存在",
            404,
            code="submission_not_found",
            hint="请检查提交记录 ID 是否属于该项目",
        )
    counts = submissions.count_submissions(db, project_id=project.id)
    return {"submission": updated, "counts": counts}
