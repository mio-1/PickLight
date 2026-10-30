"""Photo and folder inspector controls."""

from __future__ import annotations

from picklight.ui.loading import LoadingSpinner

from pathlib import Path
from math import ceil

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, QSize, QUrl, QVariantAnimation, Qt, Signal
from PySide6.QtGui import QDesktopServices, QFont, QPainter, QPainterPath, QPen, QTextOption
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QLabel, QPushButton, QSizePolicy, QTextEdit, QVBoxLayout, QWidget

from picklight.appearance import ui_color

from picklight.paths import asset_path
from picklight.ui.graphics import star_path


class PhotoStackPreview(QWidget):
    def __init__(self):
        super().__init__()
        self.paths = ()
        self.selection_order = []
        self.images = {}
        self.incoming = None
        self.drop_progress = 1.0
        self.drop_animation = QVariantAnimation(self)
        self.drop_animation.setDuration(280)
        self.drop_animation.setStartValue(0.0)
        self.drop_animation.setEndValue(1.0)
        self.drop_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.drop_animation.valueChanged.connect(self._advance_drop)
        self.drop_animation.finished.connect(self._finish_drop)
        self.setFixedHeight(238)

    def set_paths(self, paths, incoming=None):
        chosen, previous = set(paths), set(self.selection_order)
        added = [path for path in paths if path not in previous]
        self.selection_order = [path for path in self.selection_order if path in chosen] + added
        if incoming in added:
            self.selection_order.remove(incoming)
            self.selection_order.append(incoming)
        visible = tuple(self.selection_order[-8:])
        if visible == self.paths:
            return
        self.drop_animation.stop()
        self.paths = visible
        self.images = {path: image for path, image in self.images.items() if path in self.paths}
        self.incoming = incoming if incoming in added and len(paths) > 1 else None
        self.drop_progress = 0.0 if self.incoming else 1.0
        if self.incoming:
            self.drop_animation.start()
        self.update()

    def _advance_drop(self, value):
        self.drop_progress = float(value)
        self.update()

    def _finish_drop(self):
        self.incoming = None
        self.drop_progress = 1.0
        self.update()

    def set_image(self, path, image):
        if path in self.paths:
            self.images[path] = image
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        width = min(164, self.width() - 34)
        for index, path in enumerate(self.paths):
            painter.save()
            painter.translate(self.width() / 2 + (-8, 8, -5, 10, -10, 5, -7, 4)[index],
                              116 + (index - (len(self.paths) - 1) / 2) * 4)
            if path == self.incoming:
                remaining = 1 - self.drop_progress
                painter.translate((self.width() + 60) * remaining,
                                  (self.height() + 60) * remaining)
                painter.scale(1 + .12 * remaining, 1 + .12 * remaining)
                painter.rotate(14 * remaining)
            painter.rotate((-8, 7, -5, 6, -4, 4, -3, 2)[index])
            image = self.images.get(path)
            size = (image.size().scaled(QSize(width, 184), Qt.AspectRatioMode.KeepAspectRatio)
                    if image is not None and not image.isNull() else QSize(width, 114))
            rect = QRectF(-size.width() / 2, -size.height() / 2, size.width(), size.height())
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(ui_color("#131416"))
            painter.drawRoundedRect(rect, 5, 5)
            if image is not None and not image.isNull():
                clip = QPainterPath()
                clip.addRoundedRect(rect, 5, 5)
                painter.setClipPath(clip)
                painter.drawImage(rect, image)
            painter.restore()
        painter.end()


class FolderDescriptionEdit(QTextEdit):
    editingFinished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptRichText(False)
        self.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTabChangesFocus(True)
        self.document().setDocumentMargin(0)
        self.setFixedHeight(32)
        self.document().documentLayout().documentSizeChanged.connect(self._fit_height)

    def text(self):
        return self.toPlainText()

    def setText(self, text):
        if text != self.toPlainText():
            self.setPlainText(text)
        self._fit_height()

    def _fit_height(self, _size=None):
        height = ceil(self.document().size().height()) + 14
        self.setFixedHeight(max(32, min(180, height)))
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded
                                        if height > 180 else Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_height()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.editingFinished.emit()


class FolderPathLink(QWidget):
    clicked = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("folderPathLink")
        self.setFixedHeight(42)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName("打开照片所在文件夹")
        self.path: Path | None = None
        rows = QVBoxLayout(self)
        rows.setContentsMargins(0, 2, 0, 2)
        rows.setSpacing(0)
        self.folder_label = QLabel("—", objectName="pathFolder")
        self.file_label = QLabel("", objectName="pathFile")
        for item in (self.folder_label, self.file_label):
            item.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            item.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            item.setMinimumWidth(0)
            item.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            rows.addWidget(item)

    def set_path(self, path: Path | None):
        self.path = path
        self.setToolTip(str(path) if path else "")
        self._update_text()

    def _update_text(self):
        if self.path is None:
            self.folder_label.setText("—")
            self.file_label.clear()
            return
        width = max(1, self.width())
        metrics = self.folder_label.fontMetrics()
        directory = str(self.path.parent).replace("/", "\\").rstrip("\\")
        full = directory + "\\"
        if metrics.horizontalAdvance(full) <= width:
            shown = full
        else:
            tail = ""
            for part in reversed(directory.split("\\")):
                candidate = part + "\\" + tail
                if metrics.horizontalAdvance("...\\" + candidate) > width:
                    break
                tail = candidate
            if not tail:
                available = max(1, width - metrics.horizontalAdvance("...\\\\"))
                tail = metrics.elidedText(directory.split("\\")[-1],
                                          Qt.TextElideMode.ElideRight, available) + "\\"
            shown = "...\\" + tail
        self.folder_label.setText(shown)
        self.file_label.setText(self.file_label.fontMetrics().elidedText(
            self.path.name, Qt.TextElideMode.ElideMiddle, width))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_text()

    def enterEvent(self, event):
        for item in (self.folder_label, self.file_label):
            font = item.font()
            font.setUnderline(True)
            item.setFont(font)
        self._update_text()
        super().enterEvent(event)

    def leaveEvent(self, event):
        for item in (self.folder_label, self.file_label):
            font = item.font()
            font.setUnderline(False)
            item.setFont(font)
        self._update_text()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class DirectoryPathLink(QLabel):
    def __init__(self):
        super().__init__("未关联")
        self.setObjectName("detailValue")
        self.path: Path | None = None
        self.setAccessibleName("关联的本地文件夹")

    def set_path(self, path: str | None):
        self.path = Path(path) if path else None
        self.setToolTip(str(self.path) if self.path else "")
        self.setCursor(Qt.CursorShape.PointingHandCursor if self.path
                       else Qt.CursorShape.ArrowCursor)
        font = self.font()
        font.setUnderline(False)
        self.setFont(font)
        self._update_text()

    def _update_text(self):
        if self.path is None:
            self.setText("未关联")
            return
        full = str(self.path).replace("/", "\\")
        metrics = self.fontMetrics()
        width = max(1, self.contentsRect().width())
        if metrics.horizontalAdvance(full) <= width:
            self.setText(full)
            return
        tail = ""
        for part in reversed(full.rstrip("\\").split("\\")):
            candidate = part + ("\\" + tail if tail else "")
            if metrics.horizontalAdvance("...\\" + candidate) > width:
                break
            tail = candidate
        if not tail:
            available = max(1, width - metrics.horizontalAdvance("...\\"))
            tail = metrics.elidedText(self.path.name, Qt.TextElideMode.ElideMiddle, available)
        self.setText("...\\" + tail)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_text()

    def enterEvent(self, event):
        if self.path:
            font = self.font()
            font.setUnderline(True)
            self.setFont(font)
        super().enterEvent(event)

    def leaveEvent(self, event):
        font = self.font()
        font.setUnderline(False)
        self.setFont(font)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if (self.path and event.button() == Qt.MouseButton.LeftButton
                and self.rect().contains(event.position().toPoint())):
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.path)))
            event.accept()
            return
        super().mouseReleaseEvent(event)


class StarRatingControl(QWidget):
    ratingSelected = Signal(int)

    def __init__(self, interactive: bool = True, parent: QWidget | None = None):
        super().__init__(parent)
        self.interactive = interactive
        self.rating = 0
        self.muted = False
        self.hover_rating: int | None = None
        self.star_spacing = 24
        self.star_offset = 0
        self.star_radius = 6.5
        self.setFixedSize(120, 28)
        if interactive:
            self.setMouseTracking(True)
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.setToolTip("点击设置 1–5 星；再次点击相同星级可清除")
        self.setAccessibleName("照片星级")

    def set_rating(self, rating: int):
        self.rating = rating
        self.setAccessibleDescription(f"当前 {rating} 星")
        self.update()

    def _star_at(self, x: float) -> int:
        return max(1, min(5, int(x // self.star_spacing) + 1))

    def mouseMoveEvent(self, event):
        if self.interactive:
            self.hover_rating = self._star_at(event.position().x())
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self.hover_rating = None
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if self.interactive and event.button() == Qt.MouseButton.LeftButton:
            selected = self._star_at(event.position().x())
            self.ratingSelected.emit(0 if selected == self.rating else selected)
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        displayed = self.hover_rating if self.hover_rating is not None else self.rating
        for index in range(5):
            active = index < displayed
            path = star_path(self.star_offset + self.star_spacing / 2 + self.star_spacing * index,
                             self.height() / 2, self.star_radius)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(ui_color("#ffaf22" if self.hover_rating is not None else "#ff9d00")
                             if active else ui_color("#85868d" if self.hover_rating is not None else "#55565a"))
            painter.drawPath(path)
        painter.end()


class InspectorSectionButton(QPushButton):
    def __init__(self, title: str):
        super().__init__(title)
        self.setCheckable(True)
        self.setChecked(True)
        self.setFixedHeight(30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hovered = False
        self._eagle_arrow = QSvgRenderer(
            asset_path("inspector.expand"), self)

    def enterEvent(self, event):
        self._hovered = True
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event):
        self._hovered = False
        super().leaveEvent(event)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        hovered = self._hovered
        header_font = painter.font()
        muted = bool(self.property("muted"))
        header_font.setPixelSize(12 if muted else 14)
        header_font.setWeight(QFont.Weight.Bold if self.property("strong") or not muted else QFont.Weight.DemiBold)
        painter.setFont(header_font)
        resting_color = "#a6a7aa" if muted and not self.property("strong") else "#fafafa"
        painter.setPen(ui_color("#ffffff" if hovered else resting_color))
        painter.drawText(self.rect().adjusted(0, 0, -22, 0),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.text())
        if hovered or not self.isChecked() or self.property("alwaysArrow"):
            if self.property("eagleArrow"):
                painter.setOpacity(1.0 if hovered else 0.3)
                painter.translate(self.width() - 8, self.height() / 2)
                if self.isChecked():
                    painter.rotate(90)
                self._eagle_arrow.render(painter, QRectF(-8, -8, 16, 16))
                painter.end()
                return
            x, y = self.width() - 7, self.height() / 2
            painter.setPen(QPen(ui_color("#ffffff" if hovered else "#b9bac0"), 1.3, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            if self.isChecked():
                painter.drawLine(QPointF(x - 6, y - 3), QPointF(x, y + 3))
                painter.drawLine(QPointF(x, y + 3), QPointF(x + 6, y - 3))
            else:
                painter.drawLine(QPointF(x, y - 6), QPointF(x + 6, y))
                painter.drawLine(QPointF(x + 6, y), QPointF(x, y + 6))
        painter.end()


class InspectorFlagButton(QPushButton):
    def __init__(self, title: str, kind: str):
        super().__init__(title)
        self.kind = kind
        self.setObjectName("inspectorFlag")
        self.setCheckable(True)
        self.setFixedSize(48 if kind == "keep" else 64, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        from picklight.ui.graphics import photo_state_pixmap
        tint = ui_color("#62d79c" if self.kind == "keep" else "#f2797d")
        if not self.isEnabled():
            painter.setOpacity(0.35)
        color = tint.lighter(115) if self.underMouse() else tint if self.isChecked() else ui_color("#9c9fa6")
        painter.drawPixmap(0, 6, photo_state_pixmap(
            "keep" if self.kind == "keep" else "reject", 14, color.name()))
        font = painter.font()
        font.setPixelSize(11)
        painter.setFont(font)
        painter.setPen(color)
        painter.drawText(self.rect().adjusted(17, 0, -3, 0),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.text())
        painter.end()


class PhotoCanvas(QWidget):
    def __init__(self, parent: QWidget | None = None, inspector: bool = False):
        super().__init__(parent)
        self.setObjectName("previewSurface")
        self.image = None
        self.message = ""
        self.loading_spinner = LoadingSpinner(self, 28)
        self.inspector = inspector
        self.decision_state = ""
        self.setMinimumSize(200 if inspector else 220, 100)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_decision_state(self, state):
        self.decision_state = state
        self.update()

    def set_image(self, image):
        self.loading_spinner.set_loading(False)
        self.image = image
        self.message = ""
        self.update()

    def set_message(self, message: str):
        self.loading_spinner.set_loading(False)
        self.image = None
        self.message = message
        self.update()

    def set_loading(self):
        self.set_message("")
        self.loading_spinner.set_loading(True)

    def image_rect(self) -> QRectF:
        if self.image is None or self.image.isNull():
            return QRectF(self.rect())
        available = (self.rect() if self.inspector
                     else self.rect().adjusted(8, 8, -8, -8))
        target = QSize(self.image.width(), self.image.height())
        target.scale(available.size(), Qt.AspectRatioMode.KeepAspectRatio)
        return QRectF(available.x() + (available.width() - target.width()) / 2,
                      available.y() + (available.height() - target.height()) / 2,
                      target.width(), target.height())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if not self.inspector:
            surface = QPainterPath()
            surface.addRoundedRect(QRectF(self.rect()), 6, 6)
            painter.fillPath(surface, ui_color("#191a1d"))
            painter.setClipPath(surface)
        if self.image is not None and not self.image.isNull():
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            target = self.image_rect()
            painter.drawImage(target, self.image, QRectF(self.image.rect()))
            if not self.inspector:
                from picklight.ui.graphics import paint_photo_state
                paint_photo_state(painter, target, self.decision_state)
        elif self.message:
            painter.setPen(ui_color("#d6d6da"))
            painter.drawText(self.rect().adjusted(24, 24, -24, -24),
                             Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                             self.message)
        painter.end()
