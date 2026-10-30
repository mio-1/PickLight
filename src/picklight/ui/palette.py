"""Inspector color swatches with hover highlighting and click-to-filter actions."""

from PySide6.QtCore import QEvent, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from picklight.palette import display_palette


class PaletteStrip(QWidget):
    colorSelected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.colors = []
        self.hovered = -1
        self.pressed = -1
        self.selected_color = None
        self._tooltip = None
        self.setAccessibleName("图片主要颜色")
        self.setMouseTracking(True)
        self.setFixedSize(192, 28)

    def set_colors(self, colors):
        self._hide_tooltip()
        self.setToolTip("")
        self.unsetCursor()
        self.hovered = -1
        self.pressed = -1
        self.colors = display_palette(colors)
        self.setAccessibleDescription("、".join(color.detail for color in self.colors))
        self.update()

    def set_selected_color(self, rgb):
        self.selected_color = tuple(rgb) if rgb is not None else None
        self.update()

    def _index_at(self, position):
        return next((index for index in range(len(self.colors))
                     if QRectF(7 + index * 18, 6, 16, 16).contains(position)), -1)

    def mousePressEvent(self, event):
        self._hide_tooltip()
        if event.button() == Qt.MouseButton.LeftButton:
            self.pressed = self._index_at(event.position())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            index = self._index_at(event.position())
            if index >= 0 and index == self.pressed:
                self.colorSelected.emit(QColor(*self.colors[index].rgb).name().upper())
            self.pressed = -1
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        position = event.position()
        hovered = self._index_at(position)
        if hovered != self.hovered:
            self.hovered = hovered
            self.setToolTip(self.colors[hovered].detail if hovered >= 0 else "")
            if self._tooltip is not None and self._tooltip.isVisible() and hovered >= 0:
                self._show_tooltip(hovered)
            else:
                self._hide_tooltip()
            self.update()
            self.setCursor(Qt.CursorShape.PointingHandCursor if hovered >= 0
                           else Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._hide_tooltip()
        self.setToolTip("")
        self.hovered = -1
        self.update()
        super().leaveEvent(event)

    def _show_tooltip(self, index):
        if self._tooltip is None:
            from picklight.ui.tooltips import IconTooltip
            self._tooltip = IconTooltip(self)
        self._tooltip.show_for(self, text=self.colors[index].detail,
                               anchor=QRect(7 + index * 18, 6, 16, 16))

    def _hide_tooltip(self):
        if self._tooltip is not None:
            self._tooltip.hide()

    def event(self, event):
        if event.type() == QEvent.Type.ToolTip:
            index = self._index_at(event.pos())
            if index >= 0:
                self._show_tooltip(index)
            else:
                self._hide_tooltip()
            event.accept()
            return True
        if event.type() == QEvent.Type.Hide:
            self._hide_tooltip()
        return super().event(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#303134"), 1))
        painter.setBrush(QColor(0, 0, 0, 51))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 14, 14)
        for index, color in enumerate(self.colors):
            circle = QRectF(8 + index * 18, 7, 14, 14)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(*color.rgb))
            painter.drawEllipse(circle)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            if index == self.hovered or color.rgb == self.selected_color:
                painter.setPen(QPen(QColor("#cbcbcc"), 1))
                painter.drawEllipse(circle.adjusted(-1.5, -1.5, 1.5, 1.5))
            else:
                painter.setPen(QPen(QColor(255, 255, 255, 26), 1))
                painter.drawEllipse(circle.adjusted(0.5, 0.5, -0.5, -0.5))
        painter.end()
