"""Multi-photo review with independent decisions and optional linked viewports."""

from pathlib import Path
from math import ceil

from PySide6.QtCore import QPointF, QSize, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

from picklight.folder_dialogs import FolderModal
from picklight.details import DetailsLoader
from picklight.preview import PreviewLoader
from picklight.ui.common import ElidedLabel
from picklight.ui.graphics import oriented_jpeg_size
from picklight.ui.inspector import StarRatingControl, InspectorFlagButton
from picklight.viewer import LoupeCanvas


class ComparisonCanvas(LoupeCanvas):
    viewChanged = Signal()
    activated = Signal()

    def _changed(self, *, zoom_changed=True):
        super()._changed(zoom_changed=zoom_changed)
        self.viewChanged.emit()

    def mousePressEvent(self, event):
        self.activated.emit()
        super().mousePressEvent(event)

    def wheelEvent(self, event):
        self.activated.emit()
        super().wheelEvent(event)


class CompareTile(QFrame):
    activated = Signal()

    def __init__(self, pair, host, parent=None):
        super().__init__(parent)
        self.setObjectName("compareTile")
        self.pair, self.host = pair, host
        self.loader = PreviewLoader(self, color_mode=host.color_mode)
        self.loader.ready.connect(self.image_ready)
        self.loader.failed.connect(self.image_failed)
        self.details_loader = DetailsLoader(self)
        self.details_loader.ready.connect(self.details_ready)
        self.requested_width = 2200
        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)
        header = QHBoxLayout()
        header.setContentsMargins(12, 7, 8, 7)
        self.name = ElidedLabel(pair.display_path.name)
        self.name.setToolTip(str(pair.display_path))
        header.addWidget(self.name, 1)
        self.source = QComboBox(objectName="compareSource")
        for path, name in ((pair.jpg, "JPG"), (pair.raw, "RAW")):
            if path:
                self.source.addItem(name, str(path))
        header.addWidget(self.source)
        self.zoom_label = QLabel("适应", objectName="catalogHint")
        header.addWidget(self.zoom_label)
        layout.addLayout(header)
        self.canvas = ComparisonCanvas()
        layout.addWidget(self.canvas, 1)
        footer = QHBoxLayout()
        footer.setContentsMargins(12, 6, 12, 6)
        self.stars = StarRatingControl()
        self.stars.setFixedSize(100, 26)
        self.stars.ratingSelected.connect(lambda stars: host._rate_comparison_photo(pair, stars))
        footer.addWidget(self.stars)
        footer.addStretch()
        self.keep = InspectorFlagButton("保留", "keep")
        self.reject = InspectorFlagButton("待删除", "delete")
        self.keep.clicked.connect(lambda: host._mark_comparison_photo(pair, "keep"))
        self.reject.clicked.connect(lambda: host._mark_comparison_photo(pair, "reject"))
        footer.addWidget(self.keep)
        footer.addWidget(self.reject)
        layout.addLayout(footer)
        self.source.currentIndexChanged.connect(self.load_source)
        self.source.setVisible(bool(pair.jpg and pair.raw))
        self.stars.ratingSelected.connect(lambda _: self.activated.emit())
        self.keep.clicked.connect(lambda: self.activated.emit())
        self.reject.clicked.connect(lambda: self.activated.emit())
        self.canvas.viewChanged.connect(self.request_detail)
        self.load_source()
        self.refresh_state()

    def load_source(self, *_):
        path = Path(self.source.currentData())
        self.name.setText(path.name)
        self.name.setToolTip(str(path))
        self.requested_width = 2200
        self.canvas.begin_image(str(path), oriented_jpeg_size(path))
        self.canvas.set_loading()
        self.loader.request(path, 2200)
        if not self.canvas.source_size.isValid():
            self.details_loader.request(path)

    def details_ready(self, path, details):
        if path != self.source.currentData():
            return
        width, height = details.get("ImageWidth"), details.get("ImageHeight")
        if isinstance(width, (int, float)) and isinstance(height, (int, float)) and width > 0 and height > 0:
            self.canvas.set_source_size(QSize(int(width), int(height)))

    def image_ready(self, path, width, image):
        if path == self.source.currentData():
            self.canvas.set_image(image)

    def image_failed(self, path, width, error):
        if path == self.source.currentData():
            if self.canvas.image is None:
                self.canvas.set_message("无法加载照片")
            self.canvas.setToolTip(error)

    def request_detail(self):
        self.zoom_label.setText("适应" if self.canvas.fitted else f"{self.canvas.zoom * 100:.0f}%")
        if self.canvas.image is None or self.canvas.fitted:
            return
        wanted = min(12000, max(2200, ceil(self.canvas.source_size.width() * min(1, self.canvas.zoom))))
        if wanted > self.requested_width * 1.1:
            self.requested_width = wanted
            self.loader.request(Path(self.source.currentData()), wanted)

    def refresh_state(self):
        self.stars.set_rating(self.host.ratings.get(self.pair.key, 0))
        enabled = not self.host.batch_rating_loader.busy and not self.host.photo_file_loader.busy
        self.stars.setEnabled(enabled)
        state = "reject" if self.pair.key in self.host.marked else "keep" if self.pair.key in self.host.kept else ""
        self.keep.setChecked(state == "keep")
        self.reject.setChecked(state == "reject")


class ComparisonDialog(FolderModal):
    def __init__(self, pairs, parent):
        if not 2 <= len(pairs) <= 4:
            raise ValueError("请选择 2–4 组照片进行对比")
        super().__init__(parent)
        self.setWindowTitle("照片对比")
        self.resize(max(900, min(1500, parent.width() - 32)), max(560, min(960, parent.height() - 48)))
        self.active_tile = 0
        self.syncing = False
        body = QVBoxLayout(self.surface)
        body.setContentsMargins(12, 10, 12, 12)
        body.setSpacing(10)
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel(f"照片对比 · {len(pairs)} 张", objectName="catalogDialogTitle"))
        toolbar.addStretch()
        self.link = QCheckBox("同步缩放与移动")
        self.link.setChecked(True)
        toolbar.addWidget(self.link)
        for title, command in (("适应画布", self.fit_all), ("1:1", self.actual_all), ("完成", self.accept)):
            button = QPushButton(title, objectName="catalogButton")
            button.clicked.connect(command)
            toolbar.addWidget(button)
        body.addLayout(toolbar)
        grid = QGridLayout()
        grid.setSpacing(8)
        self.tiles = []
        for index, pair in enumerate(pairs):
            tile = CompareTile(pair, parent, self)
            self.tiles.append(tile)
            grid.addWidget(tile, index // 2, index % 2)
            tile.canvas.activated.connect(lambda i=index: self.activate_tile(i))
            tile.activated.connect(lambda i=index: self.activate_tile(i))
            tile.canvas.viewChanged.connect(lambda i=index: self.synchronize(i))
        body.addLayout(grid, 1)
        self.activate_tile(0)
        self.link.toggled.connect(lambda checked: self.synchronize(self.active_tile) if checked else None)
        for number in range(6):
            action = QAction(self)
            action.setShortcut(QKeySequence(parent.shortcuts[f"rating.{number}"]))
            action.triggered.connect(lambda checked=False, stars=number:
                                     parent._rate_comparison_photo(self.tiles[self.active_tile].pair, stars))
            self.addAction(action)
        for key, state in (("photo.keep", "keep"), ("photo.reject", "reject"), ("photo.clear", "")):
            action = QAction(self)
            action.setShortcut(QKeySequence(parent.shortcuts[key]))
            action.triggered.connect(lambda checked=False, value=state:
                                     parent._mark_comparison_photo(self.tiles[self.active_tile].pair, value))
            self.addAction(action)

    def activate_tile(self, index):
        self.active_tile = index
        for number, tile in enumerate(self.tiles):
            tile.setProperty("active", number == index)
            tile.style().unpolish(tile)
            tile.style().polish(tile)
            tile.update()

    def synchronize(self, index):
        if self.syncing or not self.link.isChecked():
            return
        source = self.tiles[index].canvas
        self.syncing = True
        try:
            for number, tile in enumerate(self.tiles):
                target = tile.canvas
                if number == index or target.image is None:
                    continue
                if source.fitted:
                    target.fit_to_canvas()
                else:
                    target.fitted = False
                    target.zoom = source.zoom
                    target.pan = QPointF(source.pan.x() / max(1, source.width()) * target.width(),
                                         source.pan.y() / max(1, source.height()) * target.height())
                    target._changed()
        finally:
            self.syncing = False

    def fit_all(self):
        for tile in self.tiles:
            tile.canvas.fit_to_canvas()

    def actual_all(self):
        for tile in self.tiles:
            tile.canvas.set_zoom(1.0)

    def refresh_state(self):
        for tile in self.tiles:
            tile.refresh_state()

    def done(self, result):
        for tile in self.tiles:
            tile.loader.shutdown()
            tile.details_loader.shutdown()
        super().done(result)
