"""Decode previews off the UI thread with a small in-memory cache."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import subprocess

from PySide6.QtCore import QObject, QSize, Signal
from PySide6.QtGui import QColorSpace, QImage, QImageReader, QTransform
import rawpy

from picklight.file_access import photo_files
from picklight.loading import CachedLoader
from picklight.metadata import MetadataError, _run_exiftool
from picklight.color_management import assign_source_space, convert_preview, space_from_tags, to_srgb, valid_color_mode


def _orient_raw_thumbnail(image: QImage, flip: int) -> QImage:
    """Embedded pixels are unrotated; LibRaw flip uses dcraw's 0..7 mapping."""
    if flip in (3, 5, 6):
        return image.transformed(QTransform().rotate({3: 180, 5: -90, 6: 90}[flip]))
    if flip in (1, 2):
        return image.mirrored(flip == 1, flip == 2)
    if flip in (4, 7):
        return image.transformed(QTransform().rotate(90)).mirrored(flip == 4, flip == 7)
    return image


def _libraw_image(path: Path) -> QImage:
    with rawpy.imread(str(path)) as raw:
        try:
            thumb = raw.extract_thumb()
            if thumb.format == rawpy.ThumbFormat.JPEG:
                image = QImage.fromData(thumb.data)
                if not image.isNull():
                    image = assign_source_space(image, jpeg=thumb.data, path=path)
                    return _orient_raw_thumbnail(image, raw.sizes.flip)
            elif thumb.format == rawpy.ThumbFormat.BITMAP:
                array = thumb.data
                h, w, channels = array.shape
                if channels not in (3, 4) or array.dtype.itemsize != 1:
                    raise ValueError("Unsupported embedded bitmap")
                fmt = QImage.Format.Format_RGB888 if channels == 3 else QImage.Format.Format_RGBA8888
                image = QImage(array.data, w, h, array.strides[0], fmt).copy()
                image = assign_source_space(image, path=path)
                return _orient_raw_thumbnail(image, raw.sizes.flip)
        except (rawpy.LibRawError, ValueError):
            pass
        # LibRaw applies orientation here; only extracted thumbnails need our transform.
        array = raw.postprocess(half_size=True, output_bps=8, no_auto_bright=True,
                               output_color=rawpy.ColorSpace.sRGB, gamma=(2.4, 12.92))
        h, w, _ = array.shape
        image = QImage(array.data, w, h, array.strides[0], QImage.Format.Format_RGB888).copy()
        image.setColorSpace(QColorSpace(QColorSpace.NamedColorSpace.SRgb))
        return image


def _exiftool_raw_image(path: Path) -> QImage:
    """Recover camera-rendered JPEGs even when LibRaw cannot decode the sensor data."""
    for tag in ("JpgFromRaw", "PreviewImage", "ThumbnailImage"):
        data = _run_exiftool(["-b", f"-{tag}", str(path)], strict=False)
        image = QImage.fromData(data)
        if image.isNull():
            continue
        # Embedded JPEG pixels often lack their own EXIF orientation; use the RAW tag.
        try:
            entries = json.loads(_run_exiftool(["-j", "-n", "-Orientation", "-EXIF:ColorSpace",
                                               "-InteropIndex", str(path)], strict=False))
            details = entries[0] if isinstance(entries[0], dict) else {}
        except (MetadataError, OSError, ValueError, TypeError, IndexError, KeyError, subprocess.TimeoutExpired):
            details = {}
        try:
            orientation = int(details.get("Orientation", 1))
        except (TypeError, ValueError):
            orientation = 1
        image = assign_source_space(image, jpeg=data, path=path,
                                    fallback=space_from_tags(details.get("ColorSpace"),
                                                             details.get("InteropIndex")))
        flip = {1: 0, 2: 1, 3: 3, 4: 2, 5: 4, 6: 6, 7: 7, 8: 5}.get(orientation, 0)
        return _orient_raw_thumbnail(image, flip)
    raise ValueError("没有可用的内嵌预览")


def _raw_image(path: Path) -> QImage:
    try:
        return _libraw_image(path)
    except (rawpy.LibRawError, OSError, ValueError) as raw_error:
        try:
            return _exiftool_raw_image(path)
        except (MetadataError, OSError, ValueError, subprocess.TimeoutExpired):
            if isinstance(raw_error, rawpy.LibRawFileUnsupportedError):
                message = "当前版本暂不支持此相机或 RAW 压缩模式，且未找到可用预览"
            else:
                message = "无法读取 RAW，文件可能不完整、已损坏或使用暂不支持的编码"
            raise ValueError(f"{path.name}：{message}") from raw_error


def decode(path: Path, width: int, color_mode="srgb") -> QImage:
    with photo_files([path]):
        if path.suffix.casefold() in {".jpg", ".jpeg"}:
            reader = QImageReader(str(path))
            try:
                reader.setAutoTransform(True)
                size = reader.size()
                if size.isValid() and size.width() > width:
                    reader.setScaledSize(QSize(width, max(1, round(size.height() * width / size.width()))))
                image = reader.read()
            finally:
                # QImageReader owns a file handle until its wrapper is destroyed.
                del reader
            image = assign_source_space(image, path=path)
        else:
            image = _raw_image(path)
            if image.width() > width:
                image = image.scaledToWidth(width)
    if image.isNull():
        raise ValueError(f"无法生成预览：{path.name}")
    return to_srgb(image) if valid_color_mode(color_mode) == "srgb" else convert_preview(image, color_mode)


class PreviewLoader(CachedLoader):
    ready = Signal(str, int, object)
    failed = Signal(str, int, str)

    def __init__(self, parent: QObject | None = None, *, color_mode="srgb"):
        super().__init__(parent, name="picklight-hero", cache_size=64)
        self.color_mode = valid_color_mode(color_mode)
        # Hero images must never wait behind a long filmstrip decode queue.
        self.hero_pool = self.pool
        self.thumb_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="picklight-thumb")
        self._pools.append(self.thumb_pool)

    def set_color_mode(self, mode):
        mode = valid_color_mode(mode)
        if mode == self.color_mode:
            return False
        self.color_mode = mode
        # Removing pending identities also rejects results from already-running old jobs.
        self.invalidate({key[0] for key in self.cache.keys() | self.pending.keys()})
        return True

    def cached(self, path: Path, width: int) -> QImage | None:
        return super().cached((str(path), width))

    def request(self, path: Path, width: int) -> None:
        key = (str(path), width)
        hero = width >= 1000
        self._request(key, decode, path, width, self.color_mode, pool=self.hero_pool if hero else self.thumb_pool,
                      cancel=(lambda old: old[1] >= 1000 and old != key) if hero else None)

    def keep_thumbnails(self, paths: set[str]) -> None:
        self.cancel_pending(lambda key: key[1] < 1000 and key[0] not in paths)

    def remember(self, path: str, width: int, image: QImage) -> None:
        key = (path, width)
        if width > 2200:
            for old_key in list(self.cache):
                if old_key != key and old_key[1] > 2200:
                    self.cache.pop(old_key)
        super().remember(key, image)

    def forget_failed(self, path: str, width: int) -> None:
        super().forget_failed((path, width))
