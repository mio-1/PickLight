"""General preferences: draft editing, reversible appearance preview, explicit apply."""

from dataclasses import replace

from PySide6.QtCore import QPoint, QRectF, QSize, QTimer, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QFrame,
    QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QMenu, QScrollArea, QStackedWidget, QToolButton, QVBoxLayout, QWidget)

from picklight.appearance import configure_appearance, ui_color
from picklight.paths import asset_path
from picklight.folder_dialogs import FolderModal
from picklight.platform_effects import gpu_available, transparency_available
from picklight.preferences import APPEARANCES, SCALES, LoginStartup
from picklight.ui.graphics import theme_icon
from picklight.ui.menus import ColorManagementMenu
from picklight.themes import theme_manager
from picklight.ui.shortcut_preferences import PreferencesSearchEdit, ShortcutPreferences


class ThemeSwatch(QToolButton):
    def __init__(self, name, title, color, parent):
        super().__init__(parent)
        self.name, self.color = name, color
        self.setCheckable(True)
        self.setFixedSize(26, 28)
        self.setAccessibleName(title)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(4, 5, -4, -5)
        painter.setBrush(QColor(self.color))
        painter.setPen(QColor(255, 255, 255, 45))
        painter.drawRoundedRect(rect, 5, 5)
        if self.name == "auto":
            painter.save()
            painter.setClipRect(rect.adjusted(rect.width() // 2, 0, 0, 0))
            painter.setBrush(QColor("#18191c"))
            painter.drawRoundedRect(rect, 5, 5)
            painter.restore()
        if self.isChecked() or self.underMouse():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(ui_color("#f7f8f8" if self.isChecked() else "#929397"), 1.2))
            painter.drawRoundedRect(rect.adjusted(-3, -3, 3, 3), 7, 7)
        painter.end()


class PreferenceOptionsMenu(ColorManagementMenu):
    def __init__(self, combo):
        super().__init__(combo)
        self.setTitle(combo.accessibleName() or "选择")
        self.setObjectName("preferencesOptionsMenu")
        self.setFixedWidth(combo.width() + 20)
        self.setStyleSheet('''
            QMenu#preferencesOptionsMenu { background: transparent; border: 0; padding: 13px 11px; }
            QMenu#preferencesOptionsMenu::item { background: transparent; color: #f7f8f8;
                font-size: 12px; padding: 0 6px; margin: 0; min-height: 18px; border-radius: 0; }
            QMenu#preferencesOptionsMenu::item:selected { background: #2f98ff; color: #ffffff; }
            QMenu#preferencesOptionsMenu::indicator { width: 0; height: 0; }
        ''')

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        surface = QRectF(self.rect()).adjusted(10, 10, -10, -10)
        painter.setPen(Qt.PenStyle.NoPen)
        for spread in range(8, 0, -1):
            painter.setBrush(QColor(0, 0, 0, 3 + (8 - spread) // 2))
            painter.drawRoundedRect(surface.adjusted(-spread, -spread + 2, spread, spread + 2), 4 + spread, 4 + spread)
        painter.setBrush(ui_color("#2d2e30"))
        painter.setPen(QPen(ui_color("#4a4b4e"), 1))
        painter.drawRoundedRect(surface.adjusted(.5, .5, -.5, -.5), 4, 4)
        painter.end()
        QMenu.paintEvent(self, event)


class PreferenceCombo(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._popup = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _popup_state(self, opened):
        self.setProperty("popupOpen", opened)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def showPopup(self):
        if not self.count() or self._popup is not None:
            return
        popup = PreferenceOptionsMenu(self)
        self._popup = popup
        for index in range(self.count()):
            action = popup.addAction(self.itemText(index))
            action.triggered.connect(lambda _, value=index: self.setCurrentIndex(value))
        def closed():
            self._popup = None
            self._popup_state(False)
            QComboBox.hidePopup(self)  # Reset Qt's combobox state for a custom popup.
            popup.deleteLater()
        popup.aboutToHide.connect(closed)
        self._popup_state(True)
        popup.popup(self.mapToGlobal(QPoint(-10, self.height() - 10)))
        popup.setActiveAction(popup.actions()[self.currentIndex()])

    def hidePopup(self):
        if self._popup is not None:
            self._popup.hide()
        else:
            super().hidePopup()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        theme_icon("preferences.dropdown", 12).paint(painter, self.width() - 17, (self.height() - 12) // 2, 12, 12)
        painter.end()


class PreferencesDialog(FolderModal):
    def __init__(self, parent):
        super().__init__(parent)
        self.owner = parent
        self.baseline = parent.preferences
        self.setWindowTitle("偏好设置")
        self.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)
        self.resize(888, 650)
        self.setMinimumSize(740, 545)
        self.layout().setContentsMargins(24, 24, 24, 24)
        self.surface.setObjectName("preferencesSurface")
        shadow = QGraphicsDropShadowEffect(self.surface)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(0, 0, 0, 130))
        self.surface.setGraphicsEffect(shadow)
        self.surface.setStyleSheet("""
            QFrame#preferencesSurface { background: #202124; border: 1px solid #414246; border-radius: 9px; }
            QWidget#preferencesContent { background: #26272a; border: 1px solid #393a3e; border-radius: 8px; }
            QFrame#preferencesCard { background: #2c2d30; border: 1px solid #404145; border-radius: 8px; }
            QFrame#preferencesDivider { background: #3b3c40; border: 0; }
            QLabel { background: transparent; border: 0; }
            QLabel#preferencesHeading { font-size: 13px; font-weight: 600; }
            QLabel#preferencesHint { color: #999a9e; font-size: 11px; }
            QLabel#preferencesError { color: #f2797d; font-size: 12px; }
            QPushButton#preferencesGeneral { text-align: left; background: transparent; border: 0; border-radius: 6px; padding: 8px; font-weight: 600; }
            QPushButton#preferencesGeneral[selected="true"] { background: #36373b; }
            QLineEdit#preferencesSearch { background: #191a1c; border: 1px solid #343538; border-radius: 6px; padding: 0; font-size: 13px; placeholder-text-color: #bdbec4; }
            QLineEdit#preferencesSearch:focus { border-color: #2f98ff; }
            QComboBox { background: transparent; border: 1px solid transparent; border-radius: 6px; padding: 4px 7px; }
            QComboBox:hover { background: #36373b; border-color: #414246; }
            QComboBox[popupOpen="true"] { background: #191a1c; border-color: #414246; }
            QComboBox::drop-down { width: 17px; border: 0; }
            QComboBox QAbstractItemView { background: #202124; border: 1px solid #414246; selection-background-color: #36373b; padding: 4px; }
            QCheckBox { spacing: 7px; min-height: 24px; }
            QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #696a6e; border-radius: 3px; background: #242528; }
            QCheckBox::indicator:checked { background: #2f98ff; border-color: #2f98ff; }
            QCheckBox:disabled { color: #929397; }
            QPushButton#preferencesSave { background: #2f98ff; border: 1px solid #4ba6ff; border-radius: 6px; padding: 8px 16px; font-weight: 600; color: #ffffff; }
            QPushButton#preferencesSave:hover { background: #42a2ff; }
            QPushButton#preferencesApply, QPushButton#preferencesRestart { background: #343538; border: 1px solid #494a4e; border-radius: 6px; padding: 8px 16px; }
            QPushButton#preferencesApply:hover, QPushButton#preferencesRestart:hover { background: #414246; }
            QFrame#shortcutRow { background: transparent; border: 0; border-radius: 5px; }
            QFrame#shortcutRow[alternate="true"] { background: #303134; }
            QKeySequenceEdit#shortcutEditor { background: transparent; border: 0; }
            QKeySequenceEdit#shortcutEditor QLineEdit { background: transparent; color: #bdbec4; placeholder-text-color: #929397; border: 1px solid transparent; border-radius: 4px; padding: 3px 6px; }
            QKeySequenceEdit#shortcutEditor QLineEdit:hover { background: #36373b; }
            QKeySequenceEdit#shortcutEditor QLineEdit:focus { background: #202124; border-color: #2f98ff; }
            QKeySequenceEdit#shortcutEditor QLineEdit[conflict="true"]:focus { border-color: #f5a400; }
            QLabel#shortcutConflict { background: #db8a00; color: #ffffff; border: 1px solid #ffb126; border-radius: 4px; padding: 3px 7px; font-size: 11px; font-weight: 600; }
            QPushButton#shortcutsRestore { background: #303134; border: 1px solid #494a4e; border-radius: 5px; padding: 8px; }
            QPushButton#shortcutsRestore:hover { background: #3b3c40; }
            QToolButton#preferencesClose { margin: 4px; border: 0; border-radius: 4px; background: transparent; }
            QToolButton#preferencesClose:hover { background: #303134; }
        """)
        check = asset_path("check").replace("\\", "/")
        self.surface.setStyleSheet(self.surface.styleSheet() + f'''
            QCheckBox::indicator:checked {{ image: url("{check}"); }}
            QCheckBox::indicator:disabled {{ background: #45464a; border-color: #56575b; }}
            QComboBox::down-arrow {{ image: none; width: 12px; height: 12px; }}
        ''')
        layout = QHBoxLayout(self.surface)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        sidebar = QWidget()
        sidebar.setFixedWidth(200)
        nav = QVBoxLayout(sidebar)
        nav.setContentsMargins(4, 10, 4, 10)
        nav.setSpacing(8)
        nav.addWidget(QLabel("偏好设置", objectName="preferencesHeading"))
        nav.addSpacing(4)
        self.search = PreferencesSearchEdit()
        self.search.setAccessibleName("搜索偏好设置")
        nav.addWidget(self.search)
        self.general_button = QPushButton("常用", objectName="preferencesGeneral")
        self.general_button.setProperty("selected", True)
        self.general_button.setIcon(theme_icon("preferences.general", 18))
        self.page_name = "general"
        self.general_button.clicked.connect(lambda: self._select_page("general"))
        nav.addWidget(self.general_button)
        self.shortcuts_button = QPushButton("快捷键", objectName="preferencesGeneral")
        self.shortcuts_button.setProperty("selected", False)
        self.shortcuts_button.setIcon(theme_icon("preferences.shortcuts", 18))
        self.shortcuts_button.clicked.connect(lambda: self._select_page("shortcuts"))
        nav.addWidget(self.shortcuts_button)
        nav.addStretch()
        layout.addWidget(sidebar)
        content = QWidget(objectName="preferencesContent")
        right = QVBoxLayout(content)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(16, 10, 12, 6)
        self.heading = QLabel("常用", objectName="preferencesHeading")
        head.addWidget(self.heading)
        head.addStretch()
        self.close_button = QToolButton(objectName="preferencesClose")
        self.close_button.setIcon(theme_icon("modal.close", 22))
        self.close_button.setIconSize(QSize(22, 22))
        self.close_button.setFixedSize(32, 32)
        self.close_button.setAccessibleName("关闭偏好设置")
        self.close_button.clicked.connect(self.reject)
        head.addWidget(self.close_button)
        right.addLayout(head)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        cards = QVBoxLayout(body)
        cards.setContentsMargins(16, 4, 16, 16)
        cards.setSpacing(12)
        self.appearance_card, appearance = self._card("外观")
        cards.addWidget(self.appearance_card)
        theme_row = QHBoxLayout()
        theme_row.addWidget(QLabel("配色"))
        theme_row.addStretch()
        self.theme_group = QButtonGroup(self)
        self.swatches = {}
        for name, title, color in APPEARANCES:
            button = ThemeSwatch(name, title, color, self)
            self.theme_group.addButton(button)
            button.setChecked(name == self.baseline.appearance)
            button.clicked.connect(lambda _, value=name: self._preview_theme(value))
            theme_row.addWidget(button)
            self.swatches[name] = button
        theme_row.setSpacing(2)
        theme_choice = QHBoxLayout()
        theme_choice.addWidget(QLabel("主题"))
        theme_choice.addStretch()
        self.icon_theme = PreferenceCombo()
        self.icon_theme.setAccessibleName("主题")
        self.icon_theme.setFixedWidth(190)
        manager = theme_manager()
        for theme in manager.themes():
            self.icon_theme.addItem(theme.name, theme.id)
        self.icon_theme.setCurrentIndex(max(0, self.icon_theme.findData(manager.active.id)))
        theme_choice.addWidget(self.icon_theme)
        appearance.addLayout(theme_choice)
        appearance.addLayout(theme_row)
        appearance.addWidget(self._divider())
        options = QHBoxLayout()
        options.addWidget(QLabel("语言"))
        options.addStretch()
        self.language = PreferenceCombo()
        self.language.addItem("简体中文", "zh_CN")
        self.language.setAccessibleName("语言")
        options.addWidget(self.language)
        separator = self._divider()
        separator.setFixedSize(1, 24)
        options.addWidget(separator)
        options.addSpacing(6)
        options.addWidget(QLabel("缩放程度"))
        options.addStretch()
        self.scale = PreferenceCombo()
        self.scale.setAccessibleName("缩放程度")
        for value in SCALES:
            self.scale.addItem(f"{value}%", value)
        self.scale.setCurrentIndex(self.scale.findData(self.baseline.scale))
        self.scale.currentIndexChanged.connect(self._update_restart_hint)
        options.addWidget(self.scale)
        appearance.addLayout(options)
        appearance.addWidget(self._divider())
        self.transparency = self._check("启用透明效果", self.baseline.transparency, appearance)
        if not transparency_available():
            self.transparency.setEnabled(False)
            appearance.addWidget(QLabel("透明效果需要 Windows 11 22H2 或更高版本", objectName="preferencesHint"))
        appearance.addWidget(self._divider())
        self.counts = self._check("在侧栏显示数量", self.baseline.sidebar_counts, appearance)
        self.startup_card, startup = self._card("启动项")
        cards.addWidget(self.startup_card)
        self.autostart = self._check("开机自动启动", self.baseline.launch_at_login, startup)
        self.autostart.setEnabled(LoginStartup.available())
        if self.autostart.isEnabled():
            try:
                self.autostart.setChecked(bool(LoginStartup().read()))
            except OSError:
                startup.addWidget(QLabel("无法读取系统启动项，保存时将重新尝试", objectName="preferencesHint"))
        self.gpu = self._check("启用 GPU 硬件加速（可能会占用较多内存）", self.baseline.gpu, startup)
        self.gpu.setEnabled(gpu_available())
        self.empty = QLabel("没有匹配的设置", objectName="preferencesHint")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.hide()
        cards.addWidget(self.empty)
        cards.addStretch()
        scroll.setWidget(body)
        self.pages = QStackedWidget()
        self.pages.addWidget(scroll)
        self.shortcut_page = ShortcutPreferences(parent.shortcuts)
        self.pages.addWidget(self.shortcut_page)
        right.addWidget(self.pages, 1)
        footer = QVBoxLayout()
        footer.setContentsMargins(16, 8, 12, 12)
        footer.setSpacing(6)
        self.status = QLabel(objectName="preferencesHint")
        self.status.setWordWrap(True)
        footer.addWidget(self.status)
        buttons = QHBoxLayout()
        self.restart_button = QPushButton("立即重启", objectName="preferencesRestart")
        self.restart_button.clicked.connect(self._restart)
        self.restart_button.hide()
        buttons.addWidget(self.restart_button)
        buttons.addStretch()
        self.save_button = QPushButton("保存设置", objectName="preferencesSave")
        self.apply_button = QPushButton("应用", objectName="preferencesApply")
        for button in (self.save_button, self.apply_button):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setAutoDefault(False)
            buttons.addWidget(button)
        self.save_button.clicked.connect(lambda: self._apply(close=True))
        self.apply_button.clicked.connect(lambda: self._apply(close=False))
        footer.addLayout(buttons)
        right.addLayout(footer)
        layout.addWidget(content, 1)
        self.search.textChanged.connect(self._filter)
        self.shortcut_page.changed.connect(self._update_restart_hint)
        self._update_restart_hint()
        self.restart_button.setVisible(self.baseline.scale != self.owner.startup_scale)

    @staticmethod
    def _card(title):
        card = QFrame(objectName="preferencesCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(QLabel(title, objectName="preferencesHeading"))
        return card, layout

    @staticmethod
    def _divider():
        line = QFrame(objectName="preferencesDivider")
        line.setFixedHeight(1)
        return line

    @staticmethod
    def _check(text, checked, layout):
        checkbox = QCheckBox(text)
        checkbox.setChecked(checked)
        checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(checkbox)
        return checkbox

    def _select_page(self, name):
        self.page_name = name
        if name == "shortcuts":
            self.shortcut_page.search.clear()
        self.search.clear()
        self._filter("")

    def _filter(self, query):
        query = query.strip().casefold()
        themes = " ".join(self.icon_theme.itemText(index) for index in range(self.icon_theme.count()))
        for card, keywords in ((self.appearance_card, "外观 配色 主题 自动 浅色 浅灰 深灰 深色 深蓝 深紫 语言 简体中文 缩放程度 透明效果 侧栏显示数量 " + themes),
                               (self.startup_card, "启动项 开机自动启动 GPU 硬件加速 内存 渲染")):
            card.setVisible(not query or query in keywords.casefold())
        self.empty.setVisible(self.appearance_card.isHidden() and self.startup_card.isHidden())
        page = self.page_name
        if query:
            page = "shortcuts" if (query in "快捷键" or
                (self.appearance_card.isHidden() and self.startup_card.isHidden() and self.shortcut_page.matches(query))) else "general"
            self.shortcut_page.search.setText("" if query in "快捷键" else query)
        self.pages.setCurrentIndex(1 if page == "shortcuts" else 0)
        self.heading.setText("快捷键" if page == "shortcuts" else "常用")
        for button, name in ((self.general_button, "general"), (self.shortcuts_button, "shortcuts")):
            button.setProperty("selected", not query and page == name)
            button.style().unpolish(button)
            button.style().polish(button)
            button.update()

    def _preview_theme(self, name):
        configure_appearance(name)
        self.owner._refresh_preference_effects()

    def draft(self):
        return replace(self.baseline, appearance=self.theme_group.checkedButton().name,
                       scale=self.scale.currentData(), transparency=self.transparency.isChecked(),
                       sidebar_counts=self.counts.isChecked(), launch_at_login=self.autostart.isChecked(),
                       gpu=self.gpu.isChecked())

    def _update_restart_hint(self, *_):
        pending = self.scale.currentData() != getattr(self.owner, "startup_scale", 100)
        error = self.shortcut_page.error()
        self.status.setObjectName("preferencesError" if error else "preferencesHint")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.status.setText("" if error else ("缩放程度将在下次启动时生效" if pending else ""))
        self.save_button.setEnabled(not error)
        self.apply_button.setEnabled(not error)

    def _apply(self, *, close):
        try:
            self.owner._apply_preferences(self.draft(), shortcuts=self.shortcut_page.values())
        except (OSError, ValueError) as error:
            self.status.setObjectName("preferencesError")
            self.status.setText(f"无法保存设置：{error}")
            return False
        self.baseline = self.owner.preferences
        self.status.setObjectName("preferencesHint")
        pending = self.baseline.scale != self.owner.startup_scale
        self.status.clear()
        self.restart_button.setVisible(pending)
        theme_id = self.icon_theme.currentData()
        if theme_id != theme_manager().active.id:
            owner, query = self.owner, self.search.text()
            self.accept()
            # Release the old modal before rebuilding its parent. "Apply"
            # reopens preferences on the new window; "Save" keeps them closed.
            QTimer.singleShot(0, lambda: owner._switch_theme_from_preferences(theme_id, not close, query))
        elif close:
            self.accept()
        return True

    def _restart(self):
        if self._apply(close=False):
            self.owner._restart_application(self)

    def showEvent(self, event):
        screen = self.owner.screen().availableGeometry()
        self.setMinimumSize(min(740, screen.width() - 16), min(545, screen.height() - 16))
        self.resize(min(self.width(), screen.width() - 16), min(self.height(), screen.height() - 16))
        super().showEvent(event)

    def done(self, result):
        # Closing discards edits after the most recent Apply, including preview.
        for combo in (self.language, self.scale, self.icon_theme):
            combo.hidePopup()
        configure_appearance(self.baseline.appearance)
        self.owner._refresh_preference_effects()
        super().done(result)
