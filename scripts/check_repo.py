import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

_DICT_RE = re.compile(
    r"var\s+DICT\s*=\s*\{\s*zh:\s*(\{.*?\})\s*,\s*en:\s*(\{.*?\})\s*\};",
    re.DOTALL,
)
_TRAILING_COMMA_RE = re.compile(r",(\s*\})")
_EXTERNAL_TAG_RE = re.compile(
    r"<(?:script|link)\b[^>]+(?:src|href)=[\"']((?:https?:)?//[^\"']+)[\"']",
    re.IGNORECASE,
)
_STATIC_REF_RE = re.compile(r"(?:src|href)=[\"'](/static/[^\"'?#{}]+)[\"']")
_I18N_ATTR_RE = re.compile(r"data-i18n(?:-[a-z-]+)?=[\"']([^\"']+)[\"']")
_JS_I18N_CALL_RE = re.compile(r"(?:SiteFlowI18n\.t|\bt)\(\s*[\"']([a-z][a-z0-9_]*\.[a-z0-9_.-]+)[\"']")
_JS_FORBIDDEN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("debugger", re.compile(r"\bdebugger\b")),
    ("eval()", re.compile(r"\beval\s*\(")),
    ("new Function()", re.compile(r"\bnew\s+Function\s*\(")),
    ("document.write()", re.compile(r"\bdocument\.write\s*\(")),
)
_CDN_URL_RE = re.compile(
    r"(?:https?:)?//(?:cdn\.|unpkg\.com|cdn\.jsdelivr\.net|cdnjs\.cloudflare\.com|"
    r"fonts\.googleapis\.com|fonts\.gstatic\.com)",
    re.IGNORECASE,
)


def _parse_js_dict(raw: str, locale: str) -> tuple[dict[str, str], list[str]]:
    errors: list[str] = []
    duplicates: list[str] = []

    def hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                duplicates.append(key)
            result[key] = value
        return result

    cleaned = _TRAILING_COMMA_RE.sub(r"\1", raw)
    try:
        parsed = json.loads(cleaned, object_pairs_hook=hook)
    except json.JSONDecodeError as exc:
        return {}, [f"i18n.js {locale} JSON parse error: {exc}"]

    if not isinstance(parsed, dict):
        return {}, [f"i18n.js {locale} must be an object"]

    if duplicates:
        dup_list = ", ".join(sorted(set(duplicates)))
        errors.append(f"i18n.js {locale} has duplicate keys: {dup_list}")

    out: dict[str, str] = {}
    for key, value in parsed.items():
        if not isinstance(key, str) or not key.strip():
            errors.append(f"i18n.js {locale} has empty or non-string key")
            continue
        if not isinstance(value, str) or not value.strip():
            errors.append(f"i18n.js {locale} key {key!r} has empty or non-string value")
            continue
        out[key] = value
    return out, errors


def check_i18n_js(root: Path) -> tuple[set[str], list[str]]:
    path = root / "app" / "static" / "js" / "i18n.js"
    if not path.is_file():
        return set(), ["missing app/static/js/i18n.js"]

    text = path.read_text(encoding="utf-8")
    match = _DICT_RE.search(text)
    if not match:
        return set(), ["app/static/js/i18n.js missing expected DICT zh/en definition"]

    zh_dict, zh_errors = _parse_js_dict(match.group(1), "zh")
    en_dict, en_errors = _parse_js_dict(match.group(2), "en")
    errors = [*zh_errors, *en_errors]

    zh_keys = set(zh_dict)
    en_keys = set(en_dict)
    missing_in_en = sorted(zh_keys - en_keys)
    extra_in_en = sorted(en_keys - zh_keys)
    if missing_in_en:
        errors.append(f"i18n.js en missing keys ({len(missing_in_en)}): {', '.join(missing_in_en[:10])}")
    if extra_in_en:
        errors.append(f"i18n.js en extra keys ({len(extra_in_en)}): {', '.join(extra_in_en[:10])}")
    if not zh_keys:
        errors.append("i18n.js zh dictionary is empty")
    return zh_keys & en_keys, errors


def _read_requirements(path: Path) -> tuple[list[str], list[str]]:
    lines: list[str] = []
    directives: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-"):
            directives.append(line)
        else:
            lines.append(line)
    return lines, directives


def _find_duplicates(items: list[str]) -> list[str]:
    seen: set[str] = set()
    dups: set[str] = set()
    for item in items:
        if item in seen:
            dups.add(item)
        seen.add(item)
    return sorted(dups)


def check_dependencies(root: Path) -> tuple[tuple[int, int], list[str]]:
    errors: list[str] = []
    pyproject_path = root / "pyproject.toml"
    req_path = root / "requirements.txt"
    req_dev_path = root / "requirements-dev.txt"

    if not pyproject_path.is_file():
        return (0, 0), ["missing pyproject.toml"]
    if not req_path.is_file():
        return (0, 0), ["missing requirements.txt"]

    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    project = data.get("project", {})
    raw_deps = project.get("dependencies", [])
    if not isinstance(raw_deps, list) or not all(isinstance(x, str) for x in raw_deps):
        return (0, 0), ["pyproject.toml [project].dependencies must be a string list"]
    pyproject_deps = [x.strip() for x in raw_deps if x.strip()]

    req_deps, _ = _read_requirements(req_path)
    for label, entries in (("pyproject.toml", pyproject_deps), ("requirements.txt", req_deps)):
        dups = _find_duplicates(entries)
        if dups:
            errors.append(f"{label} contains duplicate dependencies: {', '.join(dups)}")

    missing_in_req = sorted(set(pyproject_deps) - set(req_deps))
    extra_in_req = sorted(set(req_deps) - set(pyproject_deps))
    if missing_in_req:
        errors.append(f"requirements.txt missing dependencies: {', '.join(missing_in_req)}")
    if extra_in_req:
        errors.append(f"requirements.txt has extra dependencies: {', '.join(extra_in_req)}")

    dev_count = 0
    opt_deps = project.get("optional-dependencies", {})
    raw_dev = opt_deps.get("dev", []) if isinstance(opt_deps, dict) else []
    if req_dev_path.is_file() and isinstance(raw_dev, list) and all(isinstance(x, str) for x in raw_dev):
        pyproject_dev = [x.strip() for x in raw_dev if x.strip()]
        dev_count = len(pyproject_dev)
        req_dev_deps, req_dev_directives = _read_requirements(req_dev_path)
        if "-r requirements.txt" not in req_dev_directives:
            errors.append("requirements-dev.txt must include '-r requirements.txt'")
        missing_dev = sorted(set(pyproject_dev) - set(req_dev_deps))
        extra_dev = sorted(set(req_dev_deps) - set(pyproject_dev))
        if missing_dev:
            errors.append(f"requirements-dev.txt missing dev dependencies: {', '.join(missing_dev)}")
        if extra_dev:
            errors.append(f"requirements-dev.txt has extra dev dependencies: {', '.join(extra_dev)}")

    return (len(pyproject_deps), dev_count), errors


def check_templates_and_js(root: Path, i18n_keys: set[str]) -> tuple[tuple[int, int], list[str]]:
    errors: list[str] = []
    template_files = sorted(
        list((root / "app" / "templates").rglob("*.html")) + list((root / "app" / "plugins").rglob("*.html"))
    )
    if not template_files:
        errors.append("no HTML templates found under app/templates or app/plugins")

    for tpl in template_files:
        rel = tpl.relative_to(root).as_posix()
        try:
            content = tpl.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            errors.append(f"{rel}: invalid UTF-8 ({exc})")
            continue
        if not content.strip():
            errors.append(f"{rel}: template file is empty")
            continue

        for ext_match in _EXTERNAL_TAG_RE.finditer(content):
            errors.append(f"{rel}: forbidden external script/link asset {ext_match.group(1)}")

        for static_match in _STATIC_REF_RE.finditer(content):
            asset_rel = static_match.group(1).lstrip("/")
            if not (root / "app" / asset_rel).is_file():
                errors.append(f"{rel}: missing static asset /{asset_rel}")

        if i18n_keys:
            for attr_match in _I18N_ATTR_RE.finditer(content):
                key = attr_match.group(1).strip()
                if not key or "{{" in key or "{%" in key:
                    continue
                if key not in i18n_keys:
                    errors.append(f"{rel}: unknown i18n key {key!r}")

    js_files = sorted((root / "app" / "static" / "js").glob("*.js"))
    if not js_files:
        errors.append("no JS files found under app/static/js")

    for js_file in js_files:
        rel = js_file.relative_to(root).as_posix()
        try:
            content = js_file.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            errors.append(f"{rel}: invalid UTF-8 ({exc})")
            continue
        if not content.strip():
            errors.append(f"{rel}: JS file is empty")
            continue

        for label, pattern in _JS_FORBIDDEN_PATTERNS:
            if pattern.search(content):
                errors.append(f"{rel}: forbidden construct {label}")

        cdn_match = _CDN_URL_RE.search(content)
        if cdn_match:
            errors.append(f"{rel}: forbidden external CDN URL {cdn_match.group(0)}")

        if i18n_keys:
            for call_match in _JS_I18N_CALL_RE.finditer(content):
                key = call_match.group(1)
                if key.endswith((".", "_")):
                    continue
                if key not in i18n_keys:
                    errors.append(f"{rel}: unknown i18n key {key!r}")

    return (len(template_files), len(js_files)), errors


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    i18n_keys, i18n_errors = check_i18n_js(root)
    (dep_count, dev_count), dep_errors = check_dependencies(root)
    (tpl_count, js_count), asset_errors = check_templates_and_js(root, i18n_keys)

    errors = [*i18n_errors, *dep_errors, *asset_errors]
    if errors:
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        return 1

    print(
        f"check_repo: OK (i18n={len(i18n_keys)} keys, deps={dep_count}+{dev_count}, "
        f"templates={tpl_count}, js={js_count})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
