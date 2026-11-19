"""Immersive review chrome and a cache-backed, horizontal photo strip."""

from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, QSize, QTimer, Qt, Signal
from PySide6.QtGui import QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QListView, QMenu, QPushButton,
    QSizePolicy, QStyle, QStyledItemDelegate, QVBoxLayout, QWidget,
)

from picklight.appearance import ui_color
from picklight.ui.common import (
    ElidedLabel, NAVIGATION_ICON_SIZE, TOOLBAR_BUTTON_SIZE, TOOLBAR_ICON_SIZE,
)
from picklight.ui.graphics import photo_state_pixmap, theme_icon, theme_rating_pixmap
from picklight.ui.inspector import InspectorFlagButton, StarRatingControl
from picklight.ui.toolbar import ToolbarIconButton
from picklight.viewer import LoupeCanvas


class ReviewStripDelegate(QStyledItemDelegate):
    def __init__(self, strip):
        super().__init__(strip)
        self.strip = strip
        self._gray_cache = {}

    def sizeHint(self, option, index):
        return self.strip.gridSize()

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(option.rect).adjusted(5, 7, -5, -9)
        clip = QPainterPath()
        clip.addRoundedRect(rect, 5, 5)
        painter.setClipPath(clip)
        painter.fillRect(rect, ui_color("#282a2e"))
        path = index.data(Qt.ItemDataRole.UserRole + 6)
        image = self.strip.loader.cached(Path(path), 420) if path else None
        state = index.data(Qt.ItemDataRole.UserRole + 7)
        current = index == self.strip.currentIndex()
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if image is not None and not image.isNull():
            if self.strip.grayscale:
                key = image.cacheKey()
                if key not in self._gray_cache:
                    if len(self._gray_cache) >= 32:
                        self._gray_cache.pop(next(iter(self._gray_cache)))
                    self._gray_cache[key] = image.convertToFormat(QImage.Format.Format_Grayscale8)
                image = self._gray_cache[key]
            scale = min(rect.width() / image.width(), rect.height() / image.height())
            target = QRectF(0, 0, image.width() * scale, image.height() * scale)
            target.moveCenter(rect.center())
            opacity = .35 if state == "reject" else 1 if current else .85 if hovered else .72
            painter.setOpacity(opacity)
            painter.drawImage(target, image)
            painter.setOpacity(1)
        painter.setClipping(False)
        border = "#ffaf22" if current else "#73757b" if hovered else "#303136"
        painter.setPen(QPen(ui_color(border), 1.5 if current else 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, 5, 5)
        rating = index.data(Qt.ItemDataRole.UserRole + 1) or 0
        if rating or state:
            badge = QRectF(rect.left() + 4, rect.bottom() - 18,
                           8 + (22 if rating else 0) + (12 if state else 0), 14)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(ui_color("#18191c"))
            painter.drawRoundedRect(badge, 3, 3)
            font = painter.font()
            font.setPixelSize(10)
            painter.setFont(font)
            x = badge.left() + 4
            if rating:
                painter.setPen(ui_color("#ffaf22"))
                painter.drawText(QRectF(x, badge.top(), 8, 14), Qt.AlignmentFlag.AlignCenter, str(rating))
                star = theme_rating_pixmap(True)
                painter.drawPixmap(QRectF(x + 9, badge.top() + 2, 10, 10), star, QRectF(star.rect()))
                x += 22
            if state:
                painter.drawPixmap(QPointF(x, badge.top() + 1), photo_state_pixmap(
                    state, 12, badge=True, device_ratio=painter.device().devicePixelRatioF()))
        painter.restore()


class ReviewStrip(QListView):
    """Share the gallery model; only decode thumbnails near the visible range."""
    def __init__(self, gallery, loader, parent):
        super().__init__(parent)
        self.loader = loader
        self.grayscale = False
        self.setObjectName("largeScreenStrip")
        self.setModel(gallery.model())
        self.setSelectionModel(gallery.selectionModel())
        self.setItemDelegate(ReviewStripDelegate(self))
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(False)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setGridSize(QSize(100, 68))
        self.setUniformItemSizes(True)
        self.setFixedHeight(76)
        self.setHorizontalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self.setEditTriggers(QListView.EditTrigger.NoEditTriggers)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMouseTracking(True)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.timeout.connect(self.request_visible)
        self.horizontalScrollBar().valueChanged.connect(self.schedule_refresh)
        self.model().modelReset.connect(self.schedule_refresh)
        self.model().rowsInserted.connect(self.schedule_refresh)
        self.model().rowsRemoved.connect(self.schedule_refresh)
        loader.ready.connect(self._preview_ready)

    def schedule_refresh(self, *_args):
        self._center_short_strip()
        if self.isVisible() and not self.refresh_timer.isActive():
            self.refresh_timer.start(0)

    def request_visible(self):
        if not self.isVisible():
            return
        count = self.model().rowCount()
        cell_width = self.gridSize().width()
        first = max(0, self.horizontalScrollBar().value() // cell_width - 2)
        last = min(count, first + self.viewport().width() // cell_width + 6)
        paths = [self.model().index(row, 0).data(Qt.ItemDataRole.UserRole + 6)
                 for row in range(first, last)]
        self.loader.keep_thumbnails(set(filter(None, paths)))
        for path in paths:
            if path and self.loader.cached(Path(path), 420) is None:
                self.loader.request(Path(path), 420)
        self.viewport().update()

    def _preview_ready(self, _path, width, _image):
        if width == 420 and self.isVisible():
            self.viewport().update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.schedule_refresh()

    def showEvent(self, event):
        super().showEvent(event)
        self.schedule_refresh()

    def _center_short_strip(self):
        width = self.model().rowCount() * self.gridSize().width()
        inset = max(0, (self.contentsRect().width() - width) // 2)
        if self.viewportMargins().left() != inset:
            self.setViewportMargins(inset, 0, inset, 0)

    def wheelEvent(self, event):
        delta = event.pixelDelta().x() or event.pixelDelta().y()
        if not delta:
            delta = (event.angleDelta().x() or event.angleDelta().y()) / 120 * self.gridSize().width()
        bar = self.horizontalScrollBar()
        bar.setValue(bar.value() - round(delta))
        event.accept()


class LargeScreenPage(QWidget):
    exitRequested = Signal()
    previousRequested = Signal()
    nextRequested = Signal()
    sourceRequested = Signal(str)
    decisionRequested = Signal(str)
    autoAdvanceChanged = Signal(bool)

    def __init__(self, gallery, loader):
        super().__init__()
        self.immersive = False
        self.canvas = LoupeCanvas()
        self.layout_box = QVBoxLayout(self)
        self.layout_box.setContentsMargins(0, 0, 0, 0)
        self.layout_box.setSpacing(0)
        self.layout_box.addWidget(self.canvas, 1)
        self.footer = QFrame(self, objectName="largeScreenFooter")
        self.footer.setFixedHeight(44)
        footer_layout = QHBoxLayout(self.footer)
        footer_layout.setContentsMargins(20, 0, 20, 0)
        self.status = ElidedLabel(objectName="largeScreenStatus")
        self.status.elide_mode = Qt.TextElideMode.ElideMiddle
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer_layout.addWidget(self.status)
        self.layout_box.addWidget(self.footer)
        self.strip = ReviewStrip(gallery, loader, self)
        self.layout_box.addWidget(self.strip)
        self.setStyleSheet("""
            QFrame#largeScreenFooter { background:#18191c; border:0; }
            QFrame#largeScreenDock, QFrame#largeScreenWing { background:transparent; border:0; }
            QFrame#largeScreenReview { background:#222327; border:1px solid #303136; border-radius:8px; }
            QLabel#largeScreenStatus { color:#85868d; background:transparent; font-size:11px; }
            QListView#largeScreenStrip { background:#18191c; border:0; padding:0 12px; }
        """)
        self.navigation, dock_layout = self._dock()
        self.browse_group, nav_layout = self._group()
        self.review_group, review_layout = self._group(review=True)
        self.view_group, view_layout = self._group()
        dock_layout.addWidget(self.browse_group, 0, 0, Qt.AlignmentFlag.AlignLeft)
        dock_layout.addWidget(self.review_group, 0, 1, Qt.AlignmentFlag.AlignCenter)
        dock_layout.addWidget(self.view_group, 0, 2, Qt.AlignmentFlag.AlignRight)
        dock_layout.setColumnStretch(0, 1)
        dock_layout.setColumnStretch(2, 1)
        self.previous_button = self._icon_button("toolbar.back", lambda: self.previousRequested.emit(),
                                                 tip="上一张", size=NAVIGATION_ICON_SIZE)
        nav_layout.addWidget(self.previous_button)
        self.counter = QLabel("0 / 0")
        self.counter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.counter.setFixedWidth(64)
        self.counter.setStyleSheet("color:#eeeeef;background:transparent;font-size:12px;")
        nav_layout.addWidget(self.counter)
        self.next_button = self._icon_button("toolbar.forward", lambda: self.nextRequested.emit(),
                                             tip="下一张", size=NAVIGATION_ICON_SIZE)
        nav_layout.addWidget(self.next_button)
        self.stars = StarRatingControl()
        review_layout.addWidget(self.stars)
        review_layout.addSpacing(8)
        self.keep_button = InspectorFlagButton("保留", "keep")
        self.reject_button = InspectorFlagButton("待删除", "reject")
        self.keep_button.clicked.connect(lambda: self.decisionRequested.emit("keep"))
        self.reject_button.clicked.connect(lambda: self.decisionRequested.emit("reject"))
        review_layout.addWidget(self.keep_button)
        review_layout.addWidget(self.reject_button)
        self.jpg_button = self._source_button("JPG", "jpg")
        self.raw_button = self._source_button("RAW", "raw")
        view_layout.addWidget(self.jpg_button)
        view_layout.addWidget(self.raw_button)
        view_layout.addSpacing(8)
        self.zoom_label = QPushButton("100%", objectName="largeScreenZoom")
        self.zoom_label.setStyleSheet("""
            QPushButton {color:#d5d7dc;background:transparent;border:0;border-radius:5px;font-size:11px;}
            QPushButton:hover {background:#303136;color:#F7F8F8;}
            QPushButton:checked {background:#333439;color:#F7F8F8;}
        """)
        self.zoom_label.setFixedHeight(26)
        self.zoom_label.setCheckable(True)
        self.zoom_label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.zoom_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.zoom_label.setToolTip("实际大小（1:1）")
        self.zoom_label.setAccessibleName("实际大小（1:1）")
        self.zoom_label.clicked.connect(self._toggle_actual_size)
        self.zoom_label.setFixedWidth(48)
        view_layout.addWidget(self.zoom_label)
        self.tools_button = self._icon_button("toolbar.more", self._show_tools, tip="查看与选片选项")
        view_layout.addWidget(self.tools_button)
        self.tools_menu = QMenu(self)
        self.fit_action = self.tools_menu.addAction("适应画布", self.canvas.fit_to_canvas)
        self.actual_action = self.tools_menu.addAction("实际大小（1:1）", lambda: self.canvas.set_zoom(1))
        self.fit_action.setCheckable(True)
        self.actual_action.setCheckable(True)
        self.zoom_in_action = self.tools_menu.addAction("放大", lambda: self.canvas.set_zoom(self.canvas.zoom * 1.25))
        self.zoom_out_action = self.tools_menu.addAction("缩小", lambda: self.canvas.set_zoom(self.canvas.zoom / 1.25))
        self.rotate_action = self.tools_menu.addAction("逆时针旋转 90°", self.canvas.rotate_counterclockwise)
        self.fit_action.setIcon(theme_icon("loupe.fit", 14))
        self.rotate_action.setIcon(theme_icon("loupe.rotate", TOOLBAR_ICON_SIZE.width()))
        self.tools_menu.addSeparator()
        self.auto_action = self.tools_menu.addAction("标记后自动下一张")
        self.auto_action.setCheckable(True)
        self.auto_action.toggled.connect(self.autoAdvanceChanged)
        self.strip_action = self.tools_menu.addAction("显示缩略图")
        self.strip_action.setCheckable(True)
        self.strip_action.setChecked(True)
        self.strip_action.toggled.connect(self._toggle_strip)
        self.pin_action = self.tools_menu.addAction("保持工具栏显示")
        self.pin_action.setCheckable(True)
        self.pin_action.toggled.connect(self.reveal_controls)
        self.tools_menu.addSeparator()
        self.exit_action = self.tools_menu.addAction("退出全屏浏览", lambda: self.exitRequested.emit())
        self.idle_timer = QTimer(self)
        self.idle_timer.setSingleShot(True)
        self.idle_timer.setInterval(2600)
        self.idle_timer.timeout.connect(self._hide_controls)
        self.canvas.zoomChanged.connect(self._sync_zoom_controls)
        for widget in (self.canvas, self.strip.viewport(), self.status, self.footer):
            widget.setMouseTracking(True)
            widget.installEventFilter(self)
        for child in [self.navigation, *self.navigation.findChildren(QWidget)]:
            child.setMouseTracking(True)
            child.installEventFilter(self)
        self.set_immersive(False)

    def _icon_button(self, asset, callback, *, tip, size=TOOLBAR_ICON_SIZE):
        button = ToolbarIconButton()
        button.setObjectName("imageAction")
        button.setFixedSize(TOOLBAR_BUTTON_SIZE)
        button.setIcon(theme_icon(asset, size.width()))
        button.setIconSize(size)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip(tip)
        button.setAccessibleName(tip)
        button.clicked.connect(callback)
        return button

    def _source_button(self, title, source):
        button = QPushButton(title, objectName="source")
        button.setFixedSize(35, 19)
        button.setCheckable(True)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip(f"查看 {title} 原图")
        button.setAccessibleName(f"查看 {title} 原图")
        button.clicked.connect(lambda: self.sourceRequested.emit(source))
        return button

    def _dock(self):
        frame = QFrame(self.footer, objectName="largeScreenDock")
        layout = QGridLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(20)
        return frame, layout

    def _group(self, *, review=False):
        frame = QFrame(self.navigation, objectName="largeScreenReview" if review else "largeScreenWing")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(10 if review else 0, 4, 10 if review else 0, 4)
        layout.setSpacing(4)
        return frame, layout

    def _show_tools(self):
        self.tools_menu.popup(self.tools_button.mapToGlobal(
            QPoint(self.tools_button.width() - self.tools_menu.sizeHint().width(),
                   -self.tools_menu.sizeHint().height() - 12)))

    def set_immersive(self, active):
        self.immersive = active
        self.footer.hide()
        self.strip.setVisible(active and self.strip_action.isChecked())
        self.navigation.hide()
        self.idle_timer.stop()

    def _toggle_strip(self, checked):
        self.strip.setVisible(self.immersive and checked)
        self.reveal_controls()

    def _toggle_actual_size(self):
        if not self.canvas.fitted and abs(self.canvas.zoom - 1) < .001:
            self.canvas.fit_to_canvas()
        else:
            self.canvas.set_zoom(1)

    def _sync_zoom_controls(self, zoom):
        actual = not self.canvas.fitted and abs(zoom - 1) < .001
        self.zoom_label.setText(f"{zoom * 100:.0f}%" if zoom >= .1 else f"{zoom * 100:.1f}%")
        self.zoom_label.setChecked(actual)
        self.zoom_label.setToolTip("适应画布" if actual else "实际大小（1:1）；再次点击适应画布")
        self.zoom_label.setAccessibleName("适应画布" if actual else "实际大小（1:1）")
        self.fit_action.setChecked(self.canvas.fitted)
        self.actual_action.setChecked(actual)
        self.zoom_out_action.setEnabled(zoom > .05)
        self.zoom_in_action.setEnabled(zoom < 8)

    def reveal_controls(self):
        if not self.immersive or self.footer.isHidden():
            return
        self.navigation.show()
        self.navigation.raise_()
        self.status.hide()
        self._position_controls()
        if self.pin_action.isChecked():
            self.idle_timer.stop()
        else:
            self.idle_timer.start()

    def _hide_controls(self):
        if not self.immersive:
            return
        if self.pin_action.isChecked():
            return
        if (self.footer.underMouse() or self.strip.underMouse()
                or QApplication.activeModalWidget() or QApplication.activePopupWidget()):
            self.idle_timer.start()
            return
        self.navigation.hide()
        self.status.show()

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.MouseMove, QEvent.Type.Enter, QEvent.Type.MouseButtonPress):
            if watched is not self.canvas:
                self.reveal_controls()
            elif (event.type() == QEvent.Type.MouseMove
                  and event.position().y() >= self.canvas.height() - 24):
                self.reveal_controls()
        elif watched is self.footer and event.type() == QEvent.Type.Resize:
            self._position_controls()
        return False

    def _position_controls(self):
        if not self.immersive:
            return
        self.navigation.layout().activate()
        width = min(1040, max(0, self.footer.width() - 48))
        self.navigation.setGeometry((self.footer.width() - width) // 2, 3, width, 38)
        self.navigation.layout().activate()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_controls()

    def hideEvent(self, event):
        self.idle_timer.stop()
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self.reveal_controls()
