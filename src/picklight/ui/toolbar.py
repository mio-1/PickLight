"""Toolbar buttons, search input and zoom controls."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter
from PySide6.QtWidgets import (
    QLineEdit,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSlider,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionToolButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from picklight.appearance import ui_color
from picklight.ui.interaction import HoverAnimationMixin

from picklight.ui.folders import FolderFilterEdit
from picklight.ui.graphics import folder_tree_icon, theme_icon
from picklight.ui.common import ZOOM_ICON_SIZE


_SWITCH_DEPTH = Qt.ItemDataRole.UserRole + 2
_SWITCH_PARENT = Qt.ItemDataRole.UserRole + 3


class FolderSwitchDelegate(QStyledItemDelegate):
    """Draw Eagle's compact hierarchy rows and trailing parent names."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.flat = False
        self.query = ""

    def sizeHint(self, option, index):
        return QSize(0, 28)

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = option.rect.adjusted(1, 0, -1, 0)
        if option.state & QStyle.StateFlag.State_Selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(ui_color("#303136"))
            painter.drawRoundedRect(QRectF(rect), 6, 6)
        elif option.state & QStyle.StateFlag.State_MouseOver:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(ui_color("#28292d"))
            painter.drawRoundedRect(QRectF(rect), 6, 6)
        depth = 0 if self.flat else int(index.data(_SWITCH_DEPTH) or 0)
        for level in range(depth):
            x = rect.left() + 17 + level * 24
            painter.setPen(ui_color("#45464a"))
            painter.drawLine(x, rect.top(), x, rect.bottom())
            if level == depth - 1:
                painter.drawLine(x, rect.center().y(), x + 9, rect.center().y())
        left = rect.left() + 8 + depth * 24
        index.data(Qt.ItemDataRole.DecorationRole).paint(
            painter, left, rect.center().y() - 8, 16, 16)
        left += 23
        parent = index.data(_SWITCH_PARENT) or ""
        right_width = min(150, rect.width() // 3) if parent else 0
        text_rect = rect.adjusted(left - rect.left(), 0, -(right_width + 12), 0)
        title = option.fontMetrics.elidedText(index.data(), Qt.TextElideMode.ElideRight,
                                              max(0, text_rect.width()))
        self._draw_match(painter, title, text_rect.left(), rect, option.fontMetrics)
        if parent:
            parent_rect = rect.adjusted(rect.width() - right_width - 8, 0, -8, 0)
            parent_title = option.fontMetrics.elidedText(parent, Qt.TextElideMode.ElideLeft,
                                                          right_width)
            self._draw_match(painter, parent_title,
                             parent_rect.right() - option.fontMetrics.horizontalAdvance(parent_title),
                             rect, option.fontMetrics, "#777981")
        painter.restore()

    def _draw_match(self, painter, title, left, rect, metrics, normal_color="#f0f0f2"):
        baseline = rect.center().y() + (metrics.ascent() - metrics.descent()) // 2
        start = 0
        while start < len(title):
            match = title.casefold().find(self.query, start) if self.query else -1
            end = match if match >= 0 else len(title)
            if end > start:
                painter.setPen(ui_color(normal_color))
                painter.drawText(left, baseline, title[start:end])
                left += metrics.horizontalAdvance(title[start:end])
            if match < 0:
                break
            matched = title[match:match + len(self.query)]
            painter.setPen(ui_color("#3297ff"))
            painter.drawText(left, baseline, matched)
            left += metrics.horizontalAdvance(matched)
            start = match + len(matched)


class FolderSwitchPanel(QDialog):
    """Eagle-style quick switcher scoped to PickLight folders."""

    folderSelected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("folderSwitchOverlay")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch()
        center = QHBoxLayout()
        center.addStretch()
        self.card = QFrame(self)
        self.card.setObjectName("folderSwitchCard")
        self.card.setFixedWidth(480)
        center.addWidget(self.card)
        center.addStretch()
        outer.addLayout(center)
        outer.addStretch()
        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        header = QHBoxLayout()
        header.setContentsMargins(12, 0, 12, 0)
        header.setSpacing(4)
        self.search = QLineEdit()
        self.search.setObjectName("folderSwitchSearch")
        self.search.setPlaceholderText("搜索文件夹")
        self.search.setAccessibleName("搜索文件夹")
        self.search.setFixedHeight(48)
        self.search.addAction(theme_icon("search", 14), QLineEdit.ActionPosition.LeadingPosition)
        self.search_clear_action = self.search.addAction(
            theme_icon("search.clear", 14), QLineEdit.ActionPosition.TrailingPosition)
        self.search_clear_action.setText("清除搜索")
        self.search_clear_action.setVisible(False)
        self.search_clear_action.triggered.connect(self.search.clear)
        self.search.textChanged.connect(
            lambda value: self.search_clear_action.setVisible(bool(value)))
        self.search.textChanged.connect(self._filter)
        self.search.returnPressed.connect(self._activate_current)
        self.search.installEventFilter(self)
        header.addWidget(self.search, 1)
        close = QToolButton(self.card)
        close.setObjectName("folderSwitchClose")
        close.setIcon(theme_icon("modal.close", 24))
        close.setIconSize(QSize(24, 24))
        close.setFixedSize(24, 24)
        close.setAccessibleName("关闭切换文件夹")
        close.clicked.connect(self.reject)
        header.addWidget(close)
        layout.addLayout(header)
        tabs_widget = QWidget(self.card)
        tabs_widget.setFixedHeight(36)
        tabs = QHBoxLayout(tabs_widget)
        tabs.setContentsMargins(8, 0, 8, 0)
        tabs.setSpacing(8)
        self.all_tab = QPushButton(self.card)
        self.quick_tab = QPushButton(self.card)
        for tab in (self.all_tab, self.quick_tab):
            tab.setObjectName("folderSwitchTab")
            tab.setCheckable(True)
            tab.setFixedHeight(28)
            tabs.addWidget(tab)
        self.all_tab.clicked.connect(lambda: self._set_scope(False))
        self.quick_tab.clicked.connect(lambda: self._set_scope(True))
        tabs.addStretch()
        layout.addWidget(tabs_widget)
        separator = QFrame(self.card)
        separator.setObjectName("folderSwitchSeparator")
        separator.setFixedHeight(1)
        layout.addWidget(separator)
        self.folders = QListWidget()
        self.folders.setObjectName("folderSwitchList")
        self.folders.setAccessibleName("文件夹列表")
        self.folders.setItemDelegate(FolderSwitchDelegate(self.folders))
        self.folders.itemClicked.connect(self._activate)
        self.folders.itemActivated.connect(self._activate)
        layout.addWidget(self.folders, 1)
        footer_frame = QFrame(self.card)
        footer_frame.setObjectName("folderSwitchFooter")
        footer_frame.setFixedHeight(40)
        footer = QHBoxLayout(footer_frame)
        footer.setContentsMargins(12, 0, 12, 0)
        footer.setSpacing(12)
        for label, keys in (("切换", ("Tab",)), ("移动", ("↑", "↓")),
                            ("选中", ("↵",))):
            self._add_shortcut(footer, label, keys)
        footer.addStretch()
        self._add_shortcut(footer, "关闭", ("Esc",))
        layout.addWidget(footer_frame)
        self.card.layout().setStretchFactor(self.folders, 1)
        self._quick_only = False
        self._current_id = None

    def _add_shortcut(self, footer, label, keys):
        group = QHBoxLayout()
        group.setSpacing(3)
        hint = QLabel(label, self.card)
        hint.setObjectName("folderSwitchHint")
        group.addWidget(hint)
        for key in keys:
            chip = QLabel(key, self.card)
            chip.setObjectName("folderSwitchKey")
            chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chip.setFixedHeight(16)
            group.addWidget(chip)
        footer.addLayout(group)

    def showEvent(self, event):
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.geometry())
            self.card.setFixedHeight(min(550, max(300, parent.height() - 40)))
        super().showEvent(event)
        self.search.setFocus()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 112))
        painter.end()

    def eventFilter(self, watched, event):
        if watched is self.search and event.type() == QEvent.Type.KeyPress:
            if self._route_search_key(event):
                return True
        return super().eventFilter(watched, event)

    def _route_search_key(self, event):
        if event.key() == Qt.Key.Key_Tab:
            self._set_scope(not self._quick_only)
            event.accept()
            return True
        if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            row = self.folders.currentRow() + (-1 if event.key() == Qt.Key.Key_Up else 1)
            while 0 <= row < self.folders.count() and self.folders.item(row).isHidden():
                row += -1 if event.key() == Qt.Key.Key_Up else 1
            if 0 <= row < self.folders.count():
                self.folders.setCurrentRow(row)
            event.accept()
            return True
        return False

    def keyPressEvent(self, event):
        if self._route_search_key(event):
            return
        super().keyPressEvent(event)

    def _set_scope(self, quick_only):
        self._quick_only = quick_only
        self.all_tab.setChecked(not quick_only)
        self.quick_tab.setChecked(quick_only)
        self._filter(self.search.text())
        self.search.setFocus()

    def set_folders(self, projects, current_id):
        self.folders.clear()
        by_id = {project["id"]: project for project in projects}
        pinned = sorted((project for project in projects
                         if type(project.get("quick_access_order")) is int),
                        key=lambda project: project["quick_access_order"])
        children = {}
        for project in projects:
            children.setdefault(project.get("parent_id"), []).append(project)
        ordered = []
        visited = set()

        def append_branch(project):
            project_id = project["id"]
            if project_id in visited:
                return
            visited.add(project_id)
            ordered.append(project)
            for child in children.get(project_id, ()):
                append_branch(child)

        for root in children.get(None, ()):
            append_branch(root)
        for project in projects:
            append_branch(project)
        self._current_id = current_id
        self.all_tab.setText("文件夹")
        self.quick_tab.setText("快速访问")
        self._set_scope(False)
        for project in ordered:
            names, parent = [project["name"]], project.get("parent_id")
            seen = {project["id"]}
            while parent and parent in by_id and parent not in seen:
                seen.add(parent)
                ancestor = by_id[parent]
                names.insert(0, ancestor["name"])
                parent = ancestor.get("parent_id")
            title = " / ".join(names)
            item = QListWidgetItem(project["name"])
            item.setIcon(folder_tree_icon(False))
            item.setData(Qt.ItemDataRole.UserRole, project["id"])
            item.setData(Qt.ItemDataRole.UserRole + 1, project in pinned)
            item.setData(_SWITCH_DEPTH, len(names) - 1)
            item.setData(_SWITCH_PARENT, names[-2] if len(names) > 1 else "")
            item.setToolTip(title)
            self.folders.addItem(item)
            if project["id"] == current_id:
                self.folders.setCurrentItem(item)
        self.search.clear()
        self._filter("")
        if self.folders.currentItem() is None and self.folders.count():
            self.folders.setCurrentRow(0)

    def _filter(self, query):
        query = query.strip().casefold()
        self.folders.itemDelegate().flat = bool(query) or self._quick_only
        self.folders.itemDelegate().query = query
        first = None
        for row in range(self.folders.count()):
            item = self.folders.item(row)
            visible = (not self._quick_only or item.data(Qt.ItemDataRole.UserRole + 1)) and (
                not query or query in item.toolTip().casefold())
            item.setHidden(not visible)
            if visible and first is None:
                first = item
        if first is not None:
            current = self.folders.currentItem()
            if query or current is None or current.isHidden():
                self.folders.setCurrentItem(first)
        else:
            self.folders.setCurrentRow(-1)
        self.folders.viewport().update()

    def _activate_current(self):
        self._activate(self.folders.currentItem())

    def _activate(self, item):
        if item is not None and not item.isHidden():
            self.folderSelected.emit(item.data(Qt.ItemDataRole.UserRole))


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
        theme_icon("search", 14).paint(
            painter, 8, 7, 14, 14, Qt.AlignmentFlag.AlignCenter, mode)
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
        # Draw hover in the same tone as the selected toolbar state.
        option.state &= ~QStyle.StateFlag.State_MouseOver
        painter = QPainter(self)
        self.style().drawComplexControl(QStyle.ComplexControl.CC_ToolButton, option, painter, self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._hover_amount and self.isEnabled():
            painter.setOpacity(self._hover_amount)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(ui_color("#2f2f33"))
            painter.drawRoundedRect(QRectF(self.rect()), 5, 5)
            painter.setOpacity(1)
        size = self.iconSize()
        target = QRectF((self.width() - size.width()) / 2,
                        (self.height() - size.height()) / 2, size.width(), size.height())
        active = (self._hover_amount or self.property("filtered") == "true"
                  or (self.isChecked() and self.objectName() != "viewMode"))
        mode = (QIcon.Mode.Disabled if not self.isEnabled() else
                QIcon.Mode.Active if active else QIcon.Mode.Normal)
        pixmap = self.icon().pixmap(size * self.devicePixelRatioF(), mode,
                                  QIcon.State.On if self.isChecked() else QIcon.State.Off)
        painter.setOpacity(0.8 + 0.2 * float(bool(active)))
        painter.drawPixmap(target, pixmap, QRectF(pixmap.rect()))
        painter.end()


class ZoomStepButton(ToolbarIconButton):
    def __init__(self, step: int):
        super().__init__()
        self.step = step
        self.setIcon(theme_icon(
            "toolbar.zoom.in" if step > 0 else "toolbar.zoom.out", ZOOM_ICON_SIZE.width()))
        self.setIconSize(ZOOM_ICON_SIZE)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        if self._hover_amount and self.isEnabled():
            painter.setOpacity(self._hover_amount)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(ui_color("#2f2f33"))
            painter.drawRoundedRect(QRectF(self.rect()), 5, 5)
        painter.setOpacity(0.5 + 0.5 * self._hover_amount)
        size = self.iconSize()
        self.icon().paint(painter, (self.width() - size.width()) // 2,
                          (self.height() - size.height()) // 2,
                          size.width(), size.height(),
                          Qt.AlignmentFlag.AlignCenter,
                          QIcon.Mode.Disabled if not self.isEnabled() else QIcon.Mode.Normal)
        painter.end()


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
