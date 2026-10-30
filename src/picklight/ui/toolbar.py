"""Toolbar buttons, search input and zoom controls."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter
from PySide6.QtWidgets import (
    QLineEdit,
    QLabel,
    QPushButton,
    QSlider,
    QStyle,
    QStyleOptionToolButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from picklight.appearance import ui_color
from picklight.ui.interaction import HoverAnimationMixin

from picklight.ui.folders import FolderFilterEdit
from picklight.ui.graphics import folder_tree_icon, theme_icon


class SearchScopeButton(QToolButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._hover = False
        self.setFixedSize(38, 28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip("搜索范围")
        self.setAccessibleName("搜索范围")

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._hover:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(ui_color("#303136"))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(3, 3, -3, -3), 5, 5)
        mode = QIcon.Mode.Active if self._hover else QIcon.Mode.Normal
        theme_icon("search", 16).paint(painter, 6, 6, 16, 16,
                                       Qt.AlignmentFlag.AlignCenter, mode)
        theme_icon("search.dropdown", 10).paint(
            painter, 22, 9, 10, 10, Qt.AlignmentFlag.AlignCenter, mode)
        painter.end()


class ToolbarSearchEdit(FolderFilterEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTextMargins(42, 0, 26, 0)
        self.scope_menu = None
        self.scope_button = SearchScopeButton(self)
        self.scope_button.clicked.connect(self._show_scope_menu)
        self.clear_button.setIcon(theme_icon("search.clear", 12))
        self.clear_button.setIconSize(QSize(12, 12))
        self.clear_button.setAccessibleName("清除照片搜索")
        self.clear_button.setToolTip("清除搜索")

    def paintEvent(self, event):
        QLineEdit.paintEvent(self, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "scope_button"):
            self.scope_button.move(2, (self.height() - self.scope_button.height()) // 2)

    def _show_scope_menu(self):
        self.clearFocus()
        if self.scope_menu is not None:
            arrow_bottom_right = self.scope_button.mapToGlobal(
                QPoint(self.scope_button.width() - 8, self.scope_button.height() - 3))
            self.scope_menu.popup(arrow_bottom_right)


class SearchScopeRow(QPushButton):
    def __init__(self, title: str, icon_key: str, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(True)
        self.setFixedHeight(28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(title)
        self.title = title
        self.icon_key = icon_key
        self.icon_size = 14

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self.underMouse():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(ui_color("#2a2b2f"))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 4, 4)
        icon = folder_tree_icon(False) if self.icon_key == "folder.closed" else theme_icon(self.icon_key, self.icon_size)
        icon.paint(painter, 10 - self.icon_size // 2, (self.height() - self.icon_size) // 2,
                   self.icon_size, self.icon_size)
        painter.setPen(ui_color("#f0f0f2"))
        painter.drawText(self.rect().adjusted(26, 0, -20, 0),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.title)
        if self.isChecked():
            theme_icon("check", 13).paint(painter, self.width() - 17, 8, 13, 13)
        painter.end()


class SearchScopePanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("searchScopePanel")
        self.setFixedWidth(158)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(7, 7, 7, 7)
        layout.setSpacing(0)
        heading = QLabel("搜索范围:")
        heading.setObjectName("searchScopeHeading")
        heading.setFixedHeight(22)
        layout.addWidget(heading)
        self.rows = {}
        for key, title, icon in (("name", "名称", "search.scope.name"),
                                 ("folder.name", "文件夹名", "folder.closed"),
                                 ("folder.description", "文件夹描述", "search.scope.description"),
                                 ("extension", "扩展名", "search.scope.extension")):
            row = SearchScopeRow(title, icon, self)
            layout.addWidget(row)
            self.rows[key] = row


class ArrangementPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("arrangementPanel")
        self.setFixedWidth(158)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(7, 7, 7, 7)
        layout.setSpacing(0)
        heading = QLabel("布局模式:")
        heading.setObjectName("searchScopeHeading")
        heading.setFixedHeight(22)
        layout.addWidget(heading)
        self.rows = {}
        for key, title in (("waterfall", "瀑布流"), ("grid", "网格")):
            row = SearchScopeRow(title, f"layout.{key}", self)
            layout.addWidget(row)
            self.rows[key] = row


class ToolbarIconButton(HoverAnimationMixin, QToolButton):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAutoRaise(True)
        self._init_hover_animation()

    def enterEvent(self, event):
        if self.isEnabled():
            self._animate_hover(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._animate_hover(0.0)
        super().leaveEvent(event)

    def changeEvent(self, event):
        if event.type() == QEvent.Type.EnabledChange and hasattr(self, "_hover_animation"):
            self.setCursor(Qt.CursorShape.PointingHandCursor if self.isEnabled()
                           else Qt.CursorShape.ArrowCursor)
            if not self.isEnabled():
                self._hover_animation.stop()
                self._set_hover_amount(0)
        super().changeEvent(event)

    def paintEvent(self, event):
        # Let the style draw only the button surface, then paint one centered icon.
        # Overlaying a second icon on the native one offsets odd-sized icons by a pixel.
        option = QStyleOptionToolButton()
        self.initStyleOption(option)
        option.icon = QIcon()
        painter = QPainter(self)
        self.style().drawComplexControl(QStyle.ComplexControl.CC_ToolButton, option, painter, self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._hover_amount and self.isEnabled():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(ui_color(QColor(255, 255, 255, round(18 * self._hover_amount))))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 5, 5)
        size = self.iconSize()
        target = QRectF((self.width() - size.width()) / 2,
                        (self.height() - size.height()) / 2, size.width(), size.height())
        active = (self._hover_amount or self.property("filtered") == "true"
                  or (self.isChecked() and self.objectName() != "viewMode"))
        mode = (QIcon.Mode.Disabled if not self.isEnabled() else
                QIcon.Mode.Active if active else QIcon.Mode.Normal)
        pixmap = self.icon().pixmap(size * self.devicePixelRatioF(), mode,
                                  QIcon.State.On if self.isChecked() else QIcon.State.Off)
        painter.drawPixmap(target, pixmap, QRectF(pixmap.rect()))
        painter.end()


class ZoomStepButton(ToolbarIconButton):
    def __init__(self, step: int):
        super().__init__()
        self.step = step
        self.setIcon(theme_icon(
            "toolbar.zoom.in" if step > 0 else "toolbar.zoom.out", 23))
        self.setIconSize(QSize(23, 23))


class GalleryZoomSlider(QSlider):
    def _set_value_at(self, x: float):
        usable = max(1, self.width() - 12)
        self.setValue(QStyle.sliderValueFromPosition(
            self.minimum(), self.maximum(), round(x - 6), usable))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging_handle = True
            self._set_value_at(event.position().x())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if getattr(self, "_dragging_handle", False) and event.buttons() & Qt.MouseButton.LeftButton:
            self._set_value_at(event.position().x())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and getattr(self, "_dragging_handle", False):
            self._set_value_at(event.position().x())
            self._dragging_handle = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        left, right = 6.0, self.width() - 6.0
        middle = self.height() / 2
        travel = right - left
        fraction = ((self.value() - self.minimum()) /
                    max(1, self.maximum() - self.minimum()))
        handle_x = left + travel * fraction
        painter.setPen(Qt.PenStyle.NoPen)
        # Keep the 3px track and 11px thumb centered at fractional DPI scales.
        painter.setBrush(ui_color(QColor(247, 248, 248, 64)))
        painter.drawRoundedRect(QRectF(left, middle - 1.5, travel, 3), 1.5, 1.5)
        painter.setBrush(ui_color(QColor(247, 248, 248, 128)))
        painter.drawRoundedRect(QRectF(left, middle - 1.5, handle_x - left, 3), 1.5, 1.5)
        painter.setBrush(QColor(0, 0, 0, 55))
        painter.drawEllipse(QRectF(handle_x - 6, middle - 5, 12, 12))
        painter.setBrush(ui_color("#ffffff"))
        painter.drawEllipse(QRectF(handle_x - 5.5, middle - 5.5, 11, 11))
        painter.end()
