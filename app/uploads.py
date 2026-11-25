import io
import math
import re
import secrets
import shutil
import stat
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path, PurePosixPath

from PIL import Image, ImageOps, UnidentifiedImageError

from app.config import Config


class InvalidUpload(ValueError):
    pass


UploadError = InvalidUpload

MAX_EXPANSION_RATIO = 100
MAX_SVG_BYTES = 256 * 1024
MAX_SVG_ELEMENTS = 500
MAX_SVG_DEPTH = 20
_SVG_NS = "http://www.w3.org/2000/svg"
_XML_DECL_RE = re.compile(r"^\s*<\?xml(?:\s+[^?]*)?\?>", re.IGNORECASE)
_SVG_FORBIDDEN_SYNTAX_RE = re.compile(
    r"<!(?:DOCTYPE|ENTITY|ELEMENT|ATTLIST|\[CDATA\[)|<\?xml-stylesheet|<\?",
    re.IGNORECASE,
)
_SVG_FORBIDDEN_TAGS = frozenset(
    {
        "script",
        "foreignobject",
        "iframe",
        "object",
        "embed",
        "audio",
        "video",
        "image",
        "use",
        "a",
        "style",
        "handler",
        "set",
    }
)
_SVG_ALLOWED_TAGS: dict[str, str] = {
    "svg": "svg",
    "g": "g",
    "path": "path",
    "circle": "circle",
    "ellipse": "ellipse",
    "rect": "rect",
    "line": "line",
    "polyline": "polyline",
    "polygon": "polygon",
    "defs": "defs",
    "lineargradient": "linearGradient",
    "radialgradient": "radialGradient",
    "stop": "stop",
    "clippath": "clipPath",
    "mask": "mask",
    "title": "title",
    "desc": "desc",
}
_SVG_ALLOWED_ATTRS: dict[str, str] = {
    "viewbox": "viewBox",
    "width": "width",
    "height": "height",
    "preserveaspectratio": "preserveAspectRatio",
    "x": "x",
    "y": "y",
    "x1": "x1",
    "y1": "y1",
    "x2": "x2",
    "y2": "y2",
    "cx": "cx",
    "cy": "cy",
    "r": "r",
    "rx": "rx",
    "ry": "ry",
    "d": "d",
    "points": "points",
    "transform": "transform",
    "id": "id",
    "fill": "fill",
    "fill-opacity": "fill-opacity",
    "fill-rule": "fill-rule",
    "stroke": "stroke",
    "stroke-width": "stroke-width",
    "stroke-linecap": "stroke-linecap",
    "stroke-linejoin": "stroke-linejoin",
    "stroke-miterlimit": "stroke-miterlimit",
    "stroke-dasharray": "stroke-dasharray",
    "stroke-dashoffset": "stroke-dashoffset",
    "stroke-opacity": "stroke-opacity",
    "opacity": "opacity",
    "stop-color": "stop-color",
    "stop-opacity": "stop-opacity",
    "offset": "offset",
    "gradientunits": "gradientUnits",
    "gradienttransform": "gradientTransform",
    "spreadmethod": "spreadMethod",
    "clip-path": "clip-path",
    "mask": "mask",
    "clip-rule": "clip-rule",
}
_SVG_DANGEROUS_VALUE_RE = re.compile(
    r"(?:javascript|vbscript|data|http|https)\s*:|expression\s*\(",
    re.IGNORECASE,
)
_SVG_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,63}$")
_SVG_HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_SVG_FUNC_COLOR_RE = re.compile(
    r"^(?:rgb|rgba|hsl|hsla)\(\s*[0-9.%+-]+(?:\s*[,/\s]\s*[0-9.%+-]+){2,3}\s*\)$",
    re.IGNORECASE,
)
_SVG_URL_REF_RE = re.compile(r"^url\(\s*#([A-Za-z_][A-Za-z0-9_-]{0,63})\s*\)$")
_SVG_TRANSFORM_RE = re.compile(
    r"^(?:\s*(?:matrix|translate|scale|rotate|skewX|skewY)\(\s*[0-9eE.+,\s-]+\s*\)\s*)+$"
)
_SVG_DIM_RE = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)(?:px)?\s*$", re.IGNORECASE)
_SVG_NAMED_COLORS = frozenset(
    {
        "aliceblue",
        "antiquewhite",
        "aqua",
        "aquamarine",
        "azure",
        "beige",
        "bisque",
        "black",
        "blanchedalmond",
        "blue",
        "blueviolet",
        "brown",
        "burlywood",
        "cadetblue",
        "chartreuse",
        "chocolate",
        "coral",
        "cornflowerblue",
        "cornsilk",
        "crimson",
        "currentcolor",
        "cyan",
        "darkblue",
        "darkcyan",
        "darkgoldenrod",
        "darkgray",
        "darkgreen",
        "darkgrey",
        "darkkhaki",
        "darkmagenta",
        "darkolivegreen",
        "darkorange",
        "darkorchid",
        "darkred",
        "darksalmon",
        "darkseagreen",
        "darkslateblue",
        "darkslategray",
        "darkslategrey",
        "darkturquoise",
        "darkviolet",
        "deeppink",
        "deepskyblue",
        "dimgray",
        "dimgrey",
        "dodgerblue",
        "firebrick",
        "floralwhite",
        "forestgreen",
        "fuchsia",
        "gainsboro",
        "ghostwhite",
        "gold",
        "goldenrod",
        "gray",
        "green",
        "greenyellow",
        "grey",
        "honeydew",
        "hotpink",
        "indianred",
        "indigo",
        "ivory",
        "khaki",
        "lavender",
        "lavenderblush",
        "lawngreen",
        "lemonchiffon",
        "lightblue",
        "lightcoral",
        "lightcyan",
        "lightgoldenrodyellow",
        "lightgray",
        "lightgreen",
        "lightgrey",
        "lightpink",
        "lightsalmon",
        "lightseagreen",
        "lightskyblue",
        "lightslategray",
        "lightslategrey",
        "lightsteelblue",
        "lightyellow",
        "lime",
        "limegreen",
        "linen",
        "magenta",
        "maroon",
        "mediumaquamarine",
        "mediumblue",
        "mediumorchid",
        "mediumpurple",
        "mediumseagreen",
        "mediumslateblue",
        "mediumspringgreen",
        "mediumturquoise",
        "mediumvioletred",
        "midnightblue",
        "mintcream",
        "mistyrose",
        "moccasin",
        "navajowhite",
        "navy",
        "none",
        "oldlace",
        "olive",
        "olivedrab",
        "orange",
        "orangered",
        "orchid",
        "palegoldenrod",
        "palegreen",
        "paleturquoise",
        "palevioletred",
        "papayawhip",
        "peachpuff",
        "peru",
        "pink",
        "plum",
        "powderblue",
        "purple",
        "rebeccapurple",
        "red",
        "rosybrown",
        "royalblue",
        "saddlebrown",
        "salmon",
        "sandybrown",
        "seagreen",
        "seashell",
        "sienna",
        "silver",
        "skyblue",
        "slateblue",
        "slategray",
        "slategrey",
        "snow",
        "springgreen",
        "steelblue",
        "tan",
        "teal",
        "thistle",
        "tomato",
        "transparent",
        "turquoise",
        "violet",
        "wheat",
        "white",
        "whitesmoke",
        "yellow",
        "yellowgreen",
    }
)


def _split_xml_name(name: str) -> tuple[str, str]:
    if name.startswith("{"):
        end = name.find("}")
        if end != -1:
            return name[1:end], name[end + 1 :]
    return "", name


def _parse_viewbox(raw: str) -> str:
    tokens = re.split(r"[\s,]+", raw.strip())
    if len(tokens) != 4:
        raise InvalidUpload("SVG viewBox 格式不正确")
    nums: list[float] = []
    for token in tokens:
        try:
            num = float(token)
        except ValueError as exc:
            raise InvalidUpload("SVG viewBox 必须为有效数字") from exc
        if not math.isfinite(num):
            raise InvalidUpload("SVG viewBox 必须为有限数字")
        nums.append(num)
    if nums[2] <= 0 or nums[3] <= 0:
        raise InvalidUpload("SVG viewBox 宽高必须大于 0")
    return " ".join(f"{n:g}" for n in nums)


def _validate_paint_attr(attr_name: str, value: str, referenced_ids: set[str]) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise InvalidUpload(f"SVG 属性 {attr_name} 不能为空")
    lowered = cleaned.lower()
    if attr_name in ("clip-path", "mask"):
        if lowered == "none":
            return "none"
        match = _SVG_URL_REF_RE.match(cleaned)
        if not match:
            raise InvalidUpload(f"SVG 属性 {attr_name} 仅允许 none 或内部 url(#id)")
        referenced_ids.add(match.group(1))
        return f"url(#{match.group(1)})"
    if lowered in _SVG_NAMED_COLORS or _SVG_HEX_COLOR_RE.match(cleaned) or _SVG_FUNC_COLOR_RE.match(cleaned):
        return cleaned
    if attr_name in ("fill", "stroke"):
        match = _SVG_URL_REF_RE.match(cleaned)
        if match:
            referenced_ids.add(match.group(1))
            return f"url(#{match.group(1)})"
    raise InvalidUpload(f"SVG 属性 {attr_name} 包含不受支持的颜色或引用")


def sanitize_svg(raw: bytes) -> bytes:
    if not raw or len(raw) > MAX_SVG_BYTES:
        raise InvalidUpload("SVG 文件为空或超过 256KB 限制")
    if b"\x00" in raw:
        raise InvalidUpload("SVG 文件包含非法字节")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InvalidUpload("SVG 文件必须是有效的 UTF-8 编码") from exc
    text = text.removeprefix("\ufeff")
    text = _XML_DECL_RE.sub("", text, count=1).strip()
    if not text:
        raise InvalidUpload("SVG 文件内容为空")
    if _SVG_FORBIDDEN_SYNTAX_RE.search(text):
        raise InvalidUpload("SVG 包含不允许的 XML 声明或处理指令")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise InvalidUpload("SVG 格式无效，无法解析") from exc

    root_ns, root_local = _split_xml_name(root.tag)
    if root_ns not in ("", _SVG_NS) or root_local.lower() != "svg":
        raise InvalidUpload("SVG 根节点必须是 <svg>")

    defined_ids: set[str] = set()
    referenced_ids: set[str] = set()
    element_count = 0

    def walk(node: ET.Element, depth: int) -> ET.Element | None:
        nonlocal element_count
        if depth > MAX_SVG_DEPTH:
            raise InvalidUpload("SVG 嵌套层级超出限制")
        ns, local = _split_xml_name(node.tag)
        lowered = local.lower()
        if lowered in _SVG_FORBIDDEN_TAGS or lowered.startswith("animate"):
            raise InvalidUpload(f"SVG 包含不允许的元素 <{local}>")
        if ns not in ("", _SVG_NS) or lowered == "metadata":
            return None
        canonical_tag = _SVG_ALLOWED_TAGS.get(lowered)
        if canonical_tag is None:
            raise InvalidUpload(f"SVG 包含不受支持的元素 <{local}>")
        element_count += 1
        if element_count > MAX_SVG_ELEMENTS:
            raise InvalidUpload("SVG 元素数量超出限制")

        clean_attrs: dict[str, str] = {}
        for attr_key, attr_val in node.attrib.items():
            attr_ns, attr_local = _split_xml_name(attr_key)
            attr_lower = attr_local.lower()
            if attr_lower.startswith("on") or attr_lower in ("style", "href"):
                raise InvalidUpload(f"SVG 包含不允许的属性 {attr_local}")
            compact_val = re.sub(r"[\x00-\x20\x7f]+", "", attr_val)
            if _SVG_DANGEROUS_VALUE_RE.search(compact_val):
                raise InvalidUpload(f"SVG 属性 {attr_local} 包含不安全协议或表达式")
            if attr_ns:
                continue
            canonical_attr = _SVG_ALLOWED_ATTRS.get(attr_lower)
            if canonical_attr is None:
                continue
            cleaned_val = attr_val.strip()
            if canonical_attr == "id":
                if not _SVG_ID_RE.match(cleaned_val) or cleaned_val in defined_ids:
                    raise InvalidUpload("SVG 包含非法或重复的 id 属性")
                defined_ids.add(cleaned_val)
                clean_attrs["id"] = cleaned_val
            elif canonical_attr == "viewBox":
                clean_attrs["viewBox"] = _parse_viewbox(cleaned_val)
            elif canonical_attr in ("fill", "stroke", "stop-color", "clip-path", "mask"):
                clean_attrs[canonical_attr] = _validate_paint_attr(
                    canonical_attr, cleaned_val, referenced_ids
                )
            elif canonical_attr in ("transform", "gradientTransform"):
                if cleaned_val and not _SVG_TRANSFORM_RE.match(cleaned_val):
                    raise InvalidUpload(f"SVG 属性 {canonical_attr} 格式不受支持")
                if cleaned_val:
                    clean_attrs[canonical_attr] = cleaned_val
            else:
                clean_attrs[canonical_attr] = cleaned_val

        clean_el = ET.Element(canonical_tag, clean_attrs)
        if canonical_tag in ("title", "desc") and node.text:
            clean_el.text = node.text.strip()[:200]
        for child in node:
            sanitized_child = walk(child, depth + 1)
            if sanitized_child is not None:
                clean_el.append(sanitized_child)
        return clean_el

    clean_root = walk(root, 1)
    if clean_root is None:
        raise InvalidUpload("SVG 内容无效")
    if not referenced_ids.issubset(defined_ids):
        raise InvalidUpload("SVG 引用了不存在的内部标识")
    if "viewBox" not in clean_root.attrib:
        w_match = _SVG_DIM_RE.match(clean_root.attrib.get("width", ""))
        h_match = _SVG_DIM_RE.match(clean_root.attrib.get("height", ""))
        if w_match and h_match:
            w_val = float(w_match.group(1))
            h_val = float(h_match.group(1))
            if w_val > 0 and h_val > 0:
                clean_root.attrib["viewBox"] = f"0 0 {w_val:g} {h_val:g}"
        if "viewBox" not in clean_root.attrib:
            clean_root.attrib["viewBox"] = "0 0 100 100"
    clean_root.attrib["xmlns"] = _SVG_NS
    return ET.tostring(clean_root, encoding="utf-8", xml_declaration=False)


def decode_zip_name(name: str, flag_bits: int) -> str:
    if not (flag_bits & 0x800):
        try:
            raw_bytes = name.encode("cp437")
            for enc in ("utf-8", "gbk", "gb18030"):
                try:
                    return raw_bytes.decode(enc)
                except UnicodeDecodeError:
                    continue
            return raw_bytes.decode("cp437", errors="replace")
        except UnicodeEncodeError:
            return name

    try:
        raw_bytes = name.encode("cp437")
        for enc in ("gbk", "gb18030"):
            try:
                candidate = raw_bytes.decode(enc)
                if any("\u4e00" <= ch <= "\u9fff" for ch in candidate):
                    return candidate
            except UnicodeDecodeError:
                continue
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass

    return name


def _extract_zip_archive(
    archive: zipfile.ZipFile,
    archive_size: int,
    destination: Path,
    *,
    max_entries: int,
    max_extract_bytes: int,
    max_ratio: int,
    ratio_min_bytes: int,
) -> Path:
    entries = archive.infolist()
    if len(entries) > max_entries:
        raise InvalidUpload("压缩包文件数量超出限制")
    total = 0
    paths: set[str] = set()
    inodes: set[str] = set()
    for entry in entries:
        decoded_name = decode_zip_name(entry.filename, entry.flag_bits)
        normalized_name = decoded_name.replace("\\", "/")
        path = PurePosixPath(normalized_name)
        mode = entry.external_attr >> 16
        if (
            not normalized_name
            or ":" in normalized_name
            or "\x00" in normalized_name
            or path.is_absolute()
            or ".." in path.parts
            or stat.S_ISLNK(mode)
            or entry.flag_bits & 1
        ):
            raise InvalidUpload("压缩包包含不安全路径、符号链接或加密文件")
        if any(part.startswith(".") or part == "__MACOSX" for part in path.parts):
            continue
        if path.as_posix() in paths:
            raise InvalidUpload("压缩包包含重复路径")
        paths.add(path.as_posix())

        curr = path
        while curr != PurePosixPath("."):
            inodes.add(curr.as_posix())
            curr = curr.parent

        if entry.file_size >= ratio_min_bytes:
            comp_size = max(entry.compress_size, 1)
            if (entry.file_size / comp_size) > max_ratio:
                raise InvalidUpload("压缩包单文件解压膨胀比过高（疑似解压炸弹）")

        total += entry.file_size
        if total > max_extract_bytes:
            raise InvalidUpload("解压大小超出限制")

    if len(inodes) > max_entries:
        raise InvalidUpload("压缩包文件与目录总数超出 Inode 上限")

    if archive_size > 0 and total >= ratio_min_bytes and (total / archive_size) > max_ratio:
        raise InvalidUpload("压缩包解压膨胀比过高（疑似解压炸弹）")

    destination.mkdir(parents=True, exist_ok=True)
    dest_root = destination.resolve()
    written = 0
    for entry in entries:
        decoded_name = decode_zip_name(entry.filename, entry.flag_bits)
        path = PurePosixPath(decoded_name.replace("\\", "/"))
        if any(part.startswith(".") or part == "__MACOSX" for part in path.parts):
            continue
        target = destination.joinpath(*path.parts)
        if not target.resolve().is_relative_to(dest_root):
            raise InvalidUpload("压缩包包含不安全路径")
        if entry.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(entry) as incoming, target.open("xb") as outgoing:
            while chunk := incoming.read(65536):
                written += len(chunk)
                if written > max_extract_bytes:
                    raise InvalidUpload("解压大小超出限制")
                if archive_size > 0 and written >= ratio_min_bytes and (written / archive_size) > max_ratio:
                    raise InvalidUpload("压缩包解压膨胀比过高（疑似解压炸弹）")
                outgoing.write(chunk)
    return destination


def extract_zip_tree(
    archive: bytes,
    dest: Path,
    *,
    max_entries: int = 300,
    max_extract_bytes: int = 20 * 1024 * 1024,
    max_ratio: int = MAX_EXPANSION_RATIO,
) -> Path:
    if not archive:
        raise InvalidUpload("压缩包不能为空")
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as zf:
            return _extract_zip_archive(
                zf,
                len(archive),
                dest,
                max_entries=max_entries,
                max_extract_bytes=max_extract_bytes,
                max_ratio=max_ratio,
                ratio_min_bytes=16 * 1024,
            )
    except InvalidUpload:
        raise
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError, OSError) as exc:
        raise InvalidUpload("压缩包损坏或格式不支持") from exc


def extract_site(source: Path, destination: Path, config: Config) -> str:
    try:
        archive_size = source.stat().st_size
        max_inodes = getattr(config, "zip_entries", 5000)
        with zipfile.ZipFile(source) as archive:
            _extract_zip_archive(
                archive,
                archive_size,
                destination,
                max_entries=max_inodes,
                max_extract_bytes=config.extract_limit,
                max_ratio=MAX_EXPANSION_RATIO,
                ratio_min_bytes=1024 * 1024 + 1,
            )
        candidates = sorted(
            (p for p in destination.rglob("*") if p.is_file() and p.name.lower() == "index.html"),
            key=lambda p: (len(p.relative_to(destination).parts), p.as_posix()),
        )
        if not candidates:
            raise InvalidUpload("ZIP 中未找到 index.html")
        return candidates[0].relative_to(destination).as_posix()
    except InvalidUpload:
        raise
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError, OSError) as exc:
        raise InvalidUpload("压缩包损坏或格式不支持") from exc


def make_cover(raw: bytes, destination: Path) -> None:
    if len(raw) > 10 * 1024 * 1024:
        raise InvalidUpload("封面不能超过 10MB")
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.format not in {"JPEG", "PNG", "WEBP", "GIF"} or image.width * image.height > 25_000_000:
                raise InvalidUpload("图片格式不支持或尺寸过大")
            converted = ImageOps.exif_transpose(image).convert("RGB")
            converted.thumbnail((1600, 1600))
            converted.save(destination, "WEBP", quality=82)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise InvalidUpload("无法读取封面图片") from exc


def make_avatar_webp(raw: bytes, dest: Path) -> None:
    if len(raw) > 10 * 1024 * 1024:
        raise InvalidUpload("头像不能超过 10MB")
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if (
                image.format not in {"JPEG", "PNG", "WEBP", "GIF"}
                or image.width <= 0
                or image.height <= 0
                or image.width * image.height > 25_000_000
            ):
                raise InvalidUpload("头像格式不支持或尺寸过大")
            converted = ImageOps.exif_transpose(image).convert("RGBA")
            converted.thumbnail((512, 512))
            converted.save(dest, "WEBP", quality=85)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise InvalidUpload("无法读取头像图片") from exc


def remove_tree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def save_cover(config: Config, raw: bytes, slug: str) -> str:
    destination = config.data / "media" / "covers" / f"{slug}.webp"
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        make_cover(raw, destination)
    except InvalidUpload:
        return ""
    return destination.name


BLOG_MEDIA_KINDS = {"cover", "bg", "avatar"}
PROJECT_MEDIA_KINDS = {"cover", "bg", "avatar"}
MAX_BLOG_MEDIA_FILES = 500
_BLOG_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_PROJECT_MEDIA_URL_RE = re.compile(
    r"^/media/(blog|ext)/([a-z0-9][a-z0-9_-]{0,63})/((?:[a-z0-9][a-z0-9_-]{0,63}\.webp|avatar-[0-9a-f]{16}\.svg))$"
)
_BLOG_MEDIA_URL_RE = _PROJECT_MEDIA_URL_RE


def _is_svg_upload(data: bytes, filename: str, content_type: str) -> bool:
    if filename.lower().endswith(".svg"):
        return True
    if content_type.lower().split(";", 1)[0].strip() == "image/svg+xml":
        return True
    head = data[:512].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    return head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in head)


def save_project_media(
    config: Config,
    project_type: str,
    slug: str,
    kind: str,
    data: bytes,
    *,
    filename: str = "",
    content_type: str = "",
) -> str:
    if kind not in PROJECT_MEDIA_KINDS:
        raise InvalidUpload("不支持的媒体类型")
    if not _BLOG_SLUG_RE.match(slug):
        raise InvalidUpload("无效的项目标识")
    namespace = "blog" if project_type == "blog" else "ext"
    folder = config.data / "media" / namespace / slug
    folder.mkdir(parents=True, exist_ok=True)
    existing_count = sum(1 for entry in folder.iterdir() if entry.is_file())
    if existing_count >= MAX_BLOG_MEDIA_FILES:
        raise InvalidUpload("项目媒体文件数量已达上限")
    if kind == "avatar":
        if _is_svg_upload(data, filename, content_type):
            cleaned_svg = sanitize_svg(data)
            name = f"avatar-{secrets.token_hex(8)}.svg"
            (folder / name).write_bytes(cleaned_svg)
        else:
            name = f"avatar-{secrets.token_hex(8)}.webp"
            make_avatar_webp(data, folder / name)
        return f"/media/{namespace}/{slug}/{name}"
    name = f"{kind}-{secrets.token_hex(8)}.webp"
    make_cover(data, folder / name)
    return f"/media/{namespace}/{slug}/{name}"


def save_blog_media(
    config: Config,
    project_slug: str,
    kind: str,
    raw: bytes,
    *,
    filename: str = "",
    content_type: str = "",
) -> str:
    return save_project_media(
        config,
        "blog",
        project_slug,
        kind,
        raw,
        filename=filename,
        content_type=content_type,
    )


def delete_project_media_url(config: Config, slug: str, url: str) -> bool:
    match = _PROJECT_MEDIA_URL_RE.match(url.strip())
    if not match or match.group(2) != slug:
        return False
    folder = (config.data / "media" / match.group(1) / slug).resolve()
    target = (folder / match.group(3)).resolve()
    if not target.is_relative_to(folder) or not target.is_file():
        return False
    target.unlink(missing_ok=True)
    return True


delete_blog_media_url = delete_project_media_url
