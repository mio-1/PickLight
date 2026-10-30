"""Compact import status along the bottom of the center workspace."""

from PySide6.QtCore import QEasingCurve, QElapsedTimer, QSize, QTimer, QVariantAnimation, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QProgressBar, QSizePolicy, QToolButton, QVBoxLayout, QWidget

from picklight.ui.common import ElidedLabel
from picklight.ui.graphics import theme_icon


class ImportProgress(QWidget):
    cancelRequested = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("importProgress")
        self.setFixedHeight(40)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        divider = QFrame(objectName="importProgressDivider")
        divider.setFixedHeight(1)
        outer.addWidget(divider)
        layout = QHBoxLayout()
        layout.setContentsMargins(10, 9, 6, 0)
        layout.setSpacing(10)
        outer.addLayout(layout, 1)
        self.bar = QProgressBar(objectName="importProgressBar")
        self.bar.setFixedHeight(3)
        self.bar.setMinimumWidth(80)
        self.bar.setTextVisible(False)
        layout.addWidget(self.bar, 1)
        self.status = ElidedLabel()
        self.status.setObjectName("importProgressStatus")
        self.status.setMinimumWidth(0)
        self.status.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.status)
        self.cancel_button = QToolButton(objectName="importCancel")
        self.cancel_button.setIcon(theme_icon("import.cancel", 10))
        self.cancel_button.setIconSize(QSize(10, 10))
        self.cancel_button.setFixedSize(28, 28)
        self.cancel_button.setToolTip("取消导入")
        self.cancel_button.setAccessibleName("取消导入")
        self.cancel_button.clicked.connect(self.cancelRequested)
        layout.addWidget(self.cancel_button)
        self.elapsed = QElapsedTimer()
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._update_text)
        self.motion = QVariantAnimation(self)
        self.motion.setDuration(140)
        self.motion.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.motion.valueChanged.connect(lambda value: self.bar.setValue(round(value)))
        self.done = self.total = 0
        self.hide()

    def begin(self):
        self.done = self.total = 0
        self.motion.stop()
        self.bar.setRange(0, 0)
        self.elapsed.start()
        self.timer.start()
        self._update_text()
        self.show()

    def set_progress(self, done, total, path):
        self.done, self.total = done, total
        self.status.setToolTip(path)
        if total:
            current = max(0, self.bar.value()) if self.bar.maximum() else 0
            self.bar.setRange(0, 1000)
            self.motion.stop()
            self.motion.setStartValue(float(current))
            self.motion.setEndValue(float(round(done / total * 1000)))
            self.motion.start()
        self._update_text()

    def _update_text(self):
        seconds = self.elapsed.elapsed() // 1000
        stamp = f"{seconds // 3600}:{seconds // 60 % 60:02}:{seconds % 60:02}"
        title = f"正在添加文件… {self.done}/{self.total}" if self.total else "正在扫描照片…"
        self.status.setText(f"{title} ({stamp})")

    def finish(self):
        self.timer.stop()
        self.motion.stop()
        self.hide()
