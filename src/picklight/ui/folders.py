"""Folder cards, sidebar controls and the folder tree."""

from __future__ import annotations

from pathlib import Path
import re

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPersistentModelIndex,
    QPoint,
    QPointF,
    QRectF,
    QSize,
    QTimer,
    QVariantAnimation,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QFontMetrics,
    QIcon,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
    QRadialGradient,
    QTextCharFormat,
    QTextLayout,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QLabel,
    QLineEdit,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QToolButton,
    QTreeWidget,
    QWidget,
)

from picklight.appearance import ui_color

from picklight.chrome import icon_canvas
from picklight.appearance import sidebar_counts
from picklight.paths import asset_path
from picklight.ui.graphics import (
    theme_icon,
    folder_tree_icon,
    folder_triangle_icon,
)
from picklight.ui.cursors import theme_cursor


class FolderSectionToggle(QToolButton):
    def __init__(self):
        super().__init__()
        self.setCheckable(True)
        self.setChecked(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAutoRaise(True)
        self.setFixedHeight(28)
        self.toggled.connect(self.update)

    def setText(self, text):
        super().setText(text)
        font = QFont(self.font())
        font.setPixelSize(13)
        self.setFont(font)
        self.setFixedWidth(self.fontMetrics().horizontalAdvance(text) + 28)

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(ui_color("#ffffff" if self.underMouse() else "#a2a3a6"))
        painter.drawText(self.rect().adjusted(5, 0, -20, 0), Qt.AlignmentFlag.AlignVCenter, self.text())
        painter.setOpacity(1.0 if self.underMouse() else 0.68)
        folder_triangle_icon(self.isChecked()).paint(
            painter, self.width() - 18, (self.height() - 12) // 2, 12, 12,
            Qt.AlignmentFlag.AlignCenter)
        painter.end()


class FolderCard(QFrame):
    clicked = Signal(str)
    activated = Signal(str)

    def __init__(self, project: dict, count: int, cover: Path | None, child_count: int = 0):
        super().__init__()
        self.project = project
        self.project_id = project["id"]
        self.cover_path = cover
        self.photo_count = count
        self.child_count = child_count
        self.image = None
        self.selected = False
        self._double_clicked = False
        self.setObjectName("folderCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip(str(project["name"]))
        self.setAccessibleName(str(project["name"]))
        self.set_card_width(240)

    def set_card_width(self, width):
        self.setFixedSize(width, round((width - 6) * 0.75) + 64)

    def set_cover(self, image):
        if image is not None and not image.isNull():
            self.image = image
            self.update()

    def set_selected(self, selected):
        self.selected = selected
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        width = self.width()
        cover_height = round((width - 6) * 0.75)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(247, 248, 248, 25))
        painter.drawRoundedRect(QRectF(23, 5, width - 46, 2), 1, 1)
        painter.setBrush(QColor(247, 248, 248, 38))
        painter.drawRoundedRect(QRectF(13, 9, width - 26, 2), 1, 1)
        body = QRectF(3, 13, width - 6, cover_height)
        gradient = QRadialGradient(QPointF(body.center().x(), body.top()), width)
        gradient.setColorAt(0, QColor(247, 248, 248, 38))
        gradient.setColorAt(1, QColor(247, 248, 248, 13))
        painter.setBrush(gradient)
        painter.setPen(QPen(QColor(247, 248, 248, 20), 1))
        painter.drawRoundedRect(body, 10, 10)
        if self.image is not None:
            available = body.adjusted(4, 4, -4, -4)
            size = QSize(self.image.width(), self.image.height())
            size.scale(available.size().toSize(), Qt.AspectRatioMode.KeepAspectRatio)
            target = QRectF(available.center().x() - size.width() / 2,
                            available.center().y() - size.height() / 2,
                            size.width(), size.height())
            clip = QPainterPath()
            clip.addRoundedRect(target, 4, 4)
            painter.save()
            painter.setClipPath(clip)
            painter.drawImage(target, self.image)
            painter.restore()
        if self.selected or self.underMouse():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(ui_color("#2ea8f4") if self.selected
                                else QColor(247, 248, 248, 14), 2 if self.selected else 1))
            painter.drawRoundedRect(QRectF(1, 1, width - 2, cover_height + 16), 8, 8)
        font = painter.font()
        font.setPixelSize(13)
        font.setWeight(QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(ui_color("#ffffff"))
        title_y = body.bottom() + 12
        name = str(self.project["name"])
        painter.drawText(QRectF(3, title_y, width - 6, 18), Qt.AlignmentFlag.AlignCenter,
                         painter.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, width - 6))
        font.setPixelSize(11)
        painter.setFont(font)
        painter.setPen(ui_color("#939498"))
        subtitle = f"{self.photo_count} 张照片"
        if self.child_count:
            subtitle += f" · {self.child_count} 个子文件夹"
        painter.drawText(QRectF(3, title_y + 22, width - 6, 16), Qt.AlignmentFlag.AlignCenter,
                         painter.fontMetrics().elidedText(subtitle, Qt.TextElideMode.ElideRight, width - 6))
        painter.end()

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        self._double_clicked = False
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if not self._double_clicked and self.rect().contains(event.position().toPoint()):
                self.clicked.emit(self.project_id)
            self._double_clicked = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._double_clicked = True
            self.activated.emit(self.project_id)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.activated.emit(self.project_id)
            event.accept()
            return
        if event.key() == Qt.Key.Key_Space:
            self.clicked.emit(self.project_id)
            event.accept()
            return
        super().keyPressEvent(event)


class FolderFilterEdit(QLineEdit):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self.setTextMargins(28, 0, 26, 0)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.PlaceholderText, ui_color("#9b9c9f"))
        self.setPalette(palette)
        self._filter_renderer = QSvgRenderer(
            asset_path("filter"), self)
        self.clear_button = QToolButton(self)
        self.clear_button.setObjectName("folderFilterClear")
        self.clear_button.setFixedSize(20, 20)
        self.clear_button.setIconSize(QSize(14, 14))
        self.clear_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.clear_button.setAccessibleName("清除文件夹筛选")
        self.clear_button.setToolTip("清除筛选")
        icon = QIcon()
        for mode, color in ((QIcon.Mode.Normal, "#bfc0c3"), (QIcon.Mode.Active, "#ffffff")):
            canvas = icon_canvas(14)
            painter = QPainter(canvas)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(color))
            painter.drawEllipse(QRectF(1, 1, 12, 12))
            painter.setPen(QPen(ui_color("#25262a"), 1.1, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap))
            painter.drawLine(QPointF(5, 5), QPointF(9, 9))
            painter.drawLine(QPointF(9, 5), QPointF(5, 9))
            painter.end()
            icon.addPixmap(canvas, mode)
        self.clear_button.setIcon(icon)
        self.clear_button.clicked.connect(self.clear)
        self.clear_button.hide()
        self.textChanged.connect(self._update_filter_state)

    def _update_filter_state(self, text):
        self.clear_button.setVisible(bool(text))
        filtering = bool(text.strip())
        if self.property("filtering") != filtering:
            self.setProperty("filtering", filtering)
            self.style().unpolish(self)
            self.style().polish(self)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.clear_button.move(self.width() - 26, (self.height() - 20) // 2)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._filter_renderer.render(painter, QRectF(8, (self.height() - 16) / 2 + 1, 16, 16))
        painter.end()


class SidebarNavButton(QPushButton):
    def __init__(self, title: str, kind: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.title = title
        self.kind = kind
        self.count = 0
        self.active = False
        self._hovered = False
        self.setFixedHeight(27)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setAccessibleName(title)

    def set_state(self, count: int, active: bool):
        self.count = count
        self.active = active
        self.update()

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(12, 1, -2, -1)
        if self.active or self._hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(ui_color(QColor(255, 255, 255, 27 if self.active else 9)))
            painter.drawRoundedRect(rect, 6, 6)
        asset = {"all": "sidebar.all", "rated": "filter.rating", "marked": "photo.reject"}[self.kind]
        native_icon = theme_icon(asset, 18)
        native_icon.paint(painter, 18, (self.height() - 18) // 2, 18, 18,
                          Qt.AlignmentFlag.AlignCenter,
                          QIcon.Mode.Active if self._hovered else QIcon.Mode.Normal)
        font = painter.font()
        font.setPixelSize(14)
        font.setWeight(QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(ui_color("#ffffff"))
        painter.drawText(QRectF(42, 0, self.width() - 84, self.height()),
                         Qt.AlignmentFlag.AlignVCenter, self.title)
        font.setPixelSize(11)
        painter.setFont(font)
        painter.setPen(ui_color(QColor(255, 255, 255, 185)))
        painter.drawText(QRectF(self.width() - 41, 0, 29, self.height()),
                         Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                         str(self.count) if sidebar_counts(self) else "")
        painter.end()


class FolderSectionHeader(QWidget):
    hoverChanged = Signal(bool)

    def enterEvent(self, event):
        self.hoverChanged.emit(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hoverChanged.emit(False)
        super().leaveEvent(event)


class FolderHeaderPill(QFrame):
    hoverChanged = Signal(bool)
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pressed = False

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pressed = self._pressed
            self._pressed = False
            if pressed and self.rect().contains(event.position().toPoint()):
                self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def enterEvent(self, event):
        self.hoverChanged.emit(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hoverChanged.emit(False)
        super().leaveEvent(event)


FOLDER_DROP_COLOR = "#3297ff"


class FolderDragPreview(QLabel):
    def __init__(self, pixmap, parent):
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowTransparentForInput
                         | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setStyleSheet("background: transparent; border: 0; padding: 0;")
        self.setPixmap(pixmap)
        self.setFixedSize(pixmap.deviceIndependentSize().toSize())
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self.follow_cursor)
        self.follow_cursor()

    def follow_cursor(self):
        self.move(QCursor.pos() + QPoint(12, 14))

    def start(self):
        self.show()
        self._timer.start()

    def closeEvent(self, event):
        self._timer.stop()
        super().closeEvent(event)


class ProjectTree(QTreeWidget):
    foldersMoved = Signal(list)
    dragFinished = Signal()
    destinationChosen = Signal(object, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hovered_branch = QPersistentModelIndex()
        self._hovered_folder = QPersistentModelIndex()
        self._branch_press = False
        self.filter_query = ""
        self._dragged_folder = QPersistentModelIndex()
        self._drag_expansion_state = None
        self._folder_drag_active = False
        self._folder_drag_press = None
        self._pending_click_selection = None
        self._drag_destination = None
        self._drag_preview = None
        self._drag_scroll = QTimer(self)
        self._drag_scroll.setInterval(40)
        self._drag_scroll.timeout.connect(self._scroll_folder_drag)
        self._drop_target = QPersistentModelIndex()
        self.destination_picking = False
        self._insertion_target = QPersistentModelIndex()
        self._insertion_relation = ""
        self._destination_press = None
        self._branch_angles = {}
        self._branch_animations = {}
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setMouseTracking(True)
        self.expanded.connect(lambda index: self._animate_branch(index, True))
        self.collapsed.connect(lambda index: self._animate_branch(index, False))
        self.model().modelAboutToBeReset.connect(self._clear_branch_animations)

    def _branch_at(self, position):
        index = self.indexAt(position)
        if index.isValid() and self.model().hasChildren(index):
            item_rect = self.visualRect(index)
            branch_rect = QRectF(item_rect.left() - 21, item_rect.top(), 16, item_rect.height())
            if branch_rect.contains(position):
                return QPersistentModelIndex(index)
        return QPersistentModelIndex()

    def moveCursor(self, action, modifiers):
        index = super().moveCursor(action, modifiers)
        if not self.filter_query:
            return index
        if action == QAbstractItemView.CursorAction.MoveLeft:
            if index.isValid() and self.visualRect(index).height() == 0:
                return self.currentIndex()
        backwards = action in (QAbstractItemView.CursorAction.MoveUp,
                                QAbstractItemView.CursorAction.MovePrevious,
                                QAbstractItemView.CursorAction.MovePageUp,
                                QAbstractItemView.CursorAction.MoveEnd)
        while index.isValid() and self.visualRect(index).height() == 0:
            index = self.indexAbove(index) if backwards else self.indexBelow(index)
        return index if index.isValid() else self.currentIndex()

    def _animate_branch(self, index, expanded):
        key = QPersistentModelIndex(index)
        previous = self._branch_animations.pop(key, None)
        if previous is not None:
            previous.stop()
            previous.deleteLater()
        start = self._branch_angles.get(key, 0.0 if expanded else 90.0)
        animation = QVariantAnimation(self)
        animation.setDuration(180)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.setStartValue(start)
        animation.setEndValue(90.0 if expanded else 0.0)
        animation.valueChanged.connect(lambda value: self._set_branch_angle(key, value))
        animation.finished.connect(lambda: self._finish_branch_animation(key, animation))
        self._branch_animations[key] = animation
        animation.start()

    def _set_branch_angle(self, index, angle):
        if index.isValid():
            self._branch_angles[index] = float(angle)
            self.viewport().update()

    def _finish_branch_animation(self, index, animation):
        if self._branch_animations.get(index) is animation:
            self._branch_animations.pop(index, None)
            self._branch_angles.pop(index, None)
        animation.deleteLater()
        self.viewport().update()

    def _clear_branch_animations(self):
        for animation in self._branch_animations.values():
            animation.stop()
            animation.deleteLater()
        self._branch_animations.clear()
        self._branch_angles.clear()
        self._hovered_branch = QPersistentModelIndex()
        self._hovered_folder = QPersistentModelIndex()

    def mousePressEvent(self, event):
        branch = self._branch_at(event.position().toPoint())
        if event.button() == Qt.MouseButton.LeftButton and branch.isValid():
            self._folder_drag_press = None
            self._branch_press = True
            self.setExpanded(branch, not self.isExpanded(branch))
            event.accept()
            return
        self._branch_press = False
        if self.destination_picking and event.button() == Qt.MouseButton.LeftButton:
            self._destination_press = self.destination_at(event.position().toPoint())
        if self.dragEnabled() and event.button() == Qt.MouseButton.LeftButton:
            self._folder_drag_press = event.position().toPoint()
            previous = self.currentItem()
            blocked = self.blockSignals(True)
            try:
                super().mousePressEvent(event)
            finally:
                self.blockSignals(blocked)
            self._pending_click_selection = (self.currentItem(), previous)
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._folder_drag_active:
            self.finish_folder_drag(event.position().toPoint())
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._branch_press:
            self._branch_press = False
            event.accept()
            return
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self._folder_drag_press = None
            selection = self._pending_click_selection
            self._pending_click_selection = None
            if selection and selection[0] is not selection[1]:
                self.currentItemChanged.emit(*selection)
        if self.destination_picking and event.button() == Qt.MouseButton.LeftButton:
            destination = self.destination_at(event.position().toPoint())
            if destination is not None and destination == self._destination_press:
                item, relation = destination
                self._drop_target = (QPersistentModelIndex(self.indexFromItem(item))
                                     if relation == "inside" else QPersistentModelIndex())
                self.viewport().update()
                self.destinationChosen.emit(item, relation)
            self._destination_press = None

    def destination_at(self, position):
        item = self.itemAt(position)
        if item is None or not item.flags() & Qt.ItemFlag.ItemIsEnabled:
            return None
        rect = self.visualItemRect(item)
        relation = ("before" if position.y() < rect.top() + 4 else
                    "after" if position.y() > rect.bottom() - 4 else "inside")
        return item, relation

    def _update_destination_hint(self, position):
        destination = self.destination_at(position)
        item, relation = destination if destination else (None, "")
        self._insertion_target = (QPersistentModelIndex(self.indexFromItem(item))
                                  if item is not None and relation != "inside"
                                  else QPersistentModelIndex())
        self._insertion_relation = relation
        self.viewport().update()

    def paintEvent(self, event):
        # Clear every frame before painting the rotated arrow and moving rows.
        background = QPainter(self.viewport())
        background.fillRect(event.rect(), ui_color("#1f2023"))
        background.end()
        super().paintEvent(event)
        if (self.destination_picking or self._folder_drag_active) and self._insertion_target.isValid():
            rect = self.visualRect(self._insertion_target)
            y = rect.top() if self._insertion_relation == "before" else rect.bottom()
            painter = QPainter(self.viewport())
            painter.setPen(QPen(QColor(FOLDER_DROP_COLOR), 1))
            painter.drawLine(max(1, rect.left() - 8), y, self.viewport().width() - 4, y)
            painter.end()

    def mouseDoubleClickEvent(self, event):
        if (event.button() == Qt.MouseButton.LeftButton
                and self._branch_at(event.position().toPoint()).isValid()):
            self.mousePressEvent(event)
            return
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event):
        position = event.position().toPoint()
        if self._folder_drag_active:
            self._update_folder_drag(position)
            event.accept()
            return
        if (self.dragEnabled() and self._folder_drag_press is not None
                and event.buttons() & Qt.MouseButton.LeftButton
                and (position - self._folder_drag_press).manhattanLength() >= QApplication.startDragDistance()):
            self.startDrag(Qt.DropAction.MoveAction)
            self._update_folder_drag(position)
            event.accept()
            return
        index = self.indexAt(position)
        branch = self._branch_at(position)
        folder = QPersistentModelIndex(index)
        if branch != self._hovered_branch or folder != self._hovered_folder:
            self._hovered_branch = branch
            self._hovered_folder = folder
            self.viewport().update()
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor
                                  if branch.isValid() else Qt.CursorShape.ArrowCursor)
        if self.destination_picking:
            self._update_destination_hint(position)
        if not (self.dragEnabled() and event.buttons() & Qt.MouseButton.LeftButton):
            super().mouseMoveEvent(event)

    def keyPressEvent(self, event):
        if self._folder_drag_active and event.key() == Qt.Key.Key_Escape:
            self.finish_folder_drag(cancel=True)
            event.accept()
            return
        super().keyPressEvent(event)

    def hideEvent(self, event):
        if self._folder_drag_active:
            self.finish_folder_drag(cancel=True)
        super().hideEvent(event)

    def viewportEvent(self, event):
        if event.type() == QEvent.Type.Leave:
            self._hovered_branch = QPersistentModelIndex()
            self._hovered_folder = QPersistentModelIndex()
            self._insertion_target = QPersistentModelIndex()
            self.viewport().unsetCursor()
            self.viewport().update()
        return super().viewportEvent(event)

    def drawBranches(self, painter, rect, index):
        if rect.height() <= 0:
            return
        center_x = rect.right() - 12
        center_y = rect.center().y()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        ancestors = []
        parent = index.parent()
        while parent.isValid():
            ancestors.append(parent)
            parent = parent.parent()
        ancestors.reverse()
        if ancestors:
            painter.setPen(QPen(QColor(151, 154, 163, 52), 1,
                                Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                                Qt.PenJoinStyle.RoundJoin))
            for level, branch_item in enumerate([*ancestors[1:], index]):
                guide_x = center_x - (len(ancestors) - 1 - level) * self.indentation()
                tree_item = self.itemFromIndex(branch_item)
                parent_item = tree_item.parent() if tree_item else None
                sibling_count = parent_item.childCount() if parent_item else self.topLevelItemCount()
                has_next = any(not (parent_item.child(i) if parent_item else
                                    self.topLevelItem(i)).isHidden()
                               for i in range(branch_item.row() + 1, sibling_count))
                if level < len(ancestors) - 1:
                    painter.drawLine(QPointF(guide_x, rect.top()),
                                     QPointF(guide_x, rect.bottom() + 1))
                elif not self.model().hasChildren(index):
                    if has_next:
                        painter.drawLine(QPointF(guide_x, rect.top()),
                                         QPointF(guide_x, rect.bottom() + 1))
                    else:
                        elbow = QPainterPath(QPointF(guide_x, rect.top()))
                        elbow.lineTo(guide_x, center_y - 6)
                        elbow.quadTo(guide_x, center_y, guide_x + 6, center_y)
                        painter.drawPath(elbow)
        if self.model().hasChildren(index):
            painter.setOpacity(1.0 if self._hovered_branch == index else 0.5)
            angle = self._branch_angles.get(QPersistentModelIndex(index),
                                            90.0 if self.isExpanded(index) else 0.0)
            painter.translate(center_x, center_y)
            painter.rotate(angle)
            folder_triangle_icon(False).paint(painter, -6, -6, 12, 12)
        painter.restore()

    def _folder_drag_pixmap(self, item):
        font = QFont(self.font())
        font.setPixelSize(12)
        width = max(84, min(180, QFontMetrics(font).horizontalAdvance(item.text(0)) + 36))
        ratio = self.devicePixelRatioF()
        canvas = QPixmap(round(width * ratio), round(24 * ratio))
        canvas.setDevicePixelRatio(ratio)
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setPen(QPen(QColor(FOLDER_DROP_COLOR), 1))
        painter.setBrush(ui_color("#2f8fe8"))
        painter.drawRoundedRect(QRectF(0.5, 0.5, width - 1, 23), 4, 4)
        folder_tree_icon(False, True, str(item.data(0, Qt.ItemDataRole.UserRole + 4) or ""),
                         str(item.data(0, Qt.ItemDataRole.UserRole + 5) or ""), size=16).paint(
                             painter, 5, 4, 16, 16)
        painter.setFont(font)
        painter.setPen(ui_color("#ffffff"))
        painter.drawText(QRectF(26, 0, width - 32, 24), Qt.AlignmentFlag.AlignVCenter,
                         painter.fontMetrics().elidedText(
                             item.text(0), Qt.TextElideMode.ElideRight, width - 32))
        painter.end()
        return canvas

    def folder_expansion_state(self):
        state = {}
        pending = [self.topLevelItem(i) for i in range(self.topLevelItemCount())]
        while pending:
            item = pending.pop()
            state[item.data(0, Qt.ItemDataRole.UserRole)] = item.isExpanded()
            pending.extend(item.child(i) for i in range(item.childCount()))
        return state

    def restore_folder_expansion(self, state):
        if state is None:
            return
        blocked = self.blockSignals(True)
        try:
            self._clear_branch_animations()
            pending = [self.topLevelItem(i) for i in range(self.topLevelItemCount())]
            while pending:
                item = pending.pop()
                key = item.data(0, Qt.ItemDataRole.UserRole)
                if key in state:
                    item.setExpanded(state[key])
                pending.extend(item.child(i) for i in range(item.childCount()))
        finally:
            self.blockSignals(blocked)
        self.viewport().update()

    def startDrag(self, supported_actions):
        items = self.selectedItems()
        if self._folder_drag_active or not items or not supported_actions & Qt.DropAction.MoveAction:
            return
        self._drag_expansion_state = self.folder_expansion_state()
        self._folder_drag_active = True
        self._pending_click_selection = None
        self._drag_destination = None
        self._dragged_folder = QPersistentModelIndex(self.indexFromItem(items[0]))
        self._drag_preview = FolderDragPreview(self._folder_drag_pixmap(items[0]), self)
        self._drag_preview.start()
        self.setState(QAbstractItemView.State.NoState)
        self.viewport().grabMouse()
        self._drag_scroll.start()
        self._update_folder_drag(self.viewport().mapFromGlobal(QCursor.pos()))
        self.viewport().update()

    def _update_folder_drag(self, position):
        if not self._folder_drag_active:
            return
        destination = self.destination_at(position) if self.viewport().rect().contains(position) else None
        source = self.itemFromIndex(self._dragged_folder)
        if destination:
            item, relation = destination
            ancestor = item if relation == "inside" else item.parent()
            if item is source:
                destination = None
            while ancestor is not None:
                if ancestor is source:
                    destination = None
                    break
                ancestor = ancestor.parent()
        self._drag_destination = destination
        self._drop_target = QPersistentModelIndex()
        self._insertion_target = QPersistentModelIndex()
        if destination:
            item, relation = destination
            index = QPersistentModelIndex(self.indexFromItem(item))
            if relation == "inside":
                self._drop_target = index
            else:
                self._insertion_target = index
            self._insertion_relation = relation
        self.viewport().setCursor(theme_cursor("cursor.drag.move", 20, QPoint(1, 1), self.devicePixelRatioF()))
        self.viewport().update()

    def _scroll_folder_drag(self):
        if not self._folder_drag_active:
            return
        position = self.viewport().mapFromGlobal(QCursor.pos())
        if self.viewport().rect().contains(position):
            step = -12 if position.y() < 24 else 12 if position.y() > self.viewport().height() - 24 else 0
            if step:
                bar = self.verticalScrollBar()
                bar.setValue(bar.value() + step)
            self._update_folder_drag(position)

    def finish_folder_drag(self, position=None, *, cancel=False):
        if not self._folder_drag_active:
            return
        if position is not None:
            self._update_folder_drag(position)
        destination = None if cancel else self._drag_destination
        source = self.itemFromIndex(self._dragged_folder)
        snapshot = None
        if source is not None and destination:
            target, relation = destination
            blocked = self.blockSignals(True)
            try:
                previous = source.parent()
                if previous is not None:
                    previous.takeChild(previous.indexOfChild(source))
                else:
                    self.takeTopLevelItem(self.indexOfTopLevelItem(source))
                if relation == "inside":
                    target.addChild(source)
                else:
                    parent = target.parent()
                    row = parent.indexOfChild(target) if parent else self.indexOfTopLevelItem(target)
                    row += int(relation == "after")
                    if parent is not None:
                        parent.insertChild(row, source)
                    else:
                        self.insertTopLevelItem(row, source)
            finally:
                self.blockSignals(blocked)
            snapshot = self._folder_tree_snapshot()
        self._drag_scroll.stop()
        self._folder_drag_active = False
        self._folder_drag_press = None
        self._pending_click_selection = None
        if QWidget.mouseGrabber() is self.viewport():
            self.viewport().releaseMouse()
        self.viewport().unsetCursor()
        self._drag_preview.close()
        self._drag_preview.deleteLater()
        self._drag_preview = None
        self._drop_target = QPersistentModelIndex()
        self._insertion_target = QPersistentModelIndex()
        if snapshot is not None:
            self.foldersMoved.emit(snapshot)
        self.restore_folder_expansion(self._drag_expansion_state)
        self._drag_expansion_state = None
        self._dragged_folder = QPersistentModelIndex()
        self._drag_destination = None
        self.viewport().update()
        self.dragFinished.emit()

    def dragMoveEvent(self, event):
        event.ignore()

    def dragLeaveEvent(self, event):
        self._drop_target = QPersistentModelIndex()
        self.viewport().update()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        event.ignore()

    def _folder_tree_snapshot(self):
        tree: list[tuple[str, str | None]] = []

        pending = [(self.topLevelItem(index), None)
                   for index in reversed(range(self.topLevelItemCount()))]
        while pending:
            item, parent_id = pending.pop()
            project_id = item.data(0, Qt.ItemDataRole.UserRole)
            tree.append((project_id, parent_id))
            pending.extend((item.child(index), project_id)
                           for index in reversed(range(item.childCount())))
        return tree


class ProjectListDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        query = self.parent().filter_query.casefold()
        if query and query not in str(index.data() or "").casefold():
            return QSize(0, 0)
        return QSize(0, 27)

    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        editor.setObjectName("projectNameEditor")
        editor.setFrame(False)
        return editor

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect.adjusted(22, 3, -41, -3))

    def paint(self, painter, option, index):
        if option.rect.height() <= 0:
            return
        painter.save()
        if not option.state & QStyle.StateFlag.State_Enabled:
            painter.setOpacity(0.4)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(option.rect).adjusted(-8, 1, -2, -1)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        tree = self.parent()
        dragging = tree._drop_target == index
        if dragging:
            painter.setPen(QPen(QColor(FOLDER_DROP_COLOR), 1))
            painter.setBrush(QColor(47, 143, 232, 65))
            painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
        elif selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(ui_color(QColor(255, 255, 255, 27)))
            painter.drawRoundedRect(rect, 6, 6)
        elif option.state & QStyle.StateFlag.State_MouseOver:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(ui_color(QColor(255, 255, 255, 9)))
            painter.drawRoundedRect(rect, 6, 6)
        depth = 0
        parent = index.parent()
        while parent.isValid():
            depth += 1
            parent = parent.parent()
        icon_x = rect.left() + 4
        tree = self.parent()
        opened = tree.model().hasChildren(index) and tree.isExpanded(index)
        highlighted = (selected or bool(option.state & QStyle.StateFlag.State_MouseOver)
                       or tree._hovered_folder == index)
        folder_tree_icon(opened, highlighted, str(index.data(Qt.ItemDataRole.UserRole + 4) or ""),
                         str(index.data(Qt.ItemDataRole.UserRole + 5) or "")).paint(
            painter, int(icon_x), int(rect.center().y() - 10), 20, 20)
        name = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        count = index.data(Qt.ItemDataRole.UserRole + 2)
        if not sidebar_counts(tree):
            count = None
        missing = bool(index.data(Qt.ItemDataRole.UserRole + 3))
        text_x = rect.left() + 30
        text_width = max(20, rect.width() - (72 if count is not None or missing else 40))
        font = painter.font()
        font.setPixelSize(13)
        font.setWeight(QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(ui_color("#ffd2d2") if missing else ui_color("#ffffff"))
        text_rect = QRectF(text_x, rect.top(), text_width, rect.height())
        visible_name = painter.fontMetrics().elidedText(
            name, Qt.TextElideMode.ElideRight, int(text_width))
        if tree.filter_query:
            text_layout = QTextLayout(visible_name, font)
            formats = []
            for match in re.finditer(re.escape(tree.filter_query), visible_name, re.IGNORECASE):
                text_format = QTextCharFormat()
                text_format.setForeground(ui_color("#25b9f4"))
                text_format.setFontWeight(QFont.Weight.DemiBold)
                span = QTextLayout.FormatRange()
                span.start = len(visible_name[:match.start()].encode("utf-16-le")) // 2
                span.length = len(match.group().encode("utf-16-le")) // 2
                span.format = text_format
                formats.append(span)
            text_layout.setFormats(formats)
            text_layout.beginLayout()
            line = text_layout.createLine()
            line.setLineWidth(text_width)
            text_layout.endLayout()
            painter.save()
            painter.setClipRect(text_rect)
            text_layout.draw(painter, QPointF(text_x, rect.center().y() - line.height() / 2))
            painter.restore()
        else:
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter, visible_name)
        font.setPixelSize(11)
        painter.setFont(font)
        painter.setPen(ui_color("#ffd2d2") if missing else ui_color(QColor(255, 255, 255, 185)))
        painter.drawText(QRectF(rect.right() - 39, rect.top(), 29, rect.height()),
                         Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                         "!" if missing else str(count) if count is not None else "")
        painter.restore()
