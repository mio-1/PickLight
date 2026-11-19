"""Zoomable photo canvas for the in-window image viewer."""

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, QSize, QSizeF, Qt, Signal, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QTransform
from PySide6.QtWidgets import QSizePolicy, QWidget

from picklight.appearance import ui_color

from picklight.ui.cursors import system_cursor_size, theme_cursor
from picklight.ui.loading import LoadingSpinner


class NavigatorOverlay(QWidget):
    """A small overview of the visible portion of a zoomed photo."""

    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvas = canvas
        self.preview = None
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def refresh_preview(self):
        image = self.canvas.display_image()
        if image is None or image.isNull():
            self.preview = None
            return
        preview = image.scaled(QSize(160, 120), Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
        self.preview = preview.transformed(QTransform().rotate(self.canvas.rotation))

    def paintEvent(self, _event):
        if self.preview is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        outer = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        clip = QPainterPath()
        clip.addRoundedRect(outer, 6, 6)
        painter.setClipPath(clip)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 102))
        frame = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        image_rect = QRectF(self.preview.rect())
        scale = min(frame.width() / image_rect.width(), frame.height() / image_rect.height())
        image_rect.setSize(image_rect.size() * scale)
        image_rect.moveCenter(frame.center())
        painter.drawImage(image_rect, self.preview)
        photo = self.canvas.image_rect()
        if photo.width() > 0 and photo.height() > 0:
            visible = QRectF(self.canvas.rect()).intersected(photo)
            region = QRectF(
                image_rect.left() + (visible.left() - photo.left()) / photo.width() * image_rect.width(),
                image_rect.top() + (visible.top() - photo.top()) / photo.height() * image_rect.height(),
                visible.width() / photo.width() * image_rect.width(),
                visible.height() / photo.height() * image_rect.height())
            region = region.intersected(image_rect)
            if not region.isEmpty():
                region.setWidth(max(8, region.width()))
                region.setHeight(max(8, region.height()))
                region = region.intersected(image_rect)
                shade = QPainterPath()
                shade.addRect(image_rect)
                clear = QPainterPath()
                clear.addRoundedRect(region, 6, 6)
                painter.fillPath(shade.subtracted(clear), QColor(0, 0, 0, 153))
                painter.setPen(QPen(QColor(255, 255, 255), 1))
                painter.drawRoundedRect(region.adjusted(.5, .5, -.5, -.5), 6, 6)
        painter.setClipping(False)
        painter.setPen(QPen(QColor(0, 0, 0, 77), 1))
        painter.drawRoundedRect(outer, 6, 6)
        painter.end()


class LoupeCanvas(QWidget):
    zoomChanged = Signal(float)
    exitRequested = Signal()
    wheelNavigateRequested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.image = None
        self.grayscale = False
        self._grayscale_image = None
        self._gpu_surface = None
        self.loading_spinner = LoadingSpinner(self)
        self.message = ""
        self.source_size = QSizeF()
        self.image_key = None
        self.rotation = 0
        self.zoom = 1.0
        self.pan = QPointF()
        self.fitted = True
        self.fill_canvas = False
        self.wheel_action = "zoom"
        self._dragging = False
        self._hand_pressed = False
        self._last_drag_position = QPointF()
        self.decision_state = ""
        self.navigator = NavigatorOverlay(self)
        self.navigator.hide()
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
            cursor = theme_cursor("cursor.grabbing" if self._hand_pressed else "cursor.grab", size,
                                  QPoint(round(size / 2), round(size * 18 / 32)), ratio, crisp=True)
            self.setCursor(cursor)
            # Child overlays sit above the canvas and can otherwise expose the
            # platform arrow cursor while the canvas is showing its themed hand.
            for overlay in (self._gpu_surface, self.loading_spinner, self.navigator):
                if overlay is not None:
                    overlay.setCursor(cursor)
            self._hand_cursor_signature = signature

    def begin_image(self, key, source_size=QSize()):
        if key != self.image_key:
            previous_zoom = self.zoom
            previous_fitted = self.fitted
            self.image_key = key
            self.rotation = 0
            self.image = None
            self._grayscale_image = None
            self.source_size = QSizeF(source_size) if source_size.isValid() else QSizeF()
            self.pan = QPointF()
            self.fitted = previous_fitted if getattr(self, "remember_zoom", False) else True
            if not self.fitted:
                self.zoom = previous_zoom
            self._dragging = False
            self._hand_pressed = False
            self._refresh_hand_cursor()
            self.navigator.hide()
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
        self._grayscale_image = None
        self.navigator.refresh_preview()
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
        self._grayscale_image = None
        self.navigator.refresh_preview()
        self.navigator.hide()
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

    def display_image(self):
        if self.image is None or not self.grayscale:
            return self.image
        if self._grayscale_image is None:
            self._grayscale_image = self.image.convertToFormat(
                QImage.Format.Format_Grayscale8).convertToFormat(QImage.Format.Format_RGB32)
        return self._grayscale_image

    def set_grayscale(self, enabled):
        if self.grayscale == bool(enabled):
            return
        self.grayscale = bool(enabled)
        self.navigator.refresh_preview()
        self.update()

    def rotate_clockwise(self):
        self._rotate_by(90)

    def rotate_counterclockwise(self):
        self._rotate_by(-90)

    def _rotate_by(self, degrees):
        if self.image is None:
            return
        self.rotation = (self.rotation + degrees) % 360
        self.navigator.refresh_preview()
        if self.fitted:
            self.fit_to_canvas()
        else:
            self._changed()

    def fit_zoom(self):
        size = self.display_source_size()
        if size.isEmpty():
            return 1.0
        if self.fill_canvas:
            return max(0.05, min(8.0, min(self.width() / size.width(),
                                           self.height() / size.height())))
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
        self._update_navigator()
        self.update()
        if zoom_changed:
            self.zoomChanged.emit(self.zoom)

    def _update_navigator(self):
        photo = self.image_rect() if self.image is not None else QRectF()
        needed = (self.image is not None and not self.image.isNull() and
                  (photo.width() > self.width() + 2 or photo.height() > self.height() + 2 or
                   photo.left() < -2 or photo.top() < -2 or
                   photo.right() > self.width() + 2 or photo.bottom() > self.height() + 2))
        if not needed:
            self.navigator.hide()
            return
        preview = self.navigator.preview
        if preview is None:
            return
        width = height = 120
        self.navigator.setGeometry(self.width() - width - 16, self.height() - height - 16,
                                   width, height)
        self.navigator.show()
        self.navigator.raise_()
        self.navigator.update()

    def wheelEvent(self, event):
        if self.image is not None:
            delta = event.angleDelta().y() or event.pixelDelta().y()
            if delta:
                if self.wheel_action == "pan":
                    self.pan += QPointF(0, delta * 0.5)
                    self.fitted = False
                    self._changed(zoom_changed=False)
                elif self.wheel_action == "navigate":
                    self.wheelNavigateRequested.emit(1 if delta < 0 else -1)
                else:
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
        else:
            self._update_navigator()

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
                                    size.width(), size.height()), self.display_image())
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
            self._gpu_surface.setCursor(self.cursor())
            self._gpu_surface.setGeometry(self.rect())
            self._gpu_surface.show()
            self.loading_spinner.raise_()
            self.navigator.raise_()
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
