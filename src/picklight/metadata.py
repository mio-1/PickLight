"""Read and update only XMP rating fields while preserving photo pixel data."""

from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Event
import json
import os
import shutil
import struct
import subprocess
import xml.etree.ElementTree as ET

from picklight.library import PhotoPair
from picklight.file_access import locked_paths, photo_files
from picklight.paths import resource_root


XMP_HEADER = b"http://ns.adobe.com/xap/1.0/\x00"
XMP_NS = "http://ns.adobe.com/xap/1.0/"
RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
ET.register_namespace("x", "adobe:ns:meta/")
ET.register_namespace("rdf", RDF_NS)
ET.register_namespace("xmp", XMP_NS)


class MetadataError(Exception):
    pass


_UNSET = object()


def _exiftool_path() -> Path:
    override = os.environ.get("PICKLIGHT_EXIFTOOL")
    if override and Path(override).is_file():
        return Path(override)
    root = resource_root()
    for candidate in (root / "exiftool" / "exiftool.exe",
                      root / "vendor" / "exiftool" / "exiftool.exe"):
        if candidate.is_file():
            return candidate
    system = shutil.which("exiftool")
    if system:
        return Path(system)
    raise MetadataError("DNG 星级需要 ExifTool。请先运行 tools/setup-exiftool.ps1。")


def _run_exiftool(arguments: list[str], *, strict: bool = True) -> bytes:
    # UTF-8 argfile on stdin avoids mangling non-ASCII Windows file names.
    payload = ("\n".join(arguments) + "\n").encode("utf-8")
    environment = os.environ.copy()
    environment.update(LANG="C", LC_ALL="C", LC_CTYPE="C")
    result = subprocess.run(
        [str(_exiftool_path()), "-charset", "filename=utf8", "-@", "-"],
        input=payload, capture_output=True, env=environment,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        timeout=90,
    )
    if result.returncode and strict:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise MetadataError(detail or "ExifTool 操作失败")
    return result.stdout


@locked_paths(lambda paths: paths)
def read_dng_ratings(paths: list[Path]) -> list[int | None]:
    if not paths:
        return []
    try:
        output = _run_exiftool(["-j", "-n", "-XMP-xmp:Rating", *map(str, paths)])
        entries = json.loads(output.decode("utf-8", errors="replace"))
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise MetadataError(f"无法读取 DNG 星级：{exc}") from exc
    if len(entries) != len(paths):
        raise MetadataError("DNG 星级读取结果数量不一致")
    result = []
    for entry in entries:
        if "Error" in entry:
            raise MetadataError(str(entry["Error"]))
        value = entry.get("Rating")
        result.append(value if isinstance(value, int) and 0 <= value <= 5 else None)
    return result


PHOTO_DETAIL_FIELDS = (
    "Model", "LensModel", "FocalLength", "FNumber", "ExposureTime",
    "ISO", "DateTimeOriginal", "ImageWidth", "ImageHeight", "Orientation", "Software",
    "Description", "ImageDescription", "Caption-Abstract", "Keywords", "Subject",
    "GPSLatitude", "GPSLongitude", "Country", "City",
)


@locked_paths(lambda path: [path])
def read_photo_details(path: Path) -> dict:
    """Read capture fields for the inspector without changing the photo."""
    try:
        output = _run_exiftool(["-j", "-n", *[f"-{field}" for field in PHOTO_DETAIL_FIELDS], str(path)])
        entries = json.loads(output.decode("utf-8", errors="replace"))
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise MetadataError(f"无法读取拍摄信息：{exc}") from exc
    if not entries or "Error" in entries[0]:
        raise MetadataError(str(entries[0].get("Error", "没有拍摄信息")) if entries else "没有拍摄信息")
    return entries[0]


def read_photo_details_many(paths: list[Path], stop_event: Event | None = None) -> dict[str, dict]:
    """Read capture fields in batches, optionally stopping between batches."""
    details: dict[str, dict] = {}
    for start in range(0, len(paths), 100):
        if stop_event is not None and stop_event.is_set():
            break
        batch = paths[start:start + 100]
        try:
            with photo_files(batch):
                output = _run_exiftool(
                    ["-j", "-n", *[f"-{field}" for field in PHOTO_DETAIL_FIELDS],
                     *map(str, batch)], strict=False)
            entries = json.loads(output.decode("utf-8", errors="replace"))
        except (OSError, ValueError, subprocess.TimeoutExpired, MetadataError):
            continue
        if len(entries) != len(batch):
            continue
        for path, entry in zip(batch, entries):
            if isinstance(entry, dict) and "Error" not in entry:
                details[str(path)] = entry
    return details


@locked_paths(lambda path, stars: [path])
def write_dng_rating(path: Path, stars: int) -> None:
    try:
        _run_exiftool(["-overwrite_original", "-P", f"-XMP-xmp:Rating={stars}", str(path)])
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MetadataError(f"无法写入 DNG 星级：{exc}") from exc


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("wb", dir=path.parent, prefix=f".{path.name}.",
                            suffix=".tmp", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _xmp_root(data: bytes | None) -> ET.Element:
    if data:
        try:
            return ET.fromstring(data)
        except ET.ParseError as exc:
            raise MetadataError("现有 XMP 无法解析，已停止写入以避免覆盖") from exc
    return ET.Element("{adobe:ns:meta/}xmpmeta")


def _description(root: ET.Element) -> ET.Element:
    rdf = root.find(f".//{{{RDF_NS}}}RDF")
    if rdf is None:
        rdf = ET.SubElement(root, f"{{{RDF_NS}}}RDF")
    desc = rdf.find(f"{{{RDF_NS}}}Description")
    if desc is None:
        desc = ET.SubElement(rdf, f"{{{RDF_NS}}}Description")
        desc.set(f"{{{RDF_NS}}}about", "")
    return desc


def _rating_from_xmp(data: bytes | None) -> int | None:
    if not data:
        return None
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return None
    for desc in root.iter(f"{{{RDF_NS}}}Description"):
        value = desc.get(f"{{{XMP_NS}}}Rating")
        if value is None:
            rating = desc.find(f"{{{XMP_NS}}}Rating")
            value = rating.text if rating is not None else None
        if value is not None:
            try:
                number = int(value)
                return number if 0 <= number <= 5 else None
            except ValueError:
                return None
    return None


def _set_rating(data: bytes | None, stars: int) -> bytes:
    root = _xmp_root(data)
    descriptions = list(root.iter(f"{{{RDF_NS}}}Description"))
    if not descriptions:
        descriptions = [_description(root)]
    for desc in descriptions:
        desc.attrib.pop(f"{{{XMP_NS}}}Rating", None)
        for rating in desc.findall(f"{{{XMP_NS}}}Rating"):
            desc.remove(rating)
    descriptions[0].set(f"{{{XMP_NS}}}Rating", str(stars))
    return ET.tostring(root, encoding="utf-8", xml_declaration=False)


def _jpeg_segments(data: bytes):
    if not data.startswith(b"\xff\xd8"):
        raise MetadataError("文件不是有效的 JPEG")
    pos = 2
    while pos < len(data):
        start = pos
        if data[pos] != 0xFF:
            raise MetadataError("JPEG 段结构无效")
        while pos < len(data) and data[pos] == 0xFF:
            pos += 1
        if pos >= len(data):
            raise MetadataError("JPEG 文件不完整")
        marker = data[pos]
        pos += 1
        if marker in (0xDA, 0xD9):
            yield marker, start, len(data), None
            return
        if marker in (0x01,) or 0xD0 <= marker <= 0xD7:
            yield marker, start, pos, None
            continue
        if pos + 2 > len(data):
            raise MetadataError("JPEG 段长度无效")
        length = struct.unpack_from(">H", data, pos)[0]
        if length < 2 or pos + length > len(data):
            raise MetadataError("JPEG 段长度无效")
        payload = data[pos + 2:pos + length]
        pos += length
        yield marker, start, pos, payload


def _jpg_xmp(data: bytes) -> bytes | None:
    for marker, _, _, payload in _jpeg_segments(data):
        if marker == 0xE1 and payload and payload.startswith(XMP_HEADER):
            return payload[len(XMP_HEADER):]
    return None


@locked_paths(lambda path: [path])
def read_jpg_rating(path: Path) -> int | None:
    # Ratings live before the compressed image scan. Reading only JPEG headers
    # keeps a thousand-photo library scan independent of photo file size.
    with path.open("rb") as stream:
        if stream.read(2) != b"\xff\xd8":
            raise MetadataError("文件不是有效的 JPEG")
        while True:
            prefix = stream.read(1)
            if not prefix:
                raise MetadataError("JPEG 文件不完整")
            if prefix != b"\xff":
                raise MetadataError("JPEG 段结构无效")
            marker = stream.read(1)
            while marker == b"\xff":
                marker = stream.read(1)
            if not marker:
                raise MetadataError("JPEG 文件不完整")
            code = marker[0]
            if code in (0xDA, 0xD9):
                return None
            if code == 0x01 or 0xD0 <= code <= 0xD7:
                continue
            length_bytes = stream.read(2)
            if len(length_bytes) != 2:
                raise MetadataError("JPEG 段长度无效")
            length = struct.unpack(">H", length_bytes)[0]
            if length < 2:
                raise MetadataError("JPEG 段长度无效")
            payload = stream.read(length - 2)
            if len(payload) != length - 2:
                raise MetadataError("JPEG 文件不完整")
            if code == 0xE1 and payload.startswith(XMP_HEADER):
                return _rating_from_xmp(payload[len(XMP_HEADER):])


@locked_paths(lambda path: [path.with_suffix(".xmp"), path])
def read_raw_rating(path: Path) -> int | None:
    sidecar = path.with_suffix(".xmp")
    if sidecar.exists():
        rating = _rating_from_xmp(sidecar.read_bytes())
        if rating is not None:
            return rating
    if path.suffix.casefold() == ".dng":
        return read_dng_ratings([path])[0]
    return None


@locked_paths(lambda pair, dng_rating=_UNSET: [path for path in
              (pair.jpg, pair.raw, pair.raw.with_suffix(".xmp") if pair.raw else None)
              if path is not None])
def read_pair_rating(pair: PhotoPair, dng_rating: object = _UNSET) -> int:
    # An existing JPEG rating is authoritative, including an explicit zero.
    if pair.jpg:
        rating = read_jpg_rating(pair.jpg)
        if rating is not None:
            return rating
    if pair.raw:
        if pair.raw.suffix.casefold() == ".dng" and dng_rating is not _UNSET:
            sidecar = pair.raw.with_suffix(".xmp")
            sidecar_rating = _rating_from_xmp(sidecar.read_bytes()) if sidecar.exists() else None
            rating = sidecar_rating if sidecar_rating is not None else dng_rating
        else:
            rating = read_raw_rating(pair.raw)
        if rating is not None:
            return int(rating)
    return 0


@locked_paths(lambda path, stars: [path])
def write_jpg_rating(path: Path, stars: int) -> None:
    data = path.read_bytes()
    xmp = _set_rating(_jpg_xmp(data), stars)
    payload = XMP_HEADER + xmp
    if len(payload) + 2 > 65535:
        raise MetadataError("XMP 内容超过 JPEG 单段容量，未修改照片")
    segment = b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload
    sections = []
    replaced = False
    for marker, start, end, existing in _jpeg_segments(data):
        if marker == 0xE1 and existing and existing.startswith(XMP_HEADER):
            if not replaced:
                sections.append(segment)
                replaced = True
        elif marker == 0xDA:
            if not replaced:
                sections.append(segment)
                replaced = True
            sections.append(data[start:])
            break
        else:
            sections.append(data[start:end])
    if not replaced:
        raise MetadataError("无法在 JPEG 中找到可写入的元数据位置")
    _atomic_write(path, data[:2] + b"".join(sections))


@locked_paths(lambda path, stars: [path, path.with_suffix(".xmp")])
def write_raw_rating(path: Path, stars: int) -> None:
    sidecar = path.with_suffix(".xmp")
    if path.suffix.casefold() == ".dng":
        write_dng_rating(path, stars)
        if not sidecar.exists():
            return
    current = sidecar.read_bytes() if sidecar.exists() else None
    _atomic_write(sidecar, _set_rating(current, stars))


@locked_paths(lambda pair, stars: [path for path in
              (pair.jpg, pair.raw, pair.raw.with_suffix(".xmp") if pair.raw else None)
              if path is not None])
def write_pair_rating(pair: PhotoPair, stars: int) -> None:
    if not 0 <= stars <= 5:
        raise ValueError("星级必须在 0 到 5 之间")
    if pair.jpg:
        write_jpg_rating(pair.jpg, stars)
    if pair.raw:
        write_raw_rating(pair.raw, stars)
