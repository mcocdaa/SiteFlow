from pathlib import Path

from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIRS = [str(BASE_DIR / "templates")]
TEMPLATE_DIRS.extend(str(path) for path in sorted((BASE_DIR / "plugins").glob("*/templates")))

templates = Jinja2Templates(directory=TEMPLATE_DIRS)


def placeholder_hue(slug: str) -> int:
    return sum(slug.encode()) % 360
