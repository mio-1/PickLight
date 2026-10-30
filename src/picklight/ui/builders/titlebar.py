"""Build the titlebar region."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QSize
from PySide6.QtGui import QActionGroup, QKeySequence
from PySide6.QtWidgets import QHBoxLayout, QMenu

from picklight.chrome import TitleBar, TitleBarSegment, WindowControlButton
from picklight.color_management import COLOR_MODES
from picklight.ui.common import TOOLBAR_ICON_SIZE
from picklight.ui.graphics import theme_icon
from picklight.ui.menus import ColorManagementMenu
from picklight.ui.toolbar import ToolbarIconButton


def build_titlebar(self, outer):
    self.title_bar = TitleBar(self)
    top_layout = QHBoxLayout(self.title_bar)
    top_layout.setContentsMargins(0, 0, 0, 0)
    top_layout.setSpacing(0)
    self.title_left = TitleBarSegment(self)
    self.title_left.setFixedWidth(self._expanded_sidebar_width if not self._sidebar_collapsed else 90)
    left_controls = QHBoxLayout(self.title_left)
    left_controls.setContentsMargins(13, 8, 12, 0)
    left_controls.setSpacing(0)
    top_layout.addWidget(self.title_left)
    self.viewer_toolbar = TitleBarSegment(self, "viewerToolbar")
    top_layout.addWidget(self.viewer_toolbar, 1)
    self.title_right = TitleBarSegment(self)
    self.title_right.setFixedWidth(self._inspector_width)
    right_controls = QHBoxLayout(self.title_right)
    right_controls.setContentsMargins(0, 0, 0, 0)
    right_controls.setSpacing(0)
    right_controls.addStretch()
    top_layout.addWidget(self.title_right)
    self.menu_button = ToolbarIconButton()
    self.menu_button.setObjectName("menuButton")
    self.menu_button.setAccessibleName("主菜单")
    self.menu_button.setIcon(theme_icon("app.menu", 16))
    self.menu_button.setIconSize(TOOLBAR_ICON_SIZE)
    self.menu_button.setFixedSize(26, 26)
    self.main_menu = QMenu(self.menu_button)
    self.main_menu.setObjectName("mainMenu")
    self.main_menu.setFixedWidth(190)
    self.color_management_menu = ColorManagementMenu(self.main_menu)
    self.main_menu.addMenu(self.color_management_menu)
    self.preferences_action = self.main_menu.addAction("偏好设置…")
    self.preferences_action.triggered.connect(self._show_preferences)
    self.color_mode_group = QActionGroup(self.color_management_menu)
    self.color_mode_group.setExclusive(True)
    self.color_mode_actions = {}
    for mode, title in COLOR_MODES:
        action = self.color_management_menu.addAction(title)
        action.setCheckable(True)
        action.setData(mode)
        self.color_mode_group.addAction(action)
        action.setChecked(mode == self.color_mode)
        action.triggered.connect(lambda checked, value=mode: self._set_color_mode(value) if checked else None)
        self.color_mode_actions[mode] = action
    self.main_menu.addSeparator()
    self.check_update_action = self.main_menu.addAction("检查更新")
    self.check_update_action.setVisible(False)
    self.check_update_action.triggered.connect(self._show_update_dialog)
    self.about_action = self.main_menu.addAction("关于 PickLight")
    self.about_action.triggered.connect(self._show_about_dialog)
    self.main_menu.addSeparator()
    self.exit_action = self.main_menu.addAction("退出")
    self.exit_action.setShortcut(QKeySequence("Alt+F4"))
    self.exit_action.triggered.connect(self.close)
    self.menu_button.clicked.connect(lambda: self.main_menu.popup(
        self.menu_button.mapToGlobal(QPoint(self.menu_button.width() - 2, 10))))
    left_controls.addWidget(self.menu_button)
    self.sidebar_toggle = ToolbarIconButton(self.title_left)
    self.sidebar_toggle.setObjectName("sidebarToggle")
    self.sidebar_toggle.setIcon(theme_icon("toggle.sidebar", 14))
    self.sidebar_toggle.setIconSize(QSize(14, 14))
    self.sidebar_toggle.setFixedSize(26, 26)
    self.sidebar_toggle.setCheckable(True)
    self.sidebar_toggle.setChecked(self._sidebar_collapsed)
    self.sidebar_toggle.setToolTip("左栏")
    self.sidebar_toggle.setAccessibleName(self.sidebar_toggle.toolTip())
    self.sidebar_toggle.clicked.connect(self._set_sidebar_collapsed)
    left_controls.addStretch()
    left_controls.addWidget(self.sidebar_toggle)
    self.minimize_button = WindowControlButton("minimize")
    self.minimize_button.clicked.connect(self.showMinimized)
    right_controls.addWidget(self.minimize_button)
    self.maximize_button = WindowControlButton("maximize")
    self.maximize_button.clicked.connect(self.toggle_maximize)
    right_controls.addWidget(self.maximize_button)
    self.close_button = WindowControlButton("close")
    self.close_button.clicked.connect(self.close)
    right_controls.addWidget(self.close_button)
    outer.addWidget(self.title_bar)
