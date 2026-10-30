"""Read source color hints and normalize preview pixels without changing files."""

from io import BytesIO
from pathlib import Path
import struct

from PySide6.QtGui import QColorSpace, QImage


COLOR_MODES = (("srgb", "sRGB"), ("display_p3", "Display P3"), ("unmanaged", "未管理"))


def valid_color_mode(mode):
    return mode if isinstance(mode, str) and mode in {key for key, _title in COLOR_MODES} else "srgb"


def space_from_tags(color_space=None, interop=None):
    """Uncalibrated alone does not identify Adobe RGB; DCF R03 does."""
    if color_space in (1, "1"):
        return QColorSpace(QColorSpace.NamedColorSpace.SRgb)
    if color_space in (2, "2") or interop == "R03":
        return QColorSpace(QColorSpace.NamedColorSpace.AdobeRgb)
    if interop == "R98":
        return QColorSpace(QColorSpace.NamedColorSpace.SRgb)
    return None


def _tiff_space(stream):
    """Follow only classic TIFF's EXIF/Interop pointers, with bounded reads."""
    stream.seek(0)
    header = stream.read(8)
    if len(header) != 8 or header[:2] not in (b"II", b"MM"):
        return None
    endian = "<" if header[:2] == b"II" else ">"
    if struct.unpack(endian + "H", header[2:4])[0] != 42:
        return None
    pending = [(struct.unpack(endian + "I", header[4:])[0], "root")]
    visited = set()
    color_space = interop = None
    while pending and len(visited) < 4:
        offset, group = pending.pop()
        if offset in visited or not 8 <= offset <= 32 * 1024 * 1024:
            continue
        visited.add(offset)
        stream.seek(offset)
        count_data = stream.read(2)
        if len(count_data) != 2:
            continue
        count = struct.unpack(endian + "H", count_data)[0]
        if count > 4096:
            continue
        entries = stream.read(count * 12)
        if len(entries) != count * 12:
            continue
        for index in range(count):
            entry = entries[index * 12:(index + 1) * 12]
            tag, kind, components = struct.unpack(endian + "HHI", entry[:8])
            if tag in (0x8769, 0xA005) and kind == 4 and components == 1:
                pending.append((struct.unpack(endian + "I", entry[8:])[0],
                                "exif" if tag == 0x8769 else "interop"))
            elif tag == 0xA001 and kind == 3 and components == 1:
                color_space = struct.unpack(endian + "H", entry[8:10])[0]
            elif group == "interop" and tag == 1 and kind == 2 and components in (3, 4):
                interop = entry[8:8 + components].rstrip(b"\0").decode("ascii", errors="ignore")
    return space_from_tags(color_space, interop)


def _jpeg_space(stream):
    if stream.read(2) != b"\xff\xd8":
        return None
    for _ in range(256):
        if stream.read(1) != b"\xff":
            break
        marker = stream.read(1)
        for _ in range(16):
            if marker != b"\xff":
                break
            marker = stream.read(1)
        if not marker or marker in (b"\xda", b"\xd9"):
            break
        if marker == b"\x01" or 0xD0 <= marker[0] <= 0xD8:
            continue
        length_data = stream.read(2)
        if len(length_data) != 2:
            break
        length = struct.unpack(">H", length_data)[0] - 2
        if length < 0:
            break
        if marker == b"\xe1":
            payload = stream.read(length)
            if len(payload) != length:
                break
            if payload.startswith(b"Exif\0\0"):
                space = _tiff_space(BytesIO(payload[6:]))
                if space is not None:
                    return space
        else:
            # Skip compressed pixels and unrelated metadata rather than loading the file.
            stream.seek(length, 1)
    return None


def file_color_space(path: Path):
    try:
        with path.open("rb") as stream:
            jpeg = stream.read(2) == b"\xff\xd8"
            stream.seek(0)
            return _jpeg_space(stream) if jpeg else _tiff_space(stream)
    except (OSError, ValueError, struct.error):
        return None


def assign_source_space(image: QImage, *, jpeg=None, path=None, fallback=None) -> QImage:
    """Keep a valid embedded ICC; otherwise use explicit hints before assuming sRGB."""
    if image.isNull() or image.colorSpace().isValid():
        return image
    space = _jpeg_space(BytesIO(jpeg)) if jpeg is not None else None
    if space is None:
        space = fallback
    if space is None and path is not None:
        space = file_color_space(path)
    if space is None:
        space = QColorSpace(QColorSpace.NamedColorSpace.SRgb)
    result = QImage(image)
    result.setColorSpace(space)
    return result


def to_srgb(image: QImage) -> QImage:
    return _convert(image, QColorSpace(QColorSpace.NamedColorSpace.SRgb))


def convert_preview(image: QImage, mode="srgb") -> QImage:
    mode = valid_color_mode(mode)
    if mode == "unmanaged":
        return image
    target = (QColorSpace.NamedColorSpace.DisplayP3 if mode == "display_p3"
              else QColorSpace.NamedColorSpace.SRgb)
    return _convert(image, QColorSpace(target))


def _convert(image: QImage, target: QColorSpace) -> QImage:
    if image.isNull():
        return image
    source = assign_source_space(image)
    if source.colorSpace() == target:
        return source
    image_format = QImage.Format.Format_RGBA8888 if source.hasAlphaChannel() else QImage.Format.Format_RGB32
    result = source.convertedToColorSpace(target, image_format)
    if result.isNull():
        # Unsupported or incompatible profiles must not turn a readable preview blank.
        result = QImage(image)
        result.setColorSpace(target)
    return result
