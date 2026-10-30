"""Shared labels and toolbar dimensions."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPainter, QPalette
from PySide6.QtWidgets import QLabel


TOOLBAR_ICON_SIZE = QSize(16, 16)
DEFAULT_THUMBNAIL_WIDTH = 220


class ElidedLabel(QLabel):
    elide_mode = Qt.TextElideMode.ElideLeft

    def paintEvent(self, event):
        if "\n" in self.text() or self.fontMetrics().horizontalAdvance(self.text()) <= self.contentsRect().width():
            super().paintEvent(event)
            return
        painter = QPainter(self)
        painter.setFont(self.font())
        painter.setPen(self.palette().color(QPalette.ColorRole.WindowText))
        painter.drawText(self.contentsRect(), self.alignment(),
                         self.fontMetrics().elidedText(self.text(), self.elide_mode,
                                                      self.contentsRect().width()))
        painter.end()


def label(text: str, object_name: str = "") -> QLabel:
    item = ElidedLabel(text) if object_name == "detailValue" else QLabel(text)
    if object_name:
        item.setObjectName(object_name)
    return item
