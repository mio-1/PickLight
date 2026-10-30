"""Theme-aware icons and photo drawing helpers."""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from math import cos, pi, sin
from pathlib import Path

from PySide6.QtCore import QByteArray, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFontDatabase,
    QIcon,
    QImageIOHandler,
    QImageReader,
    QPainter,
    QPainterPath,
    QPixmap,
)
from PySide6.QtSvg import QSvgRenderer

from picklight.chrome import icon_canvas
from picklight.appearance import ui_color
from picklight.file_access import photo_files
from picklight.folder_menu import folder_icon_names
from picklight.library import PhotoPair
from picklight.metadata import MetadataError, read_pair_rating
from picklight.paths import asset_path


@lru_cache(maxsize=2)
def theme_rating_pixmap(lit: bool) -> QPixmap:
    filename = asset_path("rating.on" if lit else "rating.off")
    canvas = icon_canvas(12)
    painter = QPainter(canvas)
    if Path(filename).suffix.lower() == ".svg":
        QSvgRenderer(filename).render(painter, QRectF(0, 0, 12, 12))
    else:
        painter.drawPixmap(QRectF(0, 0, 12, 12), QPixmap(filename), QRectF(QPixmap(filename).rect()))
    painter.end()
    return canvas


@lru_cache(maxsize=32)
def theme_icon(asset: str, size: int = 24) -> QIcon:
    path = Path(asset_path(asset))
    if path.suffix.lower() != ".svg":
        return QIcon(str(path))
    svg_data = path.read_bytes()
    from picklight.appearance import is_light, register_icon
    from picklight.themes import theme_manager
    icon_colors = theme_manager().active.manifest.get("style", {}).get("icons", {})
    icon = QIcon()
    normal_color = b"#45464a" if is_light() else icon_colors.get("normal", "#cbcbcc").encode()
    for mode, color in ((QIcon.Mode.Normal, normal_color),
                        (QIcon.Mode.Active, b"#18191c" if is_light() else icon_colors.get("active", "#F7F8F8").encode()),
                        (QIcon.Mode.Disabled, b"#a0a1a5" if is_light() else icon_colors.get("disabled", "#515256").encode())):
        tinted = svg_data.replace(b"#F7F8F8", color).replace(b'#fff"', color + b'"')
        canvas = icon_canvas(size)
        painter = QPainter(canvas)
        QSvgRenderer(QByteArray(tinted)).render(painter, QRectF(0, 0, size, size))
        painter.end()
        icon.addPixmap(canvas, mode)
        if asset == "loupe.fit" and mode == QIcon.Mode.Active:
            icon.addPixmap(canvas, QIcon.Mode.Normal, QIcon.State.On)
    register_icon(icon, asset, size)
    return icon


def filter_icon() -> QIcon:
    return theme_icon("toolbar.filter")


@lru_cache(maxsize=32)
def photo_state_pixmap(state: str, size: int = 16, color: str = "", *, badge: bool = False,
                       device_ratio: float = 1.0) -> QPixmap:
    source_path = asset_path(("photo.badge." if badge else "photo.") + (
        "reject" if state == "reject" else "keep"))
    if badge:
        canvas = QPixmap(round(size * device_ratio), round(size * device_ratio))
        canvas.setDevicePixelRatio(device_ratio)
        canvas.fill(Qt.GlobalColor.transparent)
    else:
        canvas = icon_canvas(size)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    if Path(source_path).suffix.casefold() == ".svg":
        QSvgRenderer(source_path).render(painter, QRectF(0, 0, size, size))
    else:
        source = QPixmap(source_path)
        painter.drawPixmap(QRectF(0, 0, size, size), source, QRectF(source.rect()))
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(QRectF(0, 0, size, size), QColor(color or (
        "#f2797d" if state == "reject" else "#62d79c")))
    painter.end()
    return canvas


def paint_photo_state(painter, image_rect, state):
    if state not in ("keep", "reject") or image_rect.width() < 36 or image_rect.height() < 36:
        return
    ratio = painter.device().devicePixelRatioF()
    position = QPointF(round((image_rect.left() + 7) * ratio) / ratio,
                       round((image_rect.bottom() - 23) * ratio) / ratio)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.drawPixmap(position, photo_state_pixmap(state, 16, badge=True, device_ratio=ratio))
    painter.restore()


def search_icon() -> QIcon:
    return theme_icon("search", 16)


def navigation_icon(direction: int) -> QIcon:
    return theme_icon("toolbar.back" if direction < 0
                              else "toolbar.forward")


def arrangement_icon() -> QIcon:
    return theme_icon("toolbar.layout")


def folder_add_icon() -> QIcon:
    return theme_icon("plus", 20)


@lru_cache(maxsize=2)
def folder_triangle_icon(expanded: bool = True) -> QIcon:
    canvas = icon_canvas(12)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    svg_data = Path(asset_path("tree.arrow")).read_bytes()
    if ui_color("#ffffff").lightness() < 128:
        svg_data = svg_data.replace(b"#F7F8F8", b"#45464a").replace(b"#cbcbcc", b"#45464a").replace(b'fill="black"', b'fill="#45464a"')
    if expanded:
        painter.translate(6, 6)
        painter.rotate(90)
        painter.translate(-6, -6)
    QSvgRenderer(QByteArray(svg_data)).render(painter, QRectF(0, 0, 12, 12))
    painter.end()
    return QIcon(canvas)


@lru_cache(maxsize=512)
def folder_tree_icon(opened: bool, highlighted: bool = False, icon_name: str = "", color: str = "",
                     size: int = 24) -> QIcon:
    source_path = asset_path(f"folder.icon.{icon_name}" if icon_name in folder_icon_names()
                             else "folder.open" if opened else "folder.closed")
    source = icon_canvas(size)
    drawing = QPainter(source)
    drawing.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    if Path(source_path).suffix.lower() == ".svg":
        QSvgRenderer(source_path).render(drawing, QRectF(0, 0, size, size))
    else:
        original = QPixmap(source_path)
        drawing.drawPixmap(QRectF(0, 0, size, size), original, QRectF(original.rect()))
    drawing.end()
    painter = QPainter(source)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    tint = QColor(color) if color else ui_color("#f7f8f8" if highlighted else "#d2d3d5")
    if not color:
        from picklight.themes import theme_manager
        folder_color = theme_manager().active.manifest.get("style", {}).get("icons", {}).get("folder")
        if folder_color:
            tint = QColor(folder_color).lighter(115) if highlighted else QColor(folder_color)
    if color and highlighted:
        tint = tint.lighter(115)
    painter.fillRect(source.rect(), tint)
    painter.end()
    icon = QIcon(source)
    icon.addPixmap(source, QIcon.Mode.Active)
    icon.addPixmap(source, QIcon.Mode.Selected)
    return icon


def expand_icon() -> QIcon:
    return theme_icon("loupe.fit", 16)


def clear_theme_caches():
    """Call before rebuilding widgets after a resource theme change."""
    theme_icon.cache_clear()
    theme_rating_pixmap.cache_clear()
    folder_triangle_icon.cache_clear()
    folder_tree_icon.cache_clear()
    photo_state_pixmap.cache_clear()
    from picklight.ui.cursors import cursor_pixmap
    cursor_pixmap.cache_clear()
    folder_icon_names.cache_clear()
    from picklight.ui.visual_filters import _rating_star
    _rating_star.cache_clear()


def apply_theme_font():
    """Use system fonts by default; registered themes may supply an inspector font."""
    from PySide6.QtWidgets import QApplication
    from picklight.themes import theme_manager
    app = QApplication.instance()
    manager = theme_manager()
    path = manager.active.asset("inspector.mono") or manager.default.asset("inspector.mono")
    if getattr(app, "_theme_font_path", None) == path:
        return
    font_id = getattr(app, "_theme_font_id", -1)
    if font_id >= 0:
        QFontDatabase.removeApplicationFont(font_id)
    app._theme_font_id = QFontDatabase.addApplicationFont(str(path)) if path and path.is_file() else -1
    app._theme_font_path = path


def safe_rating(pair: PhotoPair, dng_ratings: dict[Path, int | None]) -> tuple[int, bool]:
    try:
        if pair.raw in dng_ratings:
            return read_pair_rating(pair, dng_ratings[pair.raw]), False
        return read_pair_rating(pair), False
    except (OSError, MetadataError):
        return 0, True


def format_detail_date(value: str | datetime | None) -> str:
    if not value:
        return "—"
    if not isinstance(value, datetime):
        source = str(value)
        for pattern in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S",
                        "%Y-%m-%d %H:%M"):
            try:
                value = datetime.strptime(source, pattern)
                break
            except ValueError:
                continue
        else:
            return source
    return f"{value.year}年{value.month}月{value.day}日 {value.hour:02}:{value.minute:02}"


def oriented_jpeg_size(path: Path) -> QSize:
    with photo_files([path]):
        reader = QImageReader(str(path))
        try:
            size = reader.size()
            if size.isValid() and reader.transformation() & QImageIOHandler.Transformation.TransformationRotate90:
                size.transpose()
        finally:
            del reader
    return size


def star_path(x: float, y: float, radius: float) -> QPainterPath:
    path = QPainterPath()
    for point in range(10):
        angle = -pi / 2 + point * pi / 5
        distance = radius if point % 2 == 0 else radius * 0.42
        px, py = x + cos(angle) * distance, y + sin(angle) * distance
        if point == 0:
            path.moveTo(px, py)
        else:
            path.lineTo(px, py)
    path.closeSubpath()
    return path


def thumbnail_icon(image, size: QSize | None = None) -> QIcon:
    size = size or QSize(185, 123)
    scale = 2
    canvas = QPixmap(QSize(size.width() * scale, size.height() * scale))
    canvas.setDevicePixelRatio(scale)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    clip = QPainterPath()
    clip.addRoundedRect(QRectF(0, 0, size.width(), size.height()), 8, 8)
    painter.setClipPath(clip)
    painter.fillPath(clip, QColor("#1b1c20"))
    source = QPixmap.fromImage(image).scaled(
        QSize(size.width() * scale, size.height() * scale),
        Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
    )
    source.setDevicePixelRatio(scale)
    painter.drawPixmap((size.width() - source.width() / scale) / 2,
                       (size.height() - source.height() / scale) / 2, source)
    painter.end()
    return QIcon(canvas)
