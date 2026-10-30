"""Compact tooltips positioned underneath toolbar icons."""

from PySide6.QtCore import QPoint, QRect, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel

from picklight.appearance import ui_color


class IconTooltip(QFrame):
    def __init__(self, parent):
        super().__init__(parent, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.NoDropShadowWindowHint)
        self.setObjectName("iconTooltip")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFixedHeight(26)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(9, 0, 9, 0)
        self.label = QLabel()
        self.label.setObjectName("iconTooltipLabel")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.label)
        self.target = None

    def show_for(self, target, *, text=None, anchor=None):
        self.target = target
        self.label.setText(target.toolTip() if text is None else text)
        # Native font metrics and the stylesheet's bold font can differ by a few
        # pixels; leave room so the final glyph is never clipped.
        text_width = max(self.label.sizeHint().width(),
                         self.label.fontMetrics().boundingRect(self.label.text()).width())
        self.setFixedWidth(text_width + 24)
        anchor = QRect(target.rect() if anchor is None else anchor)
        position = target.mapToGlobal(QPoint(anchor.x() + (anchor.width() - self.width()) // 2,
                                             anchor.bottom() + 7))
        screen = QGuiApplication.screenAt(position) or QGuiApplication.primaryScreen()
        if screen:
            area = screen.availableGeometry()
            position.setX(max(area.left(), min(position.x(), area.right() - self.width() + 1)))
            if position.y() + self.height() > area.bottom() + 1:
                position.setY(target.mapToGlobal(QPoint(0, anchor.top() - self.height() - 6)).y())
        self.move(position)
        self.show()
        self.raise_()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(ui_color("#131416"))
        painter.setPen(QPen(ui_color("#414246"), 1))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), 3, 3)
        painter.end()
