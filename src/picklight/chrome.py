"""Frameless Windows window chrome for the photo workspace."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap, QRegion
from PySide6.QtWidgets import QFrame, QPushButton, QWidget


from picklight.appearance import ui_color
from picklight.ui.interaction import HoverAnimationMixin

def icon_canvas(logical_size: int) -> QPixmap:
    """Give painted icons enough source pixels for smooth DPI scaling."""
    scale = 4
    canvas = QPixmap(logical_size * scale, logical_size * scale)
    canvas.setDevicePixelRatio(scale)
    canvas.fill(Qt.GlobalColor.transparent)
    return canvas


WINDOW_CORNER_RADIUS = 8
WINDOW_EDGE_COLOR = QColor(232, 236, 244, 70)
WINDOW_RESIZE_BORDER = 5
WINDOW_RESIZE_CORNER = 12


def window_resize_edges(point, size):
    """Match the thin border handles; corners extend along the edges, never inward."""
    x, y = point.x(), point.y()
    width, height = size.width(), size.height()
    if not (0 <= x < width and 0 <= y < height):
        return Qt.Edge(0)
    border, corner = WINDOW_RESIZE_BORDER, WINDOW_RESIZE_CORNER
    left, right = x < border, x >= width - border
    top, bottom = y < border, y >= height - border
    if not (left or right or top or bottom):
        return Qt.Edge(0)
    edges = Qt.Edge(0)
    if left or ((top or bottom) and x < corner):
        edges |= Qt.Edge.LeftEdge
    elif right or ((top or bottom) and x >= width - corner):
        edges |= Qt.Edge.RightEdge
    if top or ((left or right) and y < corner):
        edges |= Qt.Edge.TopEdge
    elif bottom or ((left or right) and y >= height - corner):
        edges |= Qt.Edge.BottomEdge
    return edges


class WindowOutline(QWidget):
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event):
        if (self.window().isMaximized() or self.window().isFullScreen()
                or self.window().property("nativeOutlineActive")):
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(WINDOW_EDGE_COLOR, 1, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        # A one-pixel stroke inset by half a pixel shares the outer clip's arc.
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5),
                                WINDOW_CORNER_RADIUS - .5, WINDOW_CORNER_RADIUS - .5)
        painter.end()


class WindowSurface(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.outline = WindowOutline(self)
        self.resize_handles = {}
        cursors = {
            "top": Qt.CursorShape.SizeVerCursor,
            "bottom": Qt.CursorShape.SizeVerCursor,
            "left": Qt.CursorShape.SizeHorCursor,
            "right": Qt.CursorShape.SizeHorCursor,
            "top_left": Qt.CursorShape.SizeFDiagCursor,
            "bottom_right": Qt.CursorShape.SizeFDiagCursor,
            "top_right": Qt.CursorShape.SizeBDiagCursor,
            "bottom_left": Qt.CursorShape.SizeBDiagCursor,
        }
        for name, cursor in cursors.items():
            handle = QWidget(self)
            handle.setObjectName("windowResizeHandle")
            handle.setCursor(cursor)
            self.resize_handles[name] = handle

    def _layout_resize_handles(self):
        edge, corner = WINDOW_RESIZE_BORDER, WINDOW_RESIZE_CORNER
        width, height = self.width(), self.height()
        geometry = {
            "top": (corner, 0, max(0, width - 2 * corner), edge),
            "bottom": (corner, height - edge, max(0, width - 2 * corner), edge),
            "left": (0, corner, edge, max(0, height - 2 * corner)),
            "right": (width - edge, corner, edge, max(0, height - 2 * corner)),
            "top_left": (0, 0, corner, corner),
            "top_right": (width - corner, 0, corner, corner),
            "bottom_left": (0, height - corner, corner, corner),
            "bottom_right": (width - corner, height - corner, corner, corner),
        }
        for name, rect in geometry.items():
            self.resize_handles[name].setGeometry(*rect)
            if "_" in name:
                x = corner - edge if name.endswith("right") else 0
                y = corner - edge if name.startswith("bottom") else 0
                self.resize_handles[name].setMask(
                    QRegion(QRect(x, 0, edge, corner)) |
                    QRegion(QRect(0, y, corner, edge)))

    def update_window_shape(self):
        window = self.window()
        resizable = not (window.isMaximized() or window.isFullScreen())
        if not resizable:
            self.clearMask()
            window.clearMask()
        else:
            path = QPainterPath()
            path.addRoundedRect(QRectF(self.rect()), WINDOW_CORNER_RADIUS,
                                WINDOW_CORNER_RADIUS)
            region = QRegion(path.toFillPolygon().toPolygon())
            self.setMask(region)
            # Clip the native window too: Windows' backdrop is outside the child
            # surface and otherwise fills the corners behind the rounded outline.
            window.setMask(region.translated(self.mapTo(window, QPoint())))
        from picklight.platform_effects import set_window_shape
        set_window_shape(window, WINDOW_CORNER_RADIUS if resizable else 0)
        for handle in self.resize_handles.values():
            handle.setVisible(resizable)
            handle.raise_()
        self.outline.update()
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.outline.setGeometry(self.rect())
        self.outline.raise_()
        self._layout_resize_handles()
        self.update_window_shape()

    def showEvent(self, event):
        super().showEvent(event)
        self.outline.raise_()
        self._layout_resize_handles()
        self.update_window_shape()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        surface = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        background = ui_color("#18191c")
        if self.window().property("backdropActive"):
            titlebar = getattr(self.window(), "title_bar", None)
            height = titlebar.height() if titlebar is not None else 44
            painter.setClipRect(self.rect().adjusted(0, height, 0, 0))
        if self.window().isMaximized() or self.window().isFullScreen():
            painter.fillRect(self.rect(), background)
        else:
            outline = QPainterPath()
            outline.addRoundedRect(surface, WINDOW_CORNER_RADIUS - .5, WINDOW_CORNER_RADIUS - .5)
            painter.fillPath(outline, background)
        painter.end()


class _TitleBarDragMixin:
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.owner.windowHandle():
            self.owner.windowHandle().startSystemMove()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.owner.toggle_maximize()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class TitleBar(_TitleBarDragMixin, QFrame):
    def __init__(self, owner: QWidget):
        super().__init__(owner)
        self.owner = owner
        self.setObjectName("titleBar")
        self.setFixedHeight(44)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self.owner.isMaximized():
            painter.setClipRect(self.rect())
        else:
            clip = QPainterPath()
            clip.addRoundedRect(QRectF(.5, .5, self.width() - 1, self.height() + WINDOW_CORNER_RADIUS),
                                WINDOW_CORNER_RADIUS - .5, WINDOW_CORNER_RADIUS - .5)
            painter.setClipPath(clip)
        backdrop = bool(self.owner.property("backdropActive"))
        background = ui_color("#18191c")
        if backdrop:
            background.setAlpha(235)
        left = self.owner.title_left.width() if hasattr(self.owner, "title_left") else 230
        if hasattr(self.owner, "title_left") and self.owner.title_left.isHidden():
            left = 0
        right = self.width() - (self.owner.title_right.width()
                                if hasattr(self.owner, "title_right") else 265)
        side = ui_color("#1f2023")
        if backdrop:
            side.setAlpha(235)
        # Paint the three regions once, so translucent sides do not blend into
        # the canvas color and lose the contrast of the original palette.
        painter.fillRect(left, 0, max(0, right - left), self.height(), background)
        painter.fillRect(0, 0, left, self.height(), side)
        painter.fillRect(right, 0, self.width() - right, self.height(), side)
        painter.setPen(QPen(ui_color("#303135"), 1))
        if left:
            painter.drawLine(QPointF(left - 0.5, 0), QPointF(left - 0.5, self.height()))
        painter.drawLine(QPointF(right + 0.5, 0), QPointF(right + 0.5, self.height()))
        painter.end()



class TitleBarSegment(_TitleBarDragMixin, QFrame):
    def __init__(self, owner: QWidget, object_name: str = ""):
        super().__init__(owner)
        self.owner = owner
        if object_name:
            self.setObjectName(object_name)



class WindowControlButton(HoverAnimationMixin, QPushButton):
    def __init__(self, kind: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.kind = kind
        self.setObjectName("closeControl" if kind == "close" else "windowControl")
        self.setFixedSize(40, 44)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._init_hover_animation()
        names = {"minimize": "最小化", "maximize": "最大化", "restore": "还原", "close": "关闭"}
        self.setAccessibleName(names[kind])
        self.setToolTip(names[kind])

    def set_kind(self, kind: str):
        self.kind = kind
        name = "还原" if kind == "restore" else "最大化"
        self.setAccessibleName(name)
        self.setToolTip(name)
        self.update()

    def enterEvent(self, event):
        self._animate_hover(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._animate_hover(0.0)
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._hover_amount:
            painter.setPen(Qt.PenStyle.NoPen)
            background = (QColor(173, 57, 67, round(180 * self._hover_amount))
                          if self.kind == "close" else ui_color(QColor(255, 255, 255,
                                                               round(12 * self._hover_amount))))
            painter.setBrush(background)
            painter.drawRoundedRect(QRectF(3, 6, self.width() - 6, self.height() - 12), 5, 5)
        painter.setPen(QPen(ui_color("#ffffff" if self._hover_amount > 0.5 else "#b5b6bc"),
                            1.15, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        x, y = self.width() / 2, self.height() / 2
        if self.kind == "minimize":
            painter.drawLine(QPointF(x - 4.5, y + 2), QPointF(x + 4.5, y + 2))
        elif self.kind == "maximize":
            painter.drawRoundedRect(QRectF(x - 4.5, y - 4.5, 9, 9), 0.7, 0.7)
        elif self.kind == "restore":
            painter.drawRoundedRect(QRectF(x - 2, y - 4.5, 7, 6), 0.6, 0.6)
            painter.drawRoundedRect(QRectF(x - 5, y - 1.5, 7, 6), 0.6, 0.6)
        else:
            painter.drawLine(QPointF(x - 4.5, y - 4.5), QPointF(x + 4.5, y + 4.5))
            painter.drawLine(QPointF(x + 4.5, y - 4.5), QPointF(x - 4.5, y + 4.5))
        painter.end()
