import json

from fastapi import Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.models import Project
from app.plugins.base import InvalidContent
from app.templating import templates

BASICS_TEXT_FIELDS = ("name", "label", "email", "phone", "summary")
LIMITS = {"text": 2000, "short": 200, "url": 500, "list": 20}
SECTIONS = ("work", "education", "projects", "skills")
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
    }


def normalize(parsed: dict) -> dict:
    content = default_content()
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
    return content


def validate_content(raw: str) -> dict:
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise InvalidContent("简历内容不是合法 JSON") from exc
    if not isinstance(parsed, dict):
        raise InvalidContent("简历内容必须是 JSON 对象")
    return normalize(parsed)


class ResumeApp:
    type: str = "resume"
    label: str = "简历"
    icon: str = "file-text"
    leaf: bool = True
    content_editable: bool = True
    admin_template: str | None = "resume_admin.html"

    def default_content(self) -> dict:
        return default_content()

    def validate_content(self, raw: str) -> dict:
        return validate_content(raw)

    def route(self, request: Request, project: Project, path: str, db: Session):
        return None

    def render(self, request: Request, project: Project, db: Session) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "resume.html",
            {"project": project, "resume": validate_content(project.content)},
        )
