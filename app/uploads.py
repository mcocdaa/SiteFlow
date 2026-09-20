import io
import shutil
import stat
import zipfile
from pathlib import Path, PurePosixPath

from PIL import Image, ImageOps, UnidentifiedImageError

from app.config import Config


class InvalidUpload(ValueError):
    pass


MAX_EXPANSION_RATIO = 100


def decode_zip_name(name: str, flag_bits: int) -> str:
    """Smart transcoding for zip entries. CP437/GBK/UTF-8 tolerance for Windows zip files."""
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


def extract_site(source: Path, destination: Path, config: Config) -> str:
    try:
        archive_size = source.stat().st_size
        max_inodes = getattr(config, "zip_entries", 5000)
        with zipfile.ZipFile(source) as archive:
            entries = archive.infolist()
            if len(entries) > config.zip_entries:
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

                # Collect inodes (directories + files)
                curr = path
                while curr != PurePosixPath("."):
                    inodes.add(curr.as_posix())
                    curr = curr.parent

                # Check single file expansion ratio (> 100:1) for entries >= 1MB
                if entry.file_size > 1024 * 1024:
                    comp_size = max(entry.compress_size, 1)
                    if (entry.file_size / comp_size) > MAX_EXPANSION_RATIO:
                        raise InvalidUpload("压缩包单文件解压膨胀比过高（疑似解压炸弹）")

                total += entry.file_size
                if total > config.extract_limit:
                    raise InvalidUpload("解压大小超出限制")

            if len(inodes) > max_inodes:
                raise InvalidUpload("压缩包文件与目录总数超出 Inode 上限")

            # Check total archive expansion ratio (> 100:1)
            if archive_size > 0 and total > 1024 * 1024 and (total / archive_size) > MAX_EXPANSION_RATIO:
                raise InvalidUpload("压缩包解压膨胀比过高（疑似解压炸弹）")

            written = 0
            for entry in entries:
                decoded_name = decode_zip_name(entry.filename, entry.flag_bits)
                path = PurePosixPath(decoded_name.replace("\\", "/"))
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
                        if archive_size > 0 and written > 1024 * 1024 and (written / archive_size) > MAX_EXPANSION_RATIO:
                            raise InvalidUpload("压缩包解压膨胀比过高（疑似解压炸弹）")
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
