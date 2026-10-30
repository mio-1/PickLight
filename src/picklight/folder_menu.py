"""Folder appearance controls using registered semantic theme resources."""

from functools import lru_cache
import json
import re

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QGridLayout,
    QHBoxLayout,
    QMenu,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from picklight.paths import asset_path
from pathlib import Path


FOLDER_COLORS = (
    ("默认", ""), ("红色", "#ff453a"), ("橙色", "#ff9f0a"),
    ("黄色", "#ffd60a"), ("绿色", "#30d159"), ("青色", "#40cbe0"),
    ("蓝色", "#00aaff"), ("紫色", "#c499ff"), ("粉色", "#ff99cc"),
)


class FolderContextMenu(QMenu):
    """Keep Eagle's compact width without Qt reserving a shortcut column on every row."""

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        action = self.actionAt(event.position().toPoint())
        if isinstance(action, QWidgetAction):
            self.setActiveAction(action)
            for candidate in self.actions():
                if candidate.menu() is not None:
                    candidate.menu().hide()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        from picklight.appearance import theme_font
        font = theme_font()
        font.setPixelSize(11)
        painter.setFont(font)
        for action in self.actions():
            shortcut = action.property("displayShortcut")
            if not shortcut or not action.isVisible():
                continue
            painter.setPen(QColor("#96979b" if action.isEnabled() else "#626368"))
            rect = QRectF(self.actionGeometry(action)).adjusted(0, 0, -12, 0)
            painter.drawText(rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             QKeySequence(shortcut).toString(QKeySequence.SequenceFormat.NativeText))
        painter.end()

    def keyPressEvent(self, event):
        sequence = QKeySequence(event.keyCombination())
        for action in self.actions():
            shortcut = action.property("displayShortcut")
            if shortcut and action.isEnabled() and sequence == QKeySequence(shortcut):
                self.close()
                action.trigger()
                event.accept()
                return
        super().keyPressEvent(event)


@lru_cache(maxsize=1)
def folder_icon_names():
    names = json.loads(Path(asset_path("folder.icons.index")).read_text("utf-8"))
    return tuple(name for name in names if re.fullmatch(r"[a-zA-Z0-9_-]+", name))


class FolderColorButton(QToolButton):
    def __init__(self, name, color, selected):
        super().__init__()
        self.color = color
        self.setFixedSize(16, 22)
        self.setToolTip(name)
        self.setAccessibleName(name + "文件夹")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setCheckable(True)
        self.setChecked(selected)

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self.color or "#bdbec0"))
        painter.drawEllipse(QRectF(0, 3, 16, 16))
        if self.underMouse() or self.isChecked() or self.hasFocus():
            painter.setPen(QPen(QColor("#ffffff"), 1.4))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QRectF(1.5, 4.5, 13, 13))
        painter.end()


class FolderColorRow(QWidget):
    colorSelected = Signal(str)
    hovered = Signal()

    def __init__(self, current=""):
        super().__init__()
        self.buttons = {}
        self.button_group = QButtonGroup(self)
        self.button_group.setExclusive(True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(28, 2, 28, 2)
        layout.setSpacing(8)
        for name, color in FOLDER_COLORS:
            button = FolderColorButton(name, color, current == color)
            self.button_group.addButton(button)
            button.clicked.connect(lambda checked=False, value=color: self.colorSelected.emit(value))
            layout.addWidget(button)
            self.buttons[color] = button

    def enterEvent(self, event):
        # Embedded menu widgets do not notify QMenu that another action was hovered.
        self.hovered.emit()
        super().enterEvent(event)


class FolderIconPicker(QWidget):
    iconSelected = Signal(str)

    def __init__(self, icon_factory, current=""):
        super().__init__()
        self.setObjectName("folderIconPicker")
        self.setFixedSize(324, 388)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)
        self.reset_button = QPushButton("默认文件夹图标")
        self.reset_button.setObjectName("folderIconReset")
        self.reset_button.setFixedHeight(26)
        self.reset_button.clicked.connect(lambda: self.iconSelected.emit(""))
        layout.addWidget(self.reset_button)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        grid = QGridLayout(content)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)
        grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        labels = {"camera": "相机", "aperture": "光圈", "film": "胶片", "image": "图片",
                  "home": "主页", "star": "星星", "heart": "爱心", "book": "书籍",
                  "work": "工作", "folder": "文件夹", "cloud": "云", "music": "音乐",
                  "video": "视频", "cat": "猫", "dog": "狗", "travel": "旅行"}
        self.buttons = {}
        for index, name in enumerate(folder_icon_names()):
            button = QToolButton()
            button.setObjectName("folderIconOption")
            button.setFixedSize(24, 24)
            button.setIconSize(QSize(20, 20))
            button.setCheckable(True)
            button.setChecked(current == name)
            button.setToolTip(labels.get(name, name.replace("-", " ").replace("_", " ")))
            button.setAccessibleName(button.toolTip())
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda checked=False, value=name: self.iconSelected.emit(value))
            grid.addWidget(button, index // 13, index % 13)
            self.buttons[name] = button
        scroll.setWidget(content)
        layout.addWidget(scroll)
        # The chooser previews shapes neutrally, independently of folder colors.
        self.reset_button.setIcon(icon_factory(False, False, "", "#d2d3d5"))
        for name, button in self.buttons.items():
            button.setIcon(icon_factory(False, False, name, "#d2d3d5"))
