import re
import secrets

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import store, submissions
from app.auth import (
    client_ip,
    project_cookie_name,
    read_session,
    require_same_origin,
    verify_project_token,
)
from app.config import Config
from app.deps import DbSession, api_error, get_config
from app.models import Project
from app.plugins.bottle.plugin import (
    MAX_CREDITS,
    load_bottle_config,
    read_visitor_cookie,
    set_visitor_cookie,
)

router = APIRouter()

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_MESSAGE_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_NICKNAME_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


class BottleThrowPayload(BaseModel):
    message: str = ""
    nickname: str = ""
    website: str = ""


def _has_project_access(request: Request, config: Config, project: Project, is_admin: bool) -> bool:
    if not project.password_hash or is_admin:
        return True
    token = request.cookies.get(project_cookie_name(project.slug))
    return bool(token and verify_project_token(config, project.slug, token, project.password_hash))


def _resolve_bottle_project(
    request: Request,
    db: Session,
    config: Config,
    slug: str,
) -> tuple[Project | None, bool, JSONResponse | None]:
    if not _SLUG_RE.match(slug):
        return None, False, api_error("漂流瓶空间不存在", 404)
    session = read_session(config, request)
    is_admin = bool(session and session.get("admin") is True)
    project = store.by_slug(db, slug)
    if project is None or project.type != "bottle":
        return None, is_admin, api_error("漂流瓶空间不存在", 404)
    if not is_admin:
        if not store.is_visible(db, project):
            return None, is_admin, api_error("漂流瓶空间不存在", 404)
        if not _has_project_access(request, config, project, is_admin):
            return None, is_admin, api_error("需要访问密码", 401)
    return project, is_admin, None


@router.post("/api/projects/{slug}/bottle/throw")
def throw_bottle(
    request: Request,
    slug: str,
    payload: BottleThrowPayload,
    db: DbSession,
) -> JSONResponse:
    require_same_origin(request)
    config = get_config(request)
    project, _is_admin, error = _resolve_bottle_project(request, db, config, slug)
    if error is not None or project is None:
        return error or api_error("漂流瓶空间不存在", 404)

    cfg = load_bottle_config(project.content)
    visitor_token, current_credits = read_visitor_cookie(config, request, project.slug)

    if payload.website.strip():
        sub_status = "pending" if cfg["require_approval"] else "approved"
        notice = "已入海，等待站长审核后漂向远方" if sub_status == "pending" else "漂流瓶已顺利入海，漂向远方"
        return JSONResponse(
            {
                "ok": True,
                "status": sub_status,
                "message": notice,
                "credits": current_credits,
                "max_credits": MAX_CREDITS,
            }
        )

    ip_hash = submissions.hash_ip(config, client_ip(request))
    if submissions.is_ip_banned(db, project_id=project.id, ip_hash=ip_hash):
        return api_error("当前无法投递漂流瓶", 403)

    cleaned_message = _MESSAGE_CONTROL_RE.sub("", payload.message.replace("\r\n", "\n").replace("\r", "\n"))
    message = cleaned_message.strip()
    if not message:
        return api_error("写点什么再把瓶子投进海里吧", 400)
    if len(message) > cfg["max_length"]:
        return api_error(f"内容不能超过 {cfg['max_length']} 字", 400)

    nickname = _NICKNAME_CONTROL_RE.sub("", payload.nickname).strip()[:32]
    if not cfg["allow_links"] and (
        submissions.contains_link(message) or (nickname and submissions.contains_link(nickname))
    ):
        return api_error("漂流瓶内容不支持包含网址或链接", 400)

    retry_after = submissions.check_submission_rate_limit(
        ip_hash,
        project.id,
        "throw",
        cfg["throw_limit_per_hour"],
        window_seconds=3600.0,
    )
    if retry_after is not None:
        return JSONResponse(
            {"ok": False, "error": "投递过于频繁，请稍后再试"},
            status_code=429,
            headers={"Retry-After": str(retry_after)},
        )

    if not visitor_token:
        visitor_token = secrets.token_urlsafe(16)
    sub_status = "pending" if cfg["require_approval"] else "approved"
    created = submissions.create_submission(
        db,
        project_id=project.id,
        plugin_id="bottle",
        payload={"message": message, "nickname": nickname},
        status=sub_status,
        ip_hash=ip_hash,
        author_token=visitor_token,
    )
    new_credits = min(current_credits + 1, MAX_CREDITS)
    approved_count = submissions.count_submissions(db, project_id=project.id, plugin_id="bottle")["approved"]
    notice = "已入海，等待站长审核后漂向远方" if sub_status == "pending" else "漂流瓶已顺利入海，漂向远方"
    response = JSONResponse(
        {
            "ok": True,
            "status": sub_status,
            "message": notice,
            "credits": new_credits,
            "max_credits": MAX_CREDITS,
            "approved_count": approved_count,
            "submission_id": created["id"],
        }
    )
    set_visitor_cookie(config, response, project.slug, visitor_token, new_credits)
    return response


@router.post("/api/projects/{slug}/bottle/pick")
def pick_bottle(
    request: Request,
    slug: str,
    db: DbSession,
) -> JSONResponse:
    require_same_origin(request)
    config = get_config(request)
    project, is_admin, error = _resolve_bottle_project(request, db, config, slug)
    if error is not None or project is None:
        return error or api_error("漂流瓶空间不存在", 404)

    ip_hash = submissions.hash_ip(config, client_ip(request))
    if submissions.is_ip_banned(db, project_id=project.id, ip_hash=ip_hash):
        return api_error("当前无法捞取漂流瓶", 403)

    cfg = load_bottle_config(project.content)
    visitor_token, current_credits = read_visitor_cookie(config, request, project.slug)
    needs_credit = bool(cfg["throw_to_pick"]) and not is_admin
    if needs_credit and current_credits < 1:
        return api_error("先投出一个漂流瓶，才能捞取一个哦", 400)

    retry_after = submissions.check_submission_rate_limit(
        ip_hash,
        project.id,
        "pick",
        cfg["pick_limit_per_hour"],
        window_seconds=3600.0,
    )
    if retry_after is not None:
        return JSONResponse(
            {"ok": False, "error": "捞取过于频繁，请稍后再试"},
            status_code=429,
            headers={"Retry-After": str(retry_after)},
        )

    picked = submissions.pick_random_submission(
        db,
        project_id=project.id,
        plugin_id="bottle",
        exclude_author_token=visitor_token,
        status="approved",
    )
    approved_count = submissions.count_submissions(db, project_id=project.id, plugin_id="bottle")["approved"]
    if picked is None:
        return JSONResponse(
            {
                "ok": True,
                "empty": True,
                "bottle": None,
                "credits": current_credits,
                "max_credits": MAX_CREDITS,
                "approved_count": approved_count,
                "message": "此刻海面风平浪静，暂时没有来自他人的漂流瓶，稍后再来试试吧",
            }
        )

    new_credits = max(0, current_credits - 1) if needs_credit else current_credits
    picked_payload = picked["payload"] if isinstance(picked["payload"], dict) else {}
    msg = str(picked_payload.get("message", ""))
    nickname = str(picked_payload.get("nickname", "")).strip()
    created_at = str(picked["created_at"])

    response = JSONResponse(
        {
            "ok": True,
            "empty": False,
            "bottle": {
                "id": picked["id"],
                "message": msg,
                "nickname": nickname,
                "created_at": created_at,
                "date": created_at[:10],
            },
            "credits": new_credits,
            "max_credits": MAX_CREDITS,
            "approved_count": approved_count,
        }
    )
    if visitor_token:
        set_visitor_cookie(config, response, project.slug, visitor_token, new_credits)
    return response
