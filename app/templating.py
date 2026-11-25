from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi.templating import Jinja2Templates

from app.svg_cover import generate_svg_cover

if TYPE_CHECKING:
    from app.extensions.mascot import MascotCharacterSpec

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATE_DIRS = [str(BASE_DIR / "templates")]
TEMPLATE_DIRS.extend(str(path) for path in sorted((BASE_DIR / "plugins").glob("*/templates")))

_STATIC_HASH_CACHE: dict[tuple[str, int, int], str] = {}


def static_url(path: str) -> str:
    cleaned = path.split("?", 1)[0].lstrip("/")
    rel_path = cleaned.removeprefix("static/")
    if not rel_path:
        return "/static/"
    try:
        root = STATIC_DIR.resolve()
        target = (root / rel_path).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            return f"/static/{rel_path}"
        stat = target.stat()
    except OSError:
        return f"/static/{rel_path}"
    key = (str(target), stat.st_mtime_ns, stat.st_size)
    digest = _STATIC_HASH_CACHE.get(key)
    if digest is None:
        try:
            digest = hashlib.sha256(target.read_bytes()).hexdigest()[:8]
        except OSError:
            return f"/static/{rel_path}"
        _STATIC_HASH_CACHE[key] = digest
    return f"/static/{rel_path}?v={digest}"


def mascot_spec(character: str) -> MascotCharacterSpec:
    from app.extensions.mascot import get_character_spec

    return get_character_spec(character)


templates = Jinja2Templates(directory=TEMPLATE_DIRS)
templates.env.globals["svg_cover"] = generate_svg_cover
templates.env.globals["static_url"] = static_url
templates.env.globals["mascot_spec"] = mascot_spec


def placeholder_hue(slug: str) -> int:
    return sum(slug.encode()) % 360
