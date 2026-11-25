import json
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import read_session
from app.extensions.registry import build_render_bundle, normalize_extensions
from app.models import Project
from app.plugins.base import InvalidContent
from app.surface import Capability, StaticSurface, SurfaceItem, project_meta
from app.templating import templates

BASICS_TEXT_FIELDS = ("name", "label", "email", "phone", "summary")
LIMITS = {"text": 2000, "short": 200, "url": 500, "list": 20}
PRIVATE_BASICS = frozenset({"email", "phone"})
SECTIONS = ("work", "education", "projects", "skills")
AI_VISIBILITY_KEYS = ("contact", "location", "work", "education", "projects", "skills")
DEFAULT_AI_VISIBILITY: dict[str, bool] = {
    "contact": False,
    "location": False,
    "work": True,
    "education": True,
    "projects": True,
    "skills": True,
}
RESUME_CAPABILITIES: frozenset[Capability] = frozenset({"has_content", "is_personal_profile", "has_items"})
SECTION_TEXT_FIELDS = {
    "work": ("name", "position", "startDate", "endDate", "summary"),
    "education": ("institution", "area", "studyType", "startDate", "endDate"),
    "projects": ("name", "description"),
    "skills": ("name",),
}
SECTION_LIST_FIELDS = {
    "work": ("highlights",),
    "projects": ("highlights", "keywords"),
    "skills": ("keywords",),
}
SECTION_URL_FIELDS = {"work": ("url",), "projects": ("url",)}


def _text(value: object, limit: int = LIMITS["short"]) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _url(value: object) -> str:
    text = _text(value, LIMITS["url"])
    return text if text.startswith(("http://", "https://", "/")) else ""


def _image(value: object) -> str:
    text = _text(value, LIMITS["short"])
    return text if text and "/" not in text and not text.startswith(".") else ""


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_text(item, LIMITS["short"]) for item in value[: LIMITS["list"]] if _text(item, LIMITS["short"])]


def _normalize_ai_visibility(raw: object, *, strict: bool = False) -> dict[str, bool]:
    out = dict(DEFAULT_AI_VISIBILITY)
    if raw is None:
        return out
    if not isinstance(raw, dict):
        if strict:
            raise InvalidContent("AI 可见性配置必须是对象")
        return out
    for key in AI_VISIBILITY_KEYS:
        if key not in raw:
            continue
        value = raw[key]
        if isinstance(value, bool):
            out[key] = value
        elif strict:
            raise InvalidContent("AI 可见性选项必须是布尔值")
    return out


def default_content() -> dict:
    return {
        "basics": {
            "name": "",
            "label": "",
            "image": "",
            "email": "",
            "phone": "",
            "url": "",
            "summary": "",
            "location": {"city": "", "region": "", "countryCode": ""},
            "profiles": [],
        },
        "work": [],
        "education": [],
        "projects": [],
        "skills": [],
        "ai_visibility": dict(DEFAULT_AI_VISIBILITY),
    }


def normalize(
    parsed: dict,
    strict: bool = False,
    project_slug: str | None = None,
    config: Any = None,
) -> dict[str, Any]:
    content: dict[str, Any] = default_content()
    source = parsed.get("basics")
    if isinstance(source, dict):
        for field in BASICS_TEXT_FIELDS:
            content["basics"][field] = _text(
                source.get(field), LIMITS["text"] if field == "summary" else LIMITS["short"]
            )
        content["basics"]["image"] = _image(source.get("image"))
        content["basics"]["url"] = _url(source.get("url"))
        location = source.get("location")
        if isinstance(location, dict):
            for field in ("city", "region", "countryCode"):
                content["basics"]["location"][field] = _text(location.get(field))
        profiles = source.get("profiles")
        if isinstance(profiles, list):
            content["basics"]["profiles"] = [
                {
                    "network": _text(item.get("network")),
                    "username": _text(item.get("username")),
                    "url": _url(item.get("url")),
                }
                for item in profiles[: LIMITS["list"]]
                if isinstance(item, dict)
            ]
    for section in SECTIONS:
        rows = parsed.get(section)
        if not isinstance(rows, list):
            continue
        normalized_rows = []
        for row in rows[: LIMITS["list"] * 5]:
            if not isinstance(row, dict):
                continue
            item: dict[str, object] = {field: _text(row.get(field)) for field in SECTION_TEXT_FIELDS[section]}
            for field in SECTION_URL_FIELDS.get(section, ()):
                item[field] = _url(row.get(field))
            for field in SECTION_LIST_FIELDS.get(section, ()):
                item[field] = _string_list(row.get(field))
            normalized_rows.append(item)
        content[section] = normalized_rows
    content["ai_visibility"] = _normalize_ai_visibility(parsed.get("ai_visibility"), strict=strict)
    extensions = normalize_extensions(
        parsed.get("extensions"),
        strict=strict,
        project_slug=project_slug,
        capabilities=RESUME_CAPABILITIES,
        config=config,
    )
    if extensions:
        content["extensions"] = extensions
    return content


def validate_content(
    raw: str,
    strict: bool = False,
    project_slug: str | None = None,
    config: Any = None,
) -> dict[str, Any]:
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise InvalidContent("简历内容不是合法 JSON") from exc
    if not isinstance(parsed, dict):
        raise InvalidContent("简历内容必须是 JSON 对象")
    return normalize(parsed, strict=strict, project_slug=project_slug, config=config)


class ResumeApp:
    type: str = "resume"
    label: str = "简历"
    icon: str = "file-text"
    leaf: bool = True
    content_editable: bool = True
    admin_template: str | None = "resume_admin.html"
    capabilities: frozenset[Capability] = RESUME_CAPABILITIES

    def default_content(self) -> dict[str, Any]:
        return default_content()

    def validate_content(
        self,
        raw: str,
        project_slug: str | None = None,
        config: Any = None,
    ) -> dict[str, Any]:
        return validate_content(raw, strict=False, project_slug=project_slug, config=config)

    def route(self, request: Request, project: Project, path: str, db: Session):
        if path.strip("/") == "admin":
            return RedirectResponse(f"/admin/projects/{project.id}", status_code=302)
        return None

    def surface(self, request: Request, project: Project, db: Session, *, sub: str = "") -> StaticSurface:
        config = request.app.state.config
        resume = validate_content(project.content, project_slug=project.slug, config=config)
        visibility = _normalize_ai_visibility(resume.get("ai_visibility"), strict=False)
        public = {key: value for key, value in resume.items() if key not in ("extensions", "ai_visibility")}
        basics = dict(public.get("basics") or {})
        ai_basics = dict(basics)
        if not visibility["contact"]:
            for field in PRIVATE_BASICS:
                ai_basics.pop(field, None)
        if not visibility["location"]:
            ai_basics.pop("location", None)
        ai: dict[str, Any] = {"basics": ai_basics}
        for section in SECTIONS:
            if visibility[section]:
                ai[section] = public.get(section, [])
        items = tuple(
            SurfaceItem(
                key=f"{section}-{index}",
                title=str(entry.get("name") or entry.get("institution") or entry.get("position") or ""),
                url=f"/projects/{project.slug}/#{section}",
                summary=str(entry.get("summary") or entry.get("description") or entry.get("area") or ""),
                kind=section,
            )
            for section in SECTIONS
            for index, entry in enumerate(resume.get(section) or [])
            if isinstance(entry, dict)
        )
        return StaticSurface(
            meta=project_meta(db, project, title=str(basics.get("name") or "")),
            capabilities=self.capabilities,
            contexts={"visitor": public, "ai": ai, "admin": resume},
            item_list=items,
        )

    def render(self, request: Request, project: Project, db: Session) -> HTMLResponse:
        config = request.app.state.config
        session = read_session(config, request)
        is_admin = bool(session and session.get("admin") is True)
        resume = validate_content(project.content, project_slug=project.slug, config=config)
        ext = build_render_bundle(
            "resume",
            project,
            resume,
            capabilities=self.capabilities,
            config=config,
            is_admin=is_admin,
            db=db,
        )
        return templates.TemplateResponse(
            request,
            "resume.html",
            {"project": project, "resume": resume, "ext": ext},
        )
