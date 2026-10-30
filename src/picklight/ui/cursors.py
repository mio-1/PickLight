"""Render theme cursors at their actual display density."""

from functools import lru_cache
from pathlib import Path
import ctypes
import sys

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QCursor, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from picklight.paths import asset_path


@lru_cache(maxsize=1)
def _cursor_metrics_api():
    if sys.platform != "win32":
        return None
    try:
        api = ctypes.WinDLL("user32").GetSystemMetricsForDpi
        api.argtypes = [ctypes.c_int, ctypes.c_uint]
        api.restype = ctypes.c_int
        return api
    except (AttributeError, OSError):
        return None


def system_cursor_size(ratio=1.0):
    """Match Windows' standard cursor physical size at the current screen DPI."""
    ratio = max(1.0, ratio)
    api = _cursor_metrics_api()
    pixels = api(13, round(96 * ratio)) if api is not None else 0
    return pixels / ratio if pixels > 0 else 32


def _crisp_edges(pixmap):
    """Tighten coverage without growing the cursor silhouette."""
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888_Premultiplied)
    source = bytes(image.constBits())
    target = bytearray(source)
    width, height, stride = image.width(), image.height(), image.bytesPerLine()
    for y in range(height):
        for x in range(width):
            offset = y * stride + x * 4
            if source[offset + 3] == 0:
                continue
            neighbors = [yy * stride + xx * 4 for xx, yy in
                         ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1))
                         if 0 <= xx < width and 0 <= yy < height]
            for channel in (3, 0, 1, 2):
                value = (8 * source[offset + channel]
                         - sum(source[neighbor + channel] for neighbor in neighbors) + 2) // 4
                ceiling = 255 if channel == 3 else target[offset + 3]
                target[offset + channel] = max(0, min(ceiling, value))
    result = QImage(target, width, height, stride, image.format()).copy()
    result.setDevicePixelRatio(pixmap.devicePixelRatio())
    return QPixmap.fromImage(result)


@lru_cache(maxsize=32)
def cursor_pixmap(key, size=24, ratio=1.0, *, crisp=False):
    ratio = max(1.0, ratio)
    canvas = QPixmap(round(size * ratio), round(size * ratio))
    canvas.setDevicePixelRatio(ratio)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    path = asset_path(key)
    if Path(path).suffix.casefold() == ".svg":
        QSvgRenderer(path).render(painter, QRectF(0, 0, size, size))
    else:
        source = QPixmap(path)
        painter.drawPixmap(QRectF(0, 0, size, size), source, QRectF(source.rect()))
    painter.end()
    return _crisp_edges(canvas) if crisp else canvas


def theme_cursor(key, size=24, hotspot=QPoint(1, 1), ratio=1.0, *, crisp=False):
    # Match the screen DPR so Qt's Windows cursor conversion does not resample edges.
    return QCursor(cursor_pixmap(key, size, ratio, crisp=crisp), hotspot.x(), hotspot.y())
