"""Photo grid interactions and thumbnail delegates."""

from __future__ import annotations

from math import exp
from pathlib import Path
from time import monotonic

from PySide6.QtCore import QEvent, QItemSelection, QItemSelectionModel, QMimeData, QPoint, QRectF, QSize, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QColor, QDrag, QFont, QIcon, QImage, QKeySequence, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QStyle,
    QStyledItemDelegate,
    QWidget,
)

from picklight.appearance import ui_color

from picklight.paths import asset_path
from picklight.ui.graphics import paint_photo_state, theme_rating_pixmap


class PhotoGridHeader(QWidget):
    def __init__(self, grid):
        super().__init__()
        self.grid = grid
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(event.rect(), ui_color("#18191c"))
        painter.end()

    def wheelEvent(self, event):
        self.grid.wheelEvent(event)

    def install_wheel_filters(self):
        for widget in self.findChildren(QWidget):
            widget.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Wheel:
            self.wheelEvent(event)
            return True
        return super().eventFilter(watched, event)


class PhotoGrid(QListWidget):
    resized = Signal()
    zoomStepsRequested = Signal(int)
    middleClicked = Signal(object)

    def setCurrentRow(self, row, command=None):
        # Navigation selects one photo; explicit multi-selection uses the model.
        if command is None:
            command = QItemSelectionModel.SelectionFlag.ClearAndSelect
        super().setCurrentRow(row, command)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.dim_rejected = True
        self._content_height = None
        # Keep the gap below the filters outside the scrolling photo content.
        self.setViewportMargins(0, 6, 0, 0)
        self._pressed_item: QListWidgetItem | None = None
        self._press_position = QPoint()
        self._copy_drag_armed = False
        self._selection_anchor_row = 0
        self._range_press = False
        self.stack_addition = None
        self.select_all_shortcut = None
        self._hold_timer = QTimer(self)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.setInterval(320)
        self._hold_timer.timeout.connect(self._arm_copy_drag)
        self.header_widget = None
        self._wheel_target = 0
        self._wheel_updating = False
        self._wheel_position = 0.0
        self._wheel_velocity = 0.0
        self._zoom_wheel_remainder = 0.0
        self.ctrl_wheel_zoom = True
        self.hover_zoom_enabled = False
        self.hover_grayscale = False
        self._hover_item = None
        self._hover_path = None
        self._hover_loader = None
        self._hover_scrim = QWidget(self.viewport())
        self._hover_scrim.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._hover_scrim.setStyleSheet("background: rgba(0, 0, 0, 110);")
        self._hover_scrim.hide()
        self._hover_preview = QLabel(self.viewport())
        self._hover_preview.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._hover_preview.setStyleSheet("background: #202124; border: 3px solid #494a4e; border-radius: 6px;")
        self._hover_preview.hide()
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(200)
        self._hover_timer.timeout.connect(self._show_hover_preview)
        self._wheel_timer = QTimer(self)
        self._wheel_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._wheel_timer.setInterval(16)
        self._wheel_timer.timeout.connect(self._advance_wheel)
        self.verticalScrollBar().valueChanged.connect(self._scroll_value_changed)
        self.verticalScrollBar().sliderPressed.connect(self._stop_wheel)

    def set_content_height(self, height):
        self._content_height = height
        self.updateGeometries()

    def updateGeometries(self):
        # Items are positioned by the gallery's grid/waterfall layout. QListView's
        # automatic content bounds can disagree and repeatedly hide the scrollbar,
        # resizing the viewport and starting another layout in a feedback loop.
        height = getattr(self, "_content_height", None)
        if height is None:
            super().updateGeometries()
            return
        bar = self.verticalScrollBar()
        bar.setPageStep(self.viewport().height())
        bar.setRange(0, max(0, height - self.viewport().height()))
        self.horizontalScrollBar().setRange(0, 0)

    def _stop_wheel(self):
        self._wheel_timer.stop()
        self._wheel_target = self.verticalScrollBar().value()
        self._wheel_position = float(self._wheel_target)
        self._wheel_velocity = 0.0

    def _advance_wheel(self):
        now = monotonic()
        elapsed = min(0.05, max(0.001, now - self._wheel_last_tick))
        self._wheel_last_tick = now
        bar = self.verticalScrollBar()
        self._wheel_target = max(bar.minimum(), min(bar.maximum(), self._wheel_target))
        # Analytic critically damped spring: retarget without restarting velocity.
        omega = 40.0
        displacement = self._wheel_position - self._wheel_target
        coefficient = self._wheel_velocity + omega * displacement
        decay = exp(-omega * elapsed)
        self._wheel_position = self._wheel_target + (displacement + coefficient * elapsed) * decay
        self._wheel_velocity = (self._wheel_velocity - omega * coefficient * elapsed) * decay
        finished = abs(self._wheel_position - self._wheel_target) < 0.5 and abs(self._wheel_velocity) < 5
        self._wheel_updating = True
        try:
            bar.setValue(self._wheel_target if finished else round(self._wheel_position))
        finally:
            self._wheel_updating = False
        if finished:
            self._stop_wheel()

    def _scroll_value_changed(self, value):
        if not self._wheel_updating:
            self._stop_wheel()

    def wheelEvent(self, event):
        self._hide_hover_preview()
        if self.ctrl_wheel_zoom and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            angle = event.angleDelta().y()
            pixels = event.pixelDelta().y()
            self._zoom_wheel_remainder += angle / 120 if angle else pixels / 60
            steps = int(self._zoom_wheel_remainder)
            if steps:
                self._zoom_wheel_remainder -= steps
                self.zoomStepsRequested.emit(steps)
            event.accept()
            return
        bar = self.verticalScrollBar()
        pixels = event.pixelDelta().y()
        angle = event.angleDelta().y()
        if not pixels and not angle:
            super().wheelEvent(event)
            return
        if pixels or event.phase() != Qt.ScrollPhase.NoScrollPhase:
            self._stop_wheel()
            distance = pixels if pixels else angle / 120 * 96
            bar.setValue(round(bar.value() - distance))
            self._stop_wheel()
        else:
            distance = -angle / 120 * min(128, max(64, QApplication.wheelScrollLines() * 32))
            running = self._wheel_timer.isActive()
            base = self._wheel_target if running else bar.value()
            if running and (self._wheel_target - bar.value()) * distance < 0:
                base = bar.value()
                self._wheel_velocity = 0.0
            self._wheel_target = max(bar.minimum(), min(bar.maximum(), round(base + distance)))
            if not running and self._wheel_target != bar.value():
                self._wheel_position = float(bar.value())
                self._wheel_velocity = 0.0
                self._wheel_last_tick = monotonic()
                self._wheel_timer.start()
        event.accept()

    def scrollContentsBy(self, dx, dy):
        super().scrollContentsBy(dx, dy)
        # The viewport scrolls its child widgets too; synchronize after that move.
        self._position_header()

    def set_header(self, widget):
        self.header_widget = widget
        widget.setParent(self.viewport())
        widget.install_wheel_filters()
        self._position_header()

    def _position_header(self, _value=None):
        if getattr(self, "header_widget", None) is not None:
            self.header_widget.move(0, -self.verticalScrollBar().value())

    def _arm_copy_drag(self):
        if self._pressed_item is not None:
            self._copy_drag_armed = True
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)

    def _reset_copy_drag(self):
        self._hold_timer.stop()
        self._pressed_item = None
        self._copy_drag_armed = False
        self.viewport().unsetCursor()

    def mousePressEvent(self, event):
        self._hide_hover_preview()
        self._reset_copy_drag()
        self._range_press = False
        self.stack_addition = None
        item = self.itemAt(event.position().toPoint())
        if event.button() == Qt.MouseButton.MiddleButton:
            if item is not None:
                self.setCurrentItem(item)
                self.middleClicked.emit(item)
            event.accept()
            return
        if event.button() == Qt.MouseButton.RightButton:
            if item is not None:
                if not item.isSelected():
                    self.setCurrentRow(self.row(item))
                else:
                    self.selectionModel().setCurrentIndex(self.indexFromItem(item),
                                                          QItemSelectionModel.SelectionFlag.NoUpdate)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and item is not None:
            row = self.row(item)
            if (event.modifiers() & Qt.KeyboardModifier.ControlModifier
                    and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier and not item.isSelected()):
                self.stack_addition = item.data(Qt.ItemDataRole.UserRole + 6)
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                first, last = sorted((max(0, min(self.count() - 1, self._selection_anchor_row)), row))
                flags = (QItemSelectionModel.SelectionFlag.Select if
                         event.modifiers() & Qt.KeyboardModifier.ControlModifier else
                         QItemSelectionModel.SelectionFlag.ClearAndSelect)
                self.selectionModel().select(QItemSelection(self.model().index(first, 0),
                                                           self.model().index(last, 0)), flags)
                self.selectionModel().setCurrentIndex(self.indexFromItem(item),
                                                      QItemSelectionModel.SelectionFlag.NoUpdate)
                self._range_press = True
                event.accept()
                return
            self._selection_anchor_row = row
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed_item = self.itemAt(event.position().toPoint())
            self._press_position = event.position().toPoint()
            if self._pressed_item is not None:
                self._hold_timer.start()

    def mouseMoveEvent(self, event):
        if not event.buttons() and self.hover_zoom_enabled:
            item = self.itemAt(event.position().toPoint())
            if item is None or not self._hover_lens_rect(item).contains(event.position().toPoint()):
                item = None
            if item is not self._hover_item:
                self._hide_hover_preview()
                self._hover_item = item
                if item is not None:
                    self._hover_timer.start()
            self.viewport().setCursor(Qt.CursorShape.PointingHandCursor if item else Qt.CursorShape.ArrowCursor)
        else:
            self._hide_hover_preview()
        if event.buttons() & Qt.MouseButton.RightButton and not event.buttons() & Qt.MouseButton.LeftButton:
            event.accept()
            return
        if (self._copy_drag_armed and self._pressed_item is not None
                and event.buttons() & Qt.MouseButton.LeftButton
                and (event.position().toPoint() - self._press_position).manhattanLength()
                >= QApplication.startDragDistance()):
            item = self._pressed_item
            self._reset_copy_drag()
            drag = self._create_copy_drag(item)
            if drag is not None:
                drag.exec(Qt.DropAction.CopyAction)
            return
        if self._pressed_item is not None and event.buttons() & Qt.MouseButton.LeftButton:
            event.accept()
            return
        super().mouseMoveEvent(event)

    def _hide_hover_preview(self):
        self._hover_timer.stop()
        self._hover_preview.hide()
        self._hover_scrim.hide()
        self._hover_item = None
        self._hover_path = None

    def set_hover_loader(self, loader):
        self._hover_loader = loader
        loader.ready.connect(self._hover_image_ready)

    def _hover_lens_rect(self, item):
        cell = self.visualItemRect(item)
        size = item.data(Qt.ItemDataRole.UserRole + 4)
        if not isinstance(size, QSize):
            size = self.iconSize()
        x = cell.x() + (cell.width() - size.width()) / 2
        y = cell.y() + 4
        return QRectF(x + size.width() - 24, y + size.height() - 24, 24, 24).toRect()

    def _show_hover_preview(self):
        item = self._hover_item
        if not self.hover_zoom_enabled or item is None or item.icon().isNull():
            return
        self._hover_path = item.data(Qt.ItemDataRole.UserRole + 6)
        if self._hover_path and self._hover_loader is not None:
            path = Path(self._hover_path)
            full = self._hover_loader.cached(path, 2200)
            cached = self._hover_loader.cached(path, 900)
            thumbnail = self._hover_loader.cached(path, 420)
            if full is not None:
                self._set_hover_image(full)
            elif cached is not None:
                self._set_hover_image(cached)
            elif thumbnail is not None:
                self._set_hover_image(thumbnail)
            if full is None and cached is None:
                self._hover_loader.request(path, 900)
            return
        source = item.icon().pixmap(QSize(900, 900))
        if not source.isNull():
            self._set_hover_pixmap(source)

    def _hover_image_ready(self, path, width, image):
        if width != 900 or path != self._hover_path or self._hover_item is None:
            return
        try:
            if self.row(self._hover_item) < 0:
                self._hide_hover_preview()
                return
        except RuntimeError:
            self._hide_hover_preview()
            return
        self._set_hover_image(image)

    def _set_hover_image(self, image):
        if self.hover_grayscale:
            image = image.convertToFormat(QImage.Format.Format_Grayscale8)
        self._set_hover_pixmap(QPixmap.fromImage(image))

    def _set_hover_pixmap(self, source):
        bounds = QSize(min(900, max(80, self.viewport().width() - 28)),
                       min(900, max(80, self.viewport().height() - 28)))
        pixmap = source.scaled(bounds, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
        self._hover_preview.setPixmap(pixmap)
        self._hover_preview.resize(pixmap.width() + 6, pixmap.height() + 6)
        rect = self.visualItemRect(self._hover_item)
        right_space = self.viewport().width() - rect.right()
        left_space = rect.left()
        x = rect.right() + 12 if right_space >= left_space else rect.left() - self._hover_preview.width() - 12
        x = min(max(10, x), max(10, self.viewport().width() - self._hover_preview.width() - 10))
        y = min(max(10, rect.top()), max(10, self.viewport().height() - self._hover_preview.height() - 10))
        self._hover_scrim.setGeometry(self.viewport().rect())
        self._hover_scrim.raise_()
        self._hover_scrim.show()
        self._hover_preview.move(x, y)
        self._hover_preview.raise_()
        self._hover_preview.show()

    def leaveEvent(self, event):
        self._hide_hover_preview()
        self.viewport().unsetCursor()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        self._reset_copy_drag()
        if event.button() == Qt.MouseButton.RightButton:
            event.accept()
            return
        if self._range_press and event.button() == Qt.MouseButton.LeftButton:
            self._range_press = False
            item = self.itemAt(event.position().toPoint())
            if item is not None:
                self.itemClicked.emit(item)
            self.stack_addition = None
            event.accept()
            return
        super().mouseReleaseEvent(event)
        self.stack_addition = None

    def mouseDoubleClickEvent(self, event):
        self._reset_copy_drag()
        item = self.itemAt(event.position().toPoint())
        if event.button() == Qt.MouseButton.LeftButton and item is not None:
            self.setCurrentItem(item)
            self.itemDoubleClicked.emit(item)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _create_copy_drag(self, item: QListWidgetItem) -> QDrag | None:
        source = item.data(Qt.ItemDataRole.UserRole + 6)
        if not source or not Path(source).is_file():
            return None
        drag = QDrag(self)
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(source))])
        drag.setMimeData(mime)
        icon = item.icon()
        if not icon.isNull():
            preview = icon.pixmap(QSize(108, 108))
            drag.setPixmap(preview)
            drag.setHotSpot(QPoint(preview.width() // 2, preview.height() // 2))
        return drag

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_header()
        self.resized.emit()

    def keyPressEvent(self, event):
        if self.select_all_shortcut is not None and event.matches(QKeySequence.StandardKey.SelectAll):
            if self.select_all_shortcut == "Ctrl+A":
                self.selectAll()
            event.accept()
            return
        super().keyPressEvent(event)


class EmptyFolderIllustration(QLabel):
    def __init__(self):
        super().__init__()
        illustration = QPixmap(asset_path("empty.folder"))
        illustration.setDevicePixelRatio(2)
        self.setPixmap(illustration)
        self.setFixedSize(352, 144)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)


class PhotoGridDelegate(QStyledItemDelegate):
    renameRequested = Signal(str, str)

    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        editor.setObjectName("photoNameEditor")
        editor.setAlignment(Qt.AlignmentFlag.AlignCenter)
        editor.setAccessibleName("重命名照片")
        return editor

    def setEditorData(self, editor, index):
        editor.setText(Path(index.data(Qt.ItemDataRole.UserRole + 6)).stem)
        editor.selectAll()

    def setModelData(self, editor, model, index):
        # File names change only after the file operation succeeds and is rescanned.
        self.renameRequested.emit(str(index.data(Qt.ItemDataRole.UserRole)), editor.text())

    def updateEditorGeometry(self, editor, option, index):
        size = index.data(Qt.ItemDataRole.UserRole + 4)
        if not isinstance(size, QSize):
            size = self.parent().iconSize()
        editor.setGeometry(option.rect.adjusted(3, size.height() + 10, -3,
                                                size.height() + 30 - option.rect.height()))

    def paint(self, painter, option, index):
        grid = self.parent()
        image_size = index.data(Qt.ItemDataRole.UserRole + 4)
        if not isinstance(image_size, QSize):
            image_size = grid.iconSize()
        cell = option.rect
        image_rect = QRectF(cell.x() + (cell.width() - image_size.width()) / 2,
                            cell.y() + 4, image_size.width(), image_size.height())
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if option.state & QStyle.StateFlag.State_Selected:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(ui_color("#3297ff"), 2))
            painter.drawRoundedRect(image_rect.adjusted(-2, -2, 2, 2), 9, 9)
        elif option.state & QStyle.StateFlag.State_MouseOver:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(ui_color(QColor(255, 255, 255, 50)), 1))
            painter.drawRoundedRect(image_rect.adjusted(-2, -2, 2, 2), 9, 9)
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if isinstance(icon, QIcon):
            icon.paint(painter, image_rect.toRect())
        state = str(index.data(Qt.ItemDataRole.UserRole + 7) or "")
        if state == "reject" and grid.dim_rejected and not option.state & QStyle.StateFlag.State_MouseOver:
            painter.fillRect(image_rect, QColor(0, 0, 0, 145))
        paint_photo_state(painter, image_rect, state)
        if (grid.hover_zoom_enabled and option.state & QStyle.StateFlag.State_MouseOver
                and isinstance(icon, QIcon) and not icon.isNull()):
            QIcon(asset_path("gallery.hover.zoom")).paint(
                painter, QRectF(image_rect.right() - 24, image_rect.bottom() - 24, 24, 24).toRect())
        caption = QRectF(cell.x() + 3, image_rect.bottom() + 7,
                         cell.width() - 6, 18)
        rating = max(0, min(5, int(index.data(Qt.ItemDataRole.UserRole + 1) or 0)))
        font = painter.font()
        font.setPixelSize(13)
        font.setWeight(QFont.Weight.Medium)
        painter.setFont(font)
        painter.setPen(ui_color("#ffffff"))
        name = painter.fontMetrics().elidedText(
            str(index.data(Qt.ItemDataRole.DisplayRole) or ""),
            Qt.TextElideMode.ElideMiddle, int(caption.width()))
        painter.drawText(caption, Qt.AlignmentFlag.AlignCenter, name)
        star_y = round(caption.bottom() + 10)
        for star in range(5):
            pixmap = theme_rating_pixmap(star < rating)
            painter.drawPixmap(round(cell.center().x() + (star - 2) * 11 - 6), star_y - 7, pixmap)
        painter.restore()
