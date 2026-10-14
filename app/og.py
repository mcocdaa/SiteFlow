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


def _safe_host(url: str) -> tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, str]:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    infos = socket.getaddrinfo(host, None)
    addresses = {ipaddress.ip_address(info[4][0]) for info in infos}
    for address in addresses:
        if not address.is_global:
            raise ValueError(f"不安全的目标地址: {host}")
    return addresses.pop(), host


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
