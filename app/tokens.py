import hashlib
import hmac
import json
import re
import secrets
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, cast

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

TOKEN_PREFIX = "sft_"
VALID_SCOPES: tuple[str, ...] = (
    "read",
    "posts:write",
    "content:write",
    "projects:write",
    "deploy:write",
    "submissions:write",
    "extensions:write",
    "admin",
)
MAX_TOKENS = 100

_VALID_SCOPE_SET = frozenset(VALID_SCOPES)
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_LAST_USED_THROTTLE_SECONDS = 60


class TokenError(ValueError):
    pass


@dataclass(frozen=True)
class AuthPrincipal:
    kind: Literal["session", "env_token", "db_token"]
    is_admin: bool
    scopes: frozenset[str]
    allowed_slugs: frozenset[str] | None
    token_id: int | None = None
    name: str = ""
    prefix: str = ""

    def has_scope(self, scope: str) -> bool:
        return self.is_admin or "admin" in self.scopes or scope in self.scopes

    def can_access_slugs(self, slugs: Iterable[str]) -> bool:
        return self.allowed_slugs is None or bool(set(slugs) & self.allowed_slugs)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def normalize_scopes(scopes: Collection[str]) -> list[str]:
    if isinstance(scopes, (str, bytes)):
        raise TokenError("权限范围必须为列表")
    result: list[str] = []
    seen: set[str] = set()
    for item in scopes:
        if not isinstance(item, str):
            raise TokenError("权限范围必须为字符串")
        scope = item.strip()
        if scope not in _VALID_SCOPE_SET:
            raise TokenError(f"无效的权限范围：{item}")
        if scope not in seen:
            seen.add(scope)
            result.append(scope)
    if not result:
        raise TokenError("至少需要指定一个权限范围")
    return result


def normalize_allowed_slugs(allowed_slugs: Collection[str] | None) -> list[str]:
    if allowed_slugs is None:
        return []
    if isinstance(allowed_slugs, (str, bytes)):
        raise TokenError("项目作用域必须为列表")
    result: list[str] = []
    seen: set[str] = set()
    for item in allowed_slugs:
        if not isinstance(item, str) or "\n" in item or "\r" in item:
            raise TokenError(f"无效的项目标识：{item}")
        slug = item.strip()
        if not _SLUG_RE.fullmatch(slug):
            raise TokenError(f"无效的项目标识：{item}")
        if slug not in seen:
            seen.add(slug)
            result.append(slug)
    return result


def _parse_iso_utc(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def normalize_expires_at(raw: str) -> str:
    if not isinstance(raw, str):
        raise TokenError("过期时间必须为字符串")
    cleaned = raw.strip()
    if not cleaned:
        return ""
    dt = _parse_iso_utc(cleaned)
    if dt is None:
        raise TokenError("过期时间格式无效，请使用 ISO-8601 格式")
    if dt <= datetime.now(UTC):
        raise TokenError("过期时间必须晚于当前时间")
    return dt.isoformat()


def _parse_json_str_list(raw: str) -> list[str]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, str)]


def _row_to_token(row: Any) -> dict[str, Any]:
    return {
        "id": int(row[0]),
        "name": str(row[1]),
        "prefix": str(row[2]),
        "scopes": _parse_json_str_list(str(row[3])),
        "allowed_slugs": _parse_json_str_list(str(row[4])),
        "created_at": str(row[5]),
        "last_used_at": str(row[6]),
        "expires_at": str(row[7]),
    }


def create_token(
    db: Session,
    *,
    name: str,
    scopes: Collection[str],
    allowed_slugs: Collection[str] | None = None,
    expires_at: str = "",
) -> tuple[dict[str, Any], str]:
    count_row = db.execute(text("SELECT COUNT(*) FROM api_tokens")).fetchone()
    count = int(count_row[0]) if count_row is not None else 0
    if count >= MAX_TOKENS:
        raise TokenError(f"API 令牌数量已达上限（最多 {MAX_TOKENS} 个）")

    if not isinstance(name, str):
        raise TokenError("令牌名称必须为字符串")
    cleaned_name = name.strip()
    if not 1 <= len(cleaned_name) <= 80:
        raise TokenError("令牌名称长度需在 1 到 80 个字符之间")

    norm_scopes = normalize_scopes(scopes)
    norm_slugs = normalize_allowed_slugs(allowed_slugs)
    norm_expires = normalize_expires_at(expires_at)

    raw = f"{TOKEN_PREFIX}{secrets.token_urlsafe(32)}"
    prefix = raw[:12]
    token_hash = hash_token(raw)
    created_at = datetime.now(UTC).isoformat()

    row = db.execute(
        text(
            """
            INSERT INTO api_tokens
                (name, prefix, token_hash, scopes, allowed_slugs, created_at, last_used_at, expires_at)
            VALUES
                (:name, :prefix, :token_hash, :scopes, :allowed_slugs, :created_at, '', :expires_at)
            RETURNING id, name, prefix, scopes, allowed_slugs, created_at, last_used_at, expires_at
            """
        ),
        {
            "name": cleaned_name,
            "prefix": prefix,
            "token_hash": token_hash,
            "scopes": json.dumps(norm_scopes, ensure_ascii=False),
            "allowed_slugs": json.dumps(norm_slugs, ensure_ascii=False),
            "created_at": created_at,
            "expires_at": norm_expires,
        },
    ).fetchone()
    db.commit()
    assert row is not None
    return _row_to_token(row), raw


def list_tokens(db: Session) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            SELECT id, name, prefix, scopes, allowed_slugs, created_at, last_used_at, expires_at
            FROM api_tokens
            ORDER BY created_at DESC, id DESC
            """
        )
    ).fetchall()
    return [_row_to_token(row) for row in rows]


def revoke_token(db: Session, token_id: int) -> bool:
    result = cast(
        CursorResult[Any],
        db.execute(text("DELETE FROM api_tokens WHERE id = :id"), {"id": token_id}),
    )
    db.commit()
    return (result.rowcount or 0) > 0


def verify_db_token(db: Session, raw_token: str) -> AuthPrincipal | None:
    if not raw_token or not isinstance(raw_token, str) or not raw_token.startswith(TOKEN_PREFIX):
        return None
    computed_hash = hash_token(raw_token)
    row = db.execute(
        text(
            """
            SELECT id, name, prefix, token_hash, scopes, allowed_slugs, last_used_at, expires_at
            FROM api_tokens
            WHERE token_hash = :token_hash
            """
        ),
        {"token_hash": computed_hash},
    ).fetchone()
    if row is None:
        return None
    stored_hash = str(row[3])
    if not hmac.compare_digest(computed_hash, stored_hash):
        return None

    now = datetime.now(UTC)
    expires_at = str(row[7])
    if expires_at:
        exp_dt = _parse_iso_utc(expires_at)
        if exp_dt is None or exp_dt <= now:
            return None

    token_id = int(row[0])
    last_used_at = str(row[6])
    should_touch = not last_used_at
    if not should_touch:
        last_dt = _parse_iso_utc(last_used_at)
        if last_dt is None or (now - last_dt).total_seconds() > _LAST_USED_THROTTLE_SECONDS:
            should_touch = True
    if should_touch:
        db.execute(
            text("UPDATE api_tokens SET last_used_at = :now WHERE id = :id"),
            {"now": now.isoformat(), "id": token_id},
        )
        db.commit()

    parsed_scopes = frozenset(s for s in _parse_json_str_list(str(row[4])) if s in _VALID_SCOPE_SET)
    parsed_slugs = _parse_json_str_list(str(row[5]))
    allowed_slugs: frozenset[str] | None = frozenset(parsed_slugs) if parsed_slugs else None
    is_admin = "admin" in parsed_scopes and allowed_slugs is None

    return AuthPrincipal(
        kind="db_token",
        is_admin=is_admin,
        scopes=parsed_scopes,
        allowed_slugs=allowed_slugs,
        token_id=token_id,
        name=str(row[1]),
        prefix=str(row[2]),
    )
