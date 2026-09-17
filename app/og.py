import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

_TIMEOUT = 5.0
_HTML_LIMIT = 512 * 1024
_IMAGE_LIMIT = 5 * 1024 * 1024


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


def fetch_og(url: str) -> OpenGraph | None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return None
    try:
        _safe_host(url)
    except (OSError, ValueError):
        return None
    try:
        response = httpx.get(url, timeout=_TIMEOUT, follow_redirects=False, headers={"User-Agent": "SiteFlow/1.0"})
        if response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get("location", "")
            if location:
                return fetch_og(str(httpx.URL(url).join(location)))
            return None
        response.raise_for_status()
        content = response.content[:_HTML_LIMIT]
    except (httpx.HTTPError, OSError):
        return None
    return parse_og(content, url)


def parse_og(html: bytes, base_url: str) -> OpenGraph | None:
    soup = BeautifulSoup(html, "html.parser")
    def meta(property_name: str) -> str:
        tag = soup.find("meta", attrs={"property": property_name})
        content = tag.get("content") if tag else None
        return content.strip() if isinstance(content, str) else ""

    title = meta("og:title") or (soup.title.string.strip() if soup.title and soup.title.string else "")
    description = meta("og:description")
    image_url = meta("og:image")
    return OpenGraph(title=title, description=description, image_url=image_url)
