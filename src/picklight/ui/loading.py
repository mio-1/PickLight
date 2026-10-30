"""A small themed spinner that repaints only while its preview is visible."""

from PySide6.QtCore import QElapsedTimer, QEvent, QTimer, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QWidget

from picklight.ui.graphics import theme_icon


class LoadingSpinner(QWidget):
    def __init__(self, parent, size=40):
        super().__init__(parent)
        self._wanted = False
        self.elapsed = QElapsedTimer()
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.update)
        self.setFixedSize(size, size)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAccessibleName("正在载入预览")
        parent.installEventFilter(self)
        self.hide()

    def set_loading(self, active):
        active = bool(active)
        if active and not self._wanted:
            self.elapsed.start()
        self._wanted = active
        self._sync_visibility()

    def _sync_visibility(self):
        active = self._wanted and self.parentWidget().isVisible()
        self.move(self.parentWidget().rect().center() - self.rect().center())
        self.setVisible(active)
        if active:
            self.raise_()
            self.timer.start()
            self.update()
        else:
            self.timer.stop()

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Show, QEvent.Type.Hide, QEvent.Type.Resize):
            self._sync_visibility()
        return False

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.translate(self.width() / 2, self.height() / 2)
        painter.rotate((self.elapsed.elapsed() % 900) * 360 / 900)
        size = self.width() - 8
        theme_icon("loading.spinner", size).paint(painter, -size // 2, -size // 2, size, size)
        painter.end()
