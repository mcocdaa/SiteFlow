import io
import shutil
import stat
import zipfile
from pathlib import Path, PurePosixPath

from PIL import Image, ImageOps, UnidentifiedImageError

from app.config import Config


class InvalidUpload(ValueError):
    pass


def extract_site(source: Path, destination: Path, config: Config) -> str:
    try:
        with zipfile.ZipFile(source) as archive:
            entries = archive.infolist()
            if len(entries) > config.zip_entries:
                raise InvalidUpload("压缩包文件数量超出限制")
            total = 0
            paths: set[str] = set()
            for entry in entries:
                name = entry.filename
                path = PurePosixPath(name)
                mode = entry.external_attr >> 16
                if (
                    not name
                    or "\\" in name
                    or ":" in name
                    or "\x00" in name
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
                total += entry.file_size
                if total > config.extract_limit:
                    raise InvalidUpload("解压大小超出限制")
            written = 0
            for entry in entries:
                path = PurePosixPath(entry.filename)
                if any(part.startswith(".") or part == "__MACOSX" for part in path.parts):
                    continue
                target = destination.joinpath(*path.parts)
                if not target.resolve().is_relative_to(destination.resolve()):
                    raise InvalidUpload("压缩包包含不安全路径")
                if entry.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as incoming, target.open("xb") as outgoing:
                    while chunk := incoming.read(65536):
                        written += len(chunk)
                        if written > config.extract_limit:
                            raise InvalidUpload("解压大小超出限制")
                        outgoing.write(chunk)
        candidates = sorted(
            (p for p in destination.rglob("*") if p.is_file() and p.name.lower() == "index.html"),
            key=lambda p: (len(p.relative_to(destination).parts), p.as_posix()),
        )
        if not candidates:
            raise InvalidUpload("ZIP 中未找到 index.html")
        return candidates[0].relative_to(destination).as_posix()
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
