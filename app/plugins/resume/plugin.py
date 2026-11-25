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
BASICS_FIELD_LABELS = {
    "name": "姓名",
    "label": "职位 / 头衔",
    "email": "邮箱",
    "phone": "电话",
    "summary": "简介",
}
LIMITS = {"text": 2000, "short": 200, "url": 500, "highlight": 500, "list": 20}
PRIVATE_BASICS = frozenset({"email", "phone"})
SECTIONS = ("work", "education", "projects", "skills")
SECTION_LABELS = {
    "work": "工作经历",
    "education": "教育经历",
    "projects": "项目",
    "skills": "技能",
}
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
SECTION_LONG_FIELDS = {
    "work": frozenset({"summary"}),
    "projects": frozenset({"description"}),
}
SECTION_FIELD_LABELS = {
    "name": "名称",
    "position": "职位",
    "startDate": "开始时间",
    "endDate": "结束时间",
    "summary": "摘要",
    "institution": "学校",
    "area": "专业",
    "studyType": "学历",
    "description": "描述",
    "url": "链接",
    "highlights": "要点",
    "keywords": "关键词",
}
SECTION_LIST_FIELDS = {
    "work": ("highlights",),
    "projects": ("highlights", "keywords"),
    "skills": ("keywords",),
}
SECTION_URL_FIELDS = {"work": ("url",), "projects": ("url",)}


def _text(
    value: object,
    limit: int = LIMITS["short"],
    *,
    strict: bool = False,
    label: str = "内容",
) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = value.strip()
    if strict and len(cleaned) > limit:
        raise InvalidContent(f"{label}不能超过 {limit} 字")
    return cleaned[:limit]


def _url(value: object, *, strict: bool = False, label: str = "链接") -> str:
    text = _text(value, LIMITS["url"], strict=strict, label=label)
    return text if text.startswith(("http://", "https://", "/")) else ""


def _image(value: object, *, strict: bool = False) -> str:
    text = _text(value, LIMITS["short"], strict=strict, label="头像文件名")
    return text if text and "/" not in text and not text.startswith(".") else ""


def _string_list(
    value: object,
    limit: int = LIMITS["short"],
    *,
    strict: bool = False,
    label: str = "列表项",
) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    if strict and len(cleaned) > LIMITS["list"]:
        raise InvalidContent(f"{label}不能超过 {LIMITS['list']} 条")
    out: list[str] = []
    for item in cleaned[: LIMITS["list"]]:
        if strict and len(item) > limit:
            raise InvalidContent(f"{label}单条不能超过 {limit} 字")
        out.append(item[:limit])
    return out


def _normalize_ai_visibility(raw: object, *, strict: bool = False) -> dict[str, bool]:
    out = dict(DEFAULT_AI_VISIBILITY)
    if raw is None:
        return out
    if not isinstance(raw, dict):
        if strict:
            raise InvalidContent("插件可见性配置必须是对象")
        return out
    for key in AI_VISIBILITY_KEYS:
        if key not in raw:
            continue
        value = raw[key]
        if isinstance(value, bool):
            out[key] = value
        elif strict:
            raise InvalidContent("插件可见性选项必须是布尔值")
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
                source.get(field),
                LIMITS["text"] if field == "summary" else LIMITS["short"],
                strict=strict,
                label=BASICS_FIELD_LABELS[field],
            )
        content["basics"]["image"] = _image(source.get("image"), strict=strict)
        content["basics"]["url"] = _url(source.get("url"), strict=strict, label="网站链接")
        location = source.get("location")
        if isinstance(location, dict):
            for field, loc_label in (("city", "城市"), ("region", "地区"), ("countryCode", "国家代码")):
                content["basics"]["location"][field] = _text(
                    location.get(field),
                    strict=strict,
                    label=loc_label,
                )
        profiles = source.get("profiles")
        if isinstance(profiles, list):
            dict_profiles = [item for item in profiles if isinstance(item, dict)]
            if strict and len(dict_profiles) > LIMITS["list"]:
                raise InvalidContent(f"社交链接不能超过 {LIMITS['list']} 条")
            content["basics"]["profiles"] = [
                {
                    "network": _text(item.get("network"), strict=strict, label="社交平台名称"),
                    "username": _text(item.get("username"), strict=strict, label="社交用户名"),
                    "url": _url(item.get("url"), strict=strict, label="社交链接"),
                }
                for item in dict_profiles[: LIMITS["list"]]
            ]
    for section in SECTIONS:
        rows = parsed.get(section)
        if not isinstance(rows, list):
            continue
        sec_label = SECTION_LABELS[section]
        dict_rows = [row for row in rows if isinstance(row, dict)]
        if strict and len(dict_rows) > LIMITS["list"] * 5:
            raise InvalidContent(f"{sec_label}不能超过 {LIMITS['list'] * 5} 条")
        long_fields = SECTION_LONG_FIELDS.get(section, frozenset())
        normalized_rows = []
        for row in dict_rows[: LIMITS["list"] * 5]:
            item: dict[str, object] = {
                field: _text(
                    row.get(field),
                    LIMITS["text"] if field in long_fields else LIMITS["short"],
                    strict=strict,
                    label=f"{sec_label}{SECTION_FIELD_LABELS[field]}",
                )
                for field in SECTION_TEXT_FIELDS[section]
            }
            for field in SECTION_URL_FIELDS.get(section, ()):
                item[field] = _url(
                    row.get(field),
                    strict=strict,
                    label=f"{sec_label}{SECTION_FIELD_LABELS[field]}",
                )
            for field in SECTION_LIST_FIELDS.get(section, ()):
                item_limit = LIMITS["highlight"] if field == "highlights" else LIMITS["short"]
                item[field] = _string_list(
                    row.get(field),
                    item_limit,
                    strict=strict,
                    label=f"{sec_label}{SECTION_FIELD_LABELS[field]}",
                )
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
        plugin_basics = dict(basics)
        if not visibility["contact"]:
            for field in PRIVATE_BASICS:
                plugin_basics.pop(field, None)
        if not visibility["location"]:
            plugin_basics.pop("location", None)
        plugin_ctx: dict[str, Any] = {"basics": plugin_basics}
        for section in SECTIONS:
            if visibility[section]:
                plugin_ctx[section] = public.get(section, [])
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
            contexts={"visitor": public, "plugin": plugin_ctx, "ai": plugin_ctx, "admin": resume},
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
