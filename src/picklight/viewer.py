"""Zoomable photo canvas for the in-window image viewer."""

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, QSize, QSizeF, Qt, Signal, QTimer
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget

from picklight.appearance import ui_color

from picklight.ui.cursors import system_cursor_size, theme_cursor
from picklight.ui.loading import LoadingSpinner


class LoupeCanvas(QWidget):
    zoomChanged = Signal(float)
    exitRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.image = None
        self._gpu_surface = None
        self.loading_spinner = LoadingSpinner(self)
        self.message = ""
        self.source_size = QSizeF()
        self.image_key = None
        self.rotation = 0
        self.zoom = 1.0
        self.pan = QPointF()
        self.fitted = True
        self._dragging = False
        self._hand_pressed = False
        self._last_drag_position = QPointF()
        self.decision_state = ""
        self._refresh_hand_cursor()
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(220, 100)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_decision_state(self, state):
        self.decision_state = state

    def enterEvent(self, event):
        self._refresh_hand_cursor()
        super().enterEvent(event)

    def event(self, event):
        if event.type() == QEvent.Type.DevicePixelRatioChange:
            self._refresh_hand_cursor()
        return super().event(event)

    def _refresh_hand_cursor(self):
        ratio = self.devicePixelRatioF()
        size = system_cursor_size(ratio)
        signature = (size, ratio, self._hand_pressed)
        if signature != getattr(self, "_hand_cursor_signature", None):
            self.setCursor(theme_cursor("cursor.grabbing" if self._hand_pressed else "cursor.grab", size,
                           QPoint(round(size / 2), round(size * 18 / 32)), ratio, crisp=True))
            self._hand_cursor_signature = signature

    def begin_image(self, key, source_size=QSize()):
        if key != self.image_key:
            self.image_key = key
            self.rotation = 0
            self.image = None
            self.source_size = QSizeF(source_size) if source_size.isValid() else QSizeF()
            self.pan = QPointF()
            self.fitted = True
            self._dragging = False
            self._hand_pressed = False
            self._refresh_hand_cursor()
        elif source_size.isValid():
            # A source can be overwritten at the same path with different dimensions.
            self.source_size = QSizeF(source_size)

    def set_source_size(self, size):
        if not size.isValid() or size.isEmpty():
            return
        size = QSizeF(size)
        if self.image is not None:
            if ((self.image.width() > self.image.height()) !=
                    (size.width() > size.height())):
                size.transpose()
        old_width = self.source_size.width()
        self.source_size = size
        if self.image is not None:
            if self.fitted:
                self.fit_to_canvas()
            elif old_width > 0:
                self.zoom = max(0.05, min(8.0, self.zoom * old_width / size.width()))
                self._changed()

    def set_image(self, image):
        self.image = image
        self.message = ""
        self.loading_spinner.set_loading(False)
        if not self.source_size.isValid() or self.source_size.isEmpty():
            self.source_size = QSizeF(image.size())
        elif ((image.width() > image.height()) !=
              (self.source_size.width() > self.source_size.height())):
            self.source_size.transpose()
        if self.fitted:
            self.fit_to_canvas()
        else:
            self._changed()

    def set_message(self, message):
        self.loading_spinner.set_loading(False)
        self.image = None
        self._dragging = False
        self._hand_pressed = False
        self._refresh_hand_cursor()
        self.message = message
        self.update()

    def set_loading(self):
        self.set_message("")
        self.loading_spinner.set_loading(True)

    def display_source_size(self):
        size = QSizeF(self.source_size)
        if self.rotation % 180:
            size.transpose()
        return size

    def rotate_clockwise(self):
        self._rotate_by(90)

    def rotate_counterclockwise(self):
        self._rotate_by(-90)

    def _rotate_by(self, degrees):
        if self.image is None:
            return
        self.rotation = (self.rotation + degrees) % 360
        if self.fitted:
            self.fit_to_canvas()
        else:
            self._changed()

    def fit_zoom(self):
        size = self.display_source_size()
        if size.isEmpty():
            return 1.0
        return max(0.05, min(1.0, max(1, self.width() - 48) / size.width(),
                             max(1, self.height() - 48) / size.height()))

    def fit_to_canvas(self):
        self.zoom = self.fit_zoom()
        self.pan = QPointF()
        self.fitted = True
        self._changed()

    def image_rect(self):
        size = self.display_source_size() * self.zoom
        center = QPointF(self.rect().center()) + self.pan
        return QRectF(center.x() - size.width() / 2, center.y() - size.height() / 2,
                      size.width(), size.height())

    def set_zoom(self, zoom, anchor=None):
        if self.image is None:
            return
        zoom = max(0.05, min(8.0, float(zoom)))
        anchor = QPointF(anchor) if anchor is not None else QPointF(self.rect().center())
        center = QPointF(self.rect().center())
        self.pan = anchor - center - (anchor - center - self.pan) * (zoom / self.zoom)
        self.zoom = zoom
        self.fitted = False
        self._changed()

    def _changed(self, *, zoom_changed=True):
        self.update()
        if zoom_changed:
            self.zoomChanged.emit(self.zoom)

    def wheelEvent(self, event):
        if self.image is not None:
            delta = event.angleDelta().y() or event.pixelDelta().y()
            if delta:
                self.set_zoom(self.zoom * 1.0015 ** delta, event.position())
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._hand_pressed = True
            self._refresh_hand_cursor()
        if event.button() == Qt.MouseButton.LeftButton and self.image is not None and not self.image.isNull():
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self._dragging = True
            self._last_drag_position = event.position()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.position() - self._last_drag_position
            self._last_drag_position = event.position()
            if not delta.isNull():
                self.pan += delta
                self.fitted = False
                self._changed(zoom_changed=False)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._hand_pressed = False
            self._refresh_hand_cursor()
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self._hand_pressed = False
            self._refresh_hand_cursor()
            self.exitRequested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._gpu_surface is not None:
            self._gpu_surface.setGeometry(self.rect())
        if self.fitted and self.image is not None:
            self.fit_to_canvas()

    def paintEvent(self, event):
        if self._gpu_surface is not None and self._gpu_surface.isVisible():
            return
        painter = QPainter(self)
        self._paint_photo(painter)
        painter.end()

    def _paint_photo(self, painter):
        painter.fillRect(self.rect(), ui_color("#18191c"))
        if self.image is not None and not self.image.isNull():
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.translate(self.image_rect().center())
            painter.rotate(self.rotation)
            size = self.source_size * self.zoom
            painter.drawImage(QRectF(-size.width() / 2, -size.height() / 2,
                                    size.width(), size.height()), self.image)
            painter.restore()
        elif self.message:
            painter.setPen(ui_color("#eeeeef"))
            painter.drawText(self.rect().adjusted(24, 24, -24, -24),
                             Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.message)

    def update(self, *args):
        super().update(*args)
        surface = getattr(self, "_gpu_surface", None)
        if surface is not None:
            surface.update()

    def set_gpu_enabled(self, enabled):
        from picklight.platform_effects import gpu_available
        enabled = enabled and gpu_available()
        if enabled and self._gpu_surface is None:
            self._gpu_surface = AcceleratedPhotoSurface(self)
            self._gpu_surface.setGeometry(self.rect())
            self._gpu_surface.show()
            self.loading_spinner.raise_()
        elif not enabled and self._gpu_surface is not None:
            surface, self._gpu_surface = self._gpu_surface, None
            surface.hide()
            surface.deleteLater()
        self.update()


from PySide6.QtOpenGLWidgets import QOpenGLWidget


class AcceleratedPhotoSurface(QOpenGLWidget):
    """Paint the same image geometry on the OpenGL engine; canvas owns input."""
    def __init__(self, canvas):
        super().__init__(canvas)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def paintGL(self):
        painter = QPainter(self)
        self.parentWidget()._paint_photo(painter)
        painter.end()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._check_context)

    def _check_context(self):
        if self.isVisible() and not self.isValid():
            self.parentWidget().set_gpu_enabled(False)
