import hashlib
import hmac
import json
import math
import re
import time
import unicodedata
from collections import defaultdict, deque
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.config import Config

VALID_STATUSES: tuple[str, ...] = ("pending", "approved", "rejected")

_IP_HASH_RE = re.compile(r"^[0-9a-f]{16,64}$")
_MAX_RATE_KEYS = 20_000
_rate_buckets: dict[tuple[str, int, str], deque[float]] = defaultdict(deque)

_ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u2060\ufeff\u00ad]")

_UNAMBIGUOUS_TLDS = (
    "com",
    "cn",
    "net",
    "org",
    "io",
    "co",
    "cc",
    "tv",
    "xyz",
    "top",
    "site",
    "online",
    "info",
    "biz",
    "app",
    "dev",
    "ai",
    "gg",
    "ly",
    "sh",
    "vc",
    "uk",
    "jp",
    "kr",
    "de",
    "fr",
    "ru",
    "tw",
    "hk",
    "mo",
    "sg",
    "au",
    "ca",
    "eu",
    "edu",
    "gov",
    "mil",
    "int",
    "pro",
    "vip",
    "club",
    "shop",
    "store",
    "tech",
    "cloud",
    "fun",
    "live",
    "life",
    "work",
    "blog",
    "link",
    "click",
    "icu",
    "buzz",
    "win",
    "bid",
    "pub",
    "ren",
    "wang",
    "xin",
    "ltd",
    "group",
    "team",
    "zone",
    "page",
    "bio",
    "fm",
    "ch",
    "nl",
    "se",
    "fi",
    "es",
    "pl",
    "br",
    "mx",
    "cz",
    "vn",
    "th",
    "ph",
    "tr",
    "ua",
    "kz",
    "su",
    "gl",
    "gd",
    "nu",
    "ws",
    "tk",
    "ml",
    "ga",
    "cf",
    "gq",
    "onion",
    "wiki",
)

_ALL_TLDS = _UNAMBIGUOUS_TLDS + (
    "me",
    "to",
    "so",
    "im",
    "in",
    "us",
    "am",
    "la",
    "be",
    "no",
    "it",
    "at",
    "id",
    "my",
    "ir",
    "by",
    "is",
    "bit",
)

_ALL_TLD_PATTERN = "|".join(sorted(set(_ALL_TLDS), key=len, reverse=True))
_UNAMBIGUOUS_TLD_PATTERN = "|".join(sorted(set(_UNAMBIGUOUS_TLDS), key=len, reverse=True))
_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"

_SCHEME_RE = re.compile(
    r"(?i)(?:h\s*t\s*t\s*p\s*s?|h\s*x\s*x\s*p\s*s?|f\s*t\s*p\s*s?|w\s*s\s*s?|t\s*g|w\s*e\s*i\s*x\s*i\s*n|f\s*i\s*l\s*e)\s*:\s*/\s*/"
    r"|\b(?:mailto|tel|javascript|vbscript|data)\s*:"
    r"|https?\s*\(\s*s\s*\)\s*:\s*/\s*/"
    r"|(?<![:\w])//[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.[a-z]{2,}"
)

_WWW_RE = re.compile(
    r"(?i)(?<![a-z0-9])w\s*w\s*w\s*(?:\.|。|·|•|・|∙|⋅|‧|﹒|\[\.\]|\(\.\)|\{\.\}|\[dot\]|\(dot\)|\{dot\})\s*[a-z0-9]"
)

_IPV4_RE = re.compile(r"(?<![0-9.])(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?![0-9.])")

_DOMAIN_ADJACENT_RE = re.compile(rf"(?i)(?<![a-z0-9_-])(?:{_LABEL}\.)+(?:{_ALL_TLD_PATTERN})(?![a-z0-9-])")

_OBF_DOT = r"(?:\[\s*\.\s*\]|\(\s*\.\s*\)|\{\s*\.\s*\}|\[\s*dot\s*\]|\(\s*dot\s*\)|\{\s*dot\s*\}|[·•・∙⋅‧﹒])"
_DOMAIN_OBF_RE = re.compile(
    rf"(?i)(?<![a-z0-9_-]){_LABEL}(?:\s*{_OBF_DOT}\s*{_LABEL})*\s*{_OBF_DOT}\s*(?:{_ALL_TLD_PATTERN})(?![a-z0-9-])"
)

_DOMAIN_WORD_DOT_RE = re.compile(
    rf"(?i)(?<![a-z0-9_-]){_LABEL}\s+(?:dot|点)\s+(?:{_ALL_TLD_PATTERN})(?![a-z0-9-])"
)

_DOMAIN_CJK_DOT_ADJ_RE = re.compile(
    rf"(?i)(?<![a-z0-9_-]){_LABEL}\s*。\s*(?:{_ALL_TLD_PATTERN})(?![a-z0-9-])"
)

_DOMAIN_SPACE_BEFORE_DOT_RE = re.compile(
    rf"(?i)(?<![a-z0-9_-]){_LABEL}\s+\.\s*(?:{_ALL_TLD_PATTERN})(?![a-z0-9-])"
)

_DOMAIN_SPACE_AFTER_DOT_RE = re.compile(
    rf"(?i)(?<![a-z0-9_-]){_LABEL}\.\s+(?:{_UNAMBIGUOUS_TLD_PATTERN})(?![a-z0-9-])"
)

_DOMAIN_SPACE_AFTER_PATH_RE = re.compile(rf"(?i)(?<![a-z0-9_-]){_LABEL}\.\s+(?:{_ALL_TLD_PATTERN})/[^\s]")


def hash_ip(config: Config, ip: str) -> str:
    raw = (ip or "unknown").strip()
    return hmac.new(config.secret.encode(), f"sub-ip:{raw}".encode(), hashlib.sha256).hexdigest()[:24]


def is_valid_ip_hash(value: str) -> bool:
    return bool(_IP_HASH_RE.match(value))


def reset_submission_rate_limits() -> None:
    _rate_buckets.clear()


def check_submission_rate_limit(
    ip_hash: str,
    project_id: int,
    action: str,
    limit: int,
    window_seconds: float = 3600.0,
) -> int | None:
    key = (ip_hash, project_id, action)
    now = time.monotonic()
    bucket = _rate_buckets.get(key)
    if bucket is not None:
        while bucket and now - bucket[0] >= window_seconds:
            bucket.popleft()
        if not bucket:
            _rate_buckets.pop(key, None)
            bucket = None
    effective_limit = max(1, int(limit))
    if bucket is not None and len(bucket) >= effective_limit:
        return max(1, math.ceil(window_seconds - (now - bucket[0])))
    if key not in _rate_buckets and len(_rate_buckets) >= _MAX_RATE_KEYS:
        _rate_buckets.pop(next(iter(_rate_buckets)), None)
    _rate_buckets[key].append(now)
    return None


def contains_link(raw_text: str) -> bool:
    if not raw_text:
        return False
    stripped = _ZERO_WIDTH_RE.sub("", raw_text)
    preserved = stripped.replace("\uff0e", "[.]").replace("\uff61", "[.]")
    norm = unicodedata.normalize("NFKC", preserved)
    if _SCHEME_RE.search(norm) or _WWW_RE.search(norm):
        return True
    for match in _IPV4_RE.finditer(norm):
        if all(0 <= int(part) <= 255 for part in match.groups()):
            return True
    if _DOMAIN_ADJACENT_RE.search(norm):
        return True
    if _DOMAIN_OBF_RE.search(norm):
        return True
    if _DOMAIN_WORD_DOT_RE.search(norm):
        return True
    if _DOMAIN_CJK_DOT_ADJ_RE.search(norm):
        return True
    if _DOMAIN_SPACE_BEFORE_DOT_RE.search(norm):
        return True
    if _DOMAIN_SPACE_AFTER_DOT_RE.search(norm):
        return True
    return bool(_DOMAIN_SPACE_AFTER_PATH_RE.search(norm))


def _row_to_submission(row: Any) -> dict[str, Any]:
    raw_payload = str(row[3])
    try:
        parsed_payload = json.loads(raw_payload)
    except json.JSONDecodeError:
        parsed_payload = {"raw": raw_payload}
    return {
        "id": int(row[0]),
        "project_id": int(row[1]),
        "plugin_id": str(row[2]),
        "payload": parsed_payload,
        "status": str(row[4]),
        "ip_hash": str(row[5]),
        "author_token": str(row[6]),
        "created_at": str(row[7]),
    }


def create_submission(
    db: Session,
    *,
    project_id: int,
    plugin_id: str,
    payload: dict[str, Any] | str,
    status: str = "pending",
    ip_hash: str,
    author_token: str = "",
) -> dict[str, Any]:
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid submission status: {status}")
    encoded = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    created_at = datetime.now(UTC).isoformat()
    result = db.execute(
        text(
            """
            INSERT INTO visitor_submissions
                (project_id, plugin_id, payload, status, ip_hash, author_token, created_at)
            VALUES
                (:project_id, :plugin_id, :payload, :status, :ip_hash, :author_token, :created_at)
            RETURNING id, project_id, plugin_id, payload, status, ip_hash, author_token, created_at
            """
        ),
        {
            "project_id": project_id,
            "plugin_id": plugin_id,
            "payload": encoded,
            "status": status,
            "ip_hash": ip_hash,
            "author_token": author_token,
            "created_at": created_at,
        },
    )
    row = result.fetchone()
    db.commit()
    assert row is not None
    return _row_to_submission(row)


def get_submission(
    db: Session,
    *,
    project_id: int,
    sub_id: int,
    plugin_id: str | None = None,
) -> dict[str, Any] | None:
    clauses = ["project_id = :project_id", "id = :sub_id"]
    params: dict[str, Any] = {"project_id": project_id, "sub_id": sub_id}
    if plugin_id is not None:
        clauses.append("plugin_id = :plugin_id")
        params["plugin_id"] = plugin_id
    where = " AND ".join(clauses)
    row = db.execute(
        text(
            f"SELECT id, project_id, plugin_id, payload, status, ip_hash, author_token, created_at "
            f"FROM visitor_submissions WHERE {where}"
        ),
        params,
    ).fetchone()
    return _row_to_submission(row) if row is not None else None


def list_submissions(
    db: Session,
    *,
    project_id: int,
    plugin_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    clauses = ["project_id = :project_id"]
    params: dict[str, Any] = {
        "project_id": project_id,
        "limit": max(1, min(limit, 500)),
        "offset": max(0, offset),
    }
    if plugin_id is not None:
        clauses.append("plugin_id = :plugin_id")
        params["plugin_id"] = plugin_id
    if status is not None:
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid submission status: {status}")
        clauses.append("status = :status")
        params["status"] = status
    where = " AND ".join(clauses)
    rows = db.execute(
        text(
            f"SELECT id, project_id, plugin_id, payload, status, ip_hash, author_token, created_at "
            f"FROM visitor_submissions WHERE {where} ORDER BY created_at DESC, id DESC "
            f"LIMIT :limit OFFSET :offset"
        ),
        params,
    ).fetchall()
    return [_row_to_submission(row) for row in rows]


def count_submissions(
    db: Session,
    *,
    project_id: int,
    plugin_id: str | None = None,
) -> dict[str, int]:
    clauses = ["project_id = :project_id"]
    params: dict[str, Any] = {"project_id": project_id}
    if plugin_id is not None:
        clauses.append("plugin_id = :plugin_id")
        params["plugin_id"] = plugin_id
    where = " AND ".join(clauses)
    rows = db.execute(
        text(f"SELECT status, COUNT(*) FROM visitor_submissions WHERE {where} GROUP BY status"),
        params,
    ).fetchall()
    counts = {"pending": 0, "approved": 0, "rejected": 0}
    for status_name, count in rows:
        if str(status_name) in counts:
            counts[str(status_name)] = int(count)
    counts["total"] = sum(counts.values())
    return counts


def pick_random_submission(
    db: Session,
    *,
    project_id: int,
    plugin_id: str,
    exclude_author_token: str = "",
    status: str = "approved",
) -> dict[str, Any] | None:
    clauses = ["project_id = :project_id", "plugin_id = :plugin_id", "status = :status"]
    params: dict[str, Any] = {
        "project_id": project_id,
        "plugin_id": plugin_id,
        "status": status,
    }
    if exclude_author_token:
        clauses.append("author_token != :exclude_author_token")
        params["exclude_author_token"] = exclude_author_token
    where = " AND ".join(clauses)
    row = db.execute(
        text(
            f"SELECT id, project_id, plugin_id, payload, status, ip_hash, author_token, created_at "
            f"FROM visitor_submissions WHERE {where} ORDER BY RANDOM() LIMIT 1"
        ),
        params,
    ).fetchone()
    return _row_to_submission(row) if row is not None else None


def set_submission_status(
    db: Session,
    *,
    project_id: int,
    sub_id: int,
    status: str,
    plugin_id: str | None = None,
) -> dict[str, Any] | None:
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid submission status: {status}")
    clauses = ["project_id = :project_id", "id = :sub_id"]
    params: dict[str, Any] = {"project_id": project_id, "sub_id": sub_id, "status": status}
    if plugin_id is not None:
        clauses.append("plugin_id = :plugin_id")
        params["plugin_id"] = plugin_id
    where = " AND ".join(clauses)
    result = cast(
        CursorResult[Any],
        db.execute(
            text(f"UPDATE visitor_submissions SET status = :status WHERE {where}"),
            params,
        ),
    )
    db.commit()
    if (result.rowcount or 0) <= 0:
        return None
    return get_submission(db, project_id=project_id, sub_id=sub_id, plugin_id=plugin_id)


def delete_submission(
    db: Session,
    *,
    project_id: int,
    sub_id: int,
    plugin_id: str | None = None,
) -> bool:
    clauses = ["project_id = :project_id", "id = :sub_id"]
    params: dict[str, Any] = {"project_id": project_id, "sub_id": sub_id}
    if plugin_id is not None:
        clauses.append("plugin_id = :plugin_id")
        params["plugin_id"] = plugin_id
    where = " AND ".join(clauses)
    result = cast(
        CursorResult[Any],
        db.execute(text(f"DELETE FROM visitor_submissions WHERE {where}"), params),
    )
    db.commit()
    return (result.rowcount or 0) > 0


def clear_submissions(
    db: Session,
    *,
    project_id: int,
    plugin_id: str | None = None,
    status: str | None = None,
) -> int:
    clauses = ["project_id = :project_id"]
    params: dict[str, Any] = {"project_id": project_id}
    if plugin_id is not None:
        clauses.append("plugin_id = :plugin_id")
        params["plugin_id"] = plugin_id
    if status is not None:
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid submission status: {status}")
        clauses.append("status = :status")
        params["status"] = status
    where = " AND ".join(clauses)
    result = cast(
        CursorResult[Any],
        db.execute(text(f"DELETE FROM visitor_submissions WHERE {where}"), params),
    )
    db.commit()
    return int(result.rowcount or 0)


def ban_ip_hash(db: Session, *, project_id: int, ip_hash: str) -> bool:
    if not is_valid_ip_hash(ip_hash):
        raise ValueError("无效的 IP 哈希格式")
    created_at = datetime.now(UTC).isoformat()
    db.execute(
        text(
            """
            INSERT INTO visitor_ip_bans (project_id, ip_hash, created_at)
            VALUES (:project_id, :ip_hash, :created_at)
            ON CONFLICT(project_id, ip_hash) DO NOTHING
            """
        ),
        {"project_id": project_id, "ip_hash": ip_hash, "created_at": created_at},
    )
    db.commit()
    return True


def unban_ip_hash(db: Session, *, project_id: int, ip_hash: str) -> bool:
    if not is_valid_ip_hash(ip_hash):
        return False
    result = cast(
        CursorResult[Any],
        db.execute(
            text("DELETE FROM visitor_ip_bans WHERE project_id = :project_id AND ip_hash = :ip_hash"),
            {"project_id": project_id, "ip_hash": ip_hash},
        ),
    )
    db.commit()
    return (result.rowcount or 0) > 0


def is_ip_banned(db: Session, *, project_id: int, ip_hash: str) -> bool:
    row = db.execute(
        text("SELECT 1 FROM visitor_ip_bans WHERE project_id = :project_id AND ip_hash = :ip_hash"),
        {"project_id": project_id, "ip_hash": ip_hash},
    ).fetchone()
    return row is not None


def list_banned_ips(db: Session, *, project_id: int) -> list[dict[str, str]]:
    rows = db.execute(
        text(
            "SELECT ip_hash, created_at FROM visitor_ip_bans "
            "WHERE project_id = :project_id ORDER BY created_at DESC"
        ),
        {"project_id": project_id},
    ).fetchall()
    return [{"ip_hash": str(row[0]), "created_at": str(row[1])} for row in rows]


def delete_project_submissions(
    db: Session,
    project_ids: int | Sequence[int],
    *,
    commit: bool = True,
) -> None:
    ids = [project_ids] if isinstance(project_ids, int) else list(project_ids)
    if not ids:
        return
    placeholders = ", ".join(f":id_{i}" for i in range(len(ids)))
    params = {f"id_{i}": pid for i, pid in enumerate(ids)}
    db.execute(text(f"DELETE FROM visitor_submissions WHERE project_id IN ({placeholders})"), params)
    db.execute(text(f"DELETE FROM visitor_ip_bans WHERE project_id IN ({placeholders})"), params)
    if commit:
        db.commit()
