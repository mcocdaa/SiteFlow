import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

_TIMEOUT = 5.0
_HTML_LIMIT = 512 * 1024
_IMAGE_LIMIT = 5 * 1024 * 1024
_MAX_REDIRECTS = 3


@dataclass
class OpenGraph:
    title: str
    description: str
    image_url: str


def _is_public_ip(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return _is_public_ip(address.ipv4_mapped)
    return (
        address.is_global
        and not address.is_private
        and not address.is_loopback
        and not address.is_link_local
        and not address.is_multicast
        and not address.is_reserved
        and not address.is_unspecified
    )


def _is_blocked_hostname(host: str) -> bool:
    normalized = host.strip().lower().rstrip(".")
    return (
        not normalized
        or normalized == "localhost"
        or normalized.endswith((".localhost", ".local", ".internal"))
    )


def _safe_host(url: str) -> tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, str]:
    parsed = urlparse(url)
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if _is_blocked_hostname(host):
        raise ValueError(f"不安全的目标地址: {host or url}")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if not _is_public_ip(literal):
            raise ValueError(f"不安全的目标地址: {host}")
        return literal, host
    infos = socket.getaddrinfo(host, None)
    addresses = {ipaddress.ip_address(info[4][0]) for info in infos}
    if not addresses:
        raise ValueError(f"无法解析目标主机: {host}")
    for address in addresses:
        if not _is_public_ip(address):
            raise ValueError(f"不安全的目标地址: {host}")
    return addresses.pop(), host


def validate_public_host(url: str) -> str:
    raw = url if isinstance(url, str) else ""
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in raw):
        raise ValueError("目标地址包含非法控制字符")
    cleaned = raw.strip()
    if not cleaned:
        raise ValueError("目标地址不能为空")
    parsed = urlparse(cleaned)
    if parsed.scheme.lower() != "https":
        raise ValueError("仅支持 HTTPS 目标地址")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("目标地址不允许包含认证信息")
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if _is_blocked_hostname(host):
        raise ValueError(f"不安全的目标地址: {host or cleaned}")
    try:
        _, resolved_host = _safe_host(cleaned)
    except ValueError:
        raise
    except OSError as exc:
        raise ValueError(f"无法解析目标主机: {host}") from exc
    return resolved_host


def fetch_archive(
    url: str,
    *,
    max_bytes: int = 10 * 1024 * 1024,
    timeout: float = 15.0,
) -> bytes:
    current = url.strip() if isinstance(url, str) else ""
    for hop in range(_MAX_REDIRECTS + 1):
        validate_public_host(current)
        try:
            with httpx.stream(
                "GET",
                current,
                timeout=timeout,
                follow_redirects=False,
                headers={"User-Agent": "SiteFlow/1.0"},
            ) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    if hop >= _MAX_REDIRECTS:
                        raise ValueError("下载重定向次数过多")
                    location = response.headers.get("location", "").strip()
                    if not location:
                        raise ValueError("重定向响应缺少目标地址")
                    current = str(httpx.URL(current).join(location))
                    continue
                if response.status_code >= 400:
                    raise ValueError(f"下载失败（HTTP {response.status_code}）")
                content_length = response.headers.get("content-length")
                if content_length and content_length.isdigit() and int(content_length) > max_bytes:
                    raise ValueError("下载文件超过大小限制")
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes(chunk_size=65536):
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError("下载文件超过大小限制")
                    chunks.append(chunk)
                data = b"".join(chunks)
                if not data:
                    raise ValueError("下载内容为空")
                return data
        except ValueError:
            raise
        except httpx.TimeoutException as exc:
            raise ValueError("下载超时，请稍后重试") from exc
        except (httpx.HTTPError, OSError) as exc:
            raise ValueError("网络请求失败，无法下载目标文件") from exc
    raise ValueError("下载重定向次数过多")


def _stream_bytes(url: str, limit: int, *, allow_truncate: bool, depth: int = 0) -> tuple[bytes, str] | None:
    if depth >= _MAX_REDIRECTS:
        return None
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return None
    try:
        _safe_host(url)
    except (OSError, ValueError):
        return None
    try:
        with httpx.stream(
            "GET",
            url,
            timeout=_TIMEOUT,
            follow_redirects=False,
            headers={"User-Agent": "SiteFlow/1.0"},
        ) as response:
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("location", "")
                if not location:
                    return None
                next_url = str(httpx.URL(url).join(location))
                return _stream_bytes(next_url, limit, allow_truncate=allow_truncate, depth=depth + 1)
            response.raise_for_status()
            content_length = response.headers.get("content-length")
            if (
                not allow_truncate
                and content_length
                and content_length.isdigit()
                and int(content_length) > limit
            ):
                return None
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_bytes(chunk_size=65536):
                total += len(chunk)
                if total > limit:
                    if allow_truncate:
                        keep = limit - (total - len(chunk))
                        if keep > 0:
                            chunks.append(chunk[:keep])
                        break
                    return None
                chunks.append(chunk)
            return b"".join(chunks), url
    except (httpx.HTTPError, OSError):
        return None


def fetch_og(url: str, _depth: int = 0) -> OpenGraph | None:
    result = _stream_bytes(url, _HTML_LIMIT, allow_truncate=True, depth=_depth)
    if result is None:
        return None
    raw, final_url = result
    return parse_og(raw, final_url)


def fetch_image(url: str) -> bytes | None:
    result = _stream_bytes(url, _IMAGE_LIMIT, allow_truncate=False, depth=0)
    if result is None:
        return None
    content, _ = result
    if not content:
        return None
    return content


def parse_og(html: bytes, base_url: str) -> OpenGraph | None:
    soup = BeautifulSoup(html, "html.parser")

    def meta(property_name: str) -> str:
        tag = soup.find("meta", attrs={"property": property_name})
        content = tag.get("content") if tag else None
        return content.strip() if isinstance(content, str) else ""

    title = meta("og:title") or (soup.title.string.strip() if soup.title and soup.title.string else "")
    description = meta("og:description")
    raw_image = meta("og:image")
    image_url = urljoin(base_url, raw_image) if raw_image else ""
    return OpenGraph(title=title, description=description, image_url=image_url)
