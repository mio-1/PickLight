"""A separate, modeless photo preview for a gallery middle click."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout

from picklight.preview import PreviewLoader
from picklight.viewer import LoupeCanvas


class DetachedPreview(QDialog):
    def __init__(self, path: Path, parent=None, *, color_mode="srgb", grayscale=False):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(path.name)
        self.resize(1050, 750)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.canvas = LoupeCanvas(self)
        self.canvas.grayscale = grayscale
        self.canvas.begin_image(str(path))
        layout.addWidget(self.canvas)
        self.loader = PreviewLoader(self, color_mode=color_mode)
        self.loader.ready.connect(self._ready)
        self.loader.failed.connect(self._failed)
        self.loader.request(path, 2200)

    def _ready(self, path, width, image):
        self.loader.remember(path, width, image)
        self.canvas.set_image(image)

    def _failed(self, path, width, message):
        self.loader.forget_failed(path, width)
        self.canvas.set_message(message)

    def closeEvent(self, event):
        self.loader.shutdown()
        super().closeEvent(event)
