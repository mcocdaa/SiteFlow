import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from typing import Any
from urllib.parse import urlparse

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import HTTPException, Request, Response, status
from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.config import Config

SESSION_COOKIE = "siteflow_session"
SESSION_MAX_AGE = 7 * 24 * 3600
_password_hasher = PasswordHasher()
_password_hash_cache: dict[str, str] = {}
_serializer: URLSafeTimedSerializer | None = None
_serializer_secret: str | None = None
_failed: dict[str, deque[float]] = defaultdict(deque)


def _get_serializer(config: Config) -> URLSafeTimedSerializer:
    global _serializer, _serializer_secret
    if _serializer is None or _serializer_secret != config.secret:
        _serializer = URLSafeTimedSerializer(config.secret, salt="siteflow-session")
        _serializer_secret = config.secret
    return _serializer


def password_version(config: Config) -> str:
    return hmac.new(config.secret.encode(), config.password.encode(), hashlib.sha256).hexdigest()


def verify_password(config: Config, password: str) -> bool:
    version = password_version(config)
    cached = _password_hash_cache.get(version)
    if cached is None:
        cached = _password_hasher.hash(config.password)
        _password_hash_cache[version] = cached
    try:
        return _password_hasher.verify(cached, password)
    except VerifyMismatchError:
        return False


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def apply_session(config: Config, response: Response, token: str, authenticated: bool = True) -> None:
    signed = _get_serializer(config).dumps(
        {"csrf": token, "admin": authenticated, "version": password_version(config)}
    )
    response.set_cookie(
        SESSION_COOKIE,
        signed,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=config.secure,
        path="/",
    )


def create_session(config: Config, response: Response, authenticated: bool = True) -> str:
    token = new_session_token()
    apply_session(config, response, token, authenticated)
    return token


def read_session(config: Config, request: Request) -> dict[str, Any] | None:
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    try:
        data = _get_serializer(config).loads(raw, max_age=SESSION_MAX_AGE)
    except BadSignature:
        return None
    if not isinstance(data, dict) or data.get("version") != password_version(config):
        return None
    if not isinstance(data.get("csrf"), str):
        return None
    return data


def clear_session(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def csrf_for(request: Request) -> str:
    session = read_session(request.app.state.config, request)
    existing = request.scope.get("siteflow_csrf") or (session or {}).get("csrf")
    if existing:
        return str(existing)
    token = secrets.token_urlsafe(24)
    request.scope["siteflow_csrf"] = token
    return token


def check_csrf(request: Request, submitted: str | None) -> bool:
    session = read_session(request.app.state.config, request)
    expected = (session or {}).get("csrf")
    if not expected or not submitted:
        return False
    return secrets.compare_digest(submitted, str(expected))


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def login_allowed(request: Request) -> bool:
    key = client_ip(request)
    now = time.time()
    window = _failed[key]
    while window and now - window[0] > 900:
        window.popleft()
    return len(window) < 5


def record_login_failure(request: Request) -> None:
    _failed[client_ip(request)].append(time.time())


def clear_login_failures(request: Request) -> None:
    _failed.pop(client_ip(request), None)


def require_admin(request: Request, config: Config) -> dict[str, Any]:
    data = read_session(config, request)
    if data is None or data.get("admin") is not True:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "需要登录")
    request.scope["siteflow_csrf"] = data.get("csrf")
    return data


def require_same_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    host = request.headers.get("host")
    if not origin or not host:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "缺少 Origin 或 Host")
    parsed = urlparse(origin)
    if parsed.netloc != host:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "跨站请求被拒绝")
