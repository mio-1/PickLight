"""Application chrome colors, independent of photo pixels and icon packages."""

import re
from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication, QAbstractButton, QWidget

_appearance = "dark"
_effective = "dark"
_manager = None
_theme_style = {}


def is_light():
    return _effective in ("light", "lightgray")


def theme_font(role="ui", default="Segoe UI"):
    font = QFont()
    font.setFamilies(_theme_style.get("typography", {}).get(role) or [default])
    return font


def ui_color(value):
    """Map only neutral UI colors; never pass photo or color-picker data here."""
    color = QColor(value)
    if not color.isValid():
        return color
    mapped = _theme_style.get("colors", {}).get(color.name())
    if mapped:
        alpha = color.alpha()
        color = QColor(mapped)
        color.setAlpha(alpha)
    if _effective == "dark":
        return color
    r, g, b, a = color.getRgb()
    if max(r, g, b) - min(r, g, b) > 24:
        return color
    v = (r + g + b) / 3
    if is_light():
        v = min(255, (267 if _effective == "light" else 247) - v * .92)
        return QColor(round(v), round(v), round(v), a)
    shifts = {"gray": (24, 24, 24), "blue": (17, 20, 37), "purple": (26, 17, 34)}
    if v < 128:
        dr, dg, db = shifts.get(_effective, (0, 0, 0))
        return QColor(min(255, r + dr), min(255, g + dg), min(255, b + db), a)
    return color


def style_sheet(source):
    if _effective == "dark" and not _theme_style:
        return source
    # Keep blue primary-button text white; semantic accents retain their hue.
    source = re.sub(r"#[0-9a-fA-F]{6}\b", lambda m: ui_color(m[0]).name(), source)
    def rgba(match):
        color = ui_color(QColor(*[int(match[i]) for i in range(1, 5)]))
        return f"rgba({color.red()},{color.green()},{color.blue()},{color.alpha()})"
    source = re.sub(r"rgba\((\d+),\s*(\d+),\s*(\d+),\s*(\d+)\)", rgba, source)
    typography = _theme_style.get("typography", {})
    if typography:
        def family(match):
            role = "mono" if re.search("mono|consolas", match[1], re.I) else "ui"
            names = typography.get(role)
            return "font-family: " + ", ".join(f'"{name}"' for name in names) + ";" if names else match[0]
        source = re.sub(r"font-family:\s*([^;]+);", family, source)
        weight = typography.get("heading_weight")
        if weight:
            source = re.sub(r"font-weight:\s*(600|700)\b", f"font-weight: {weight}", source)
    if _theme_style and not is_light():
        source = re.sub(r"\bwhite\b", ui_color("#ffffff").name(), source)
    if is_light():
        source = re.sub(r"\bwhite\b", "#242424", source)
        source += '\nQPushButton#folderModalPrimary, QPushButton#preferencesSave, QPushButton#primaryButton { color: #ffffff; }'
    primary = _theme_style.get("primary", {})
    if primary:
        def primary_rule(match):
            selectors, body = match.groups()
            if not re.search(r"QPushButton#(?:folderModalPrimary|preferencesSave|primary)\b", selectors):
                return match[0]
            if ":hover" in selectors:
                colors = {"background": primary.get("hover")}
            elif ":" in selectors:
                return match[0]
            else:
                colors = {"background": primary.get("background"),
                          "border-color": primary.get("border"), "color": primary.get("text")}
            additions = " ".join(f"{name}: {value};" for name, value in colors.items() if value)
            return selectors + "{" + body.rstrip().rstrip(";") + "; " + additions + " }"
        source = re.sub(r"([^{}]+)\{([^{}]*)\}", primary_rule, source)
    return source


class AppearanceManager(QObject):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self._styling = False
        self.icon_specs = {}
        app.installEventFilter(self)
        app.styleHints().colorSchemeChanged.connect(self.system_changed)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Polish and isinstance(obj, QWidget):
            self.style_widget(obj)
        return False

    def style_widget(self, widget):
        if self._styling or widget.property("preserveContentColors"):
            return
        source = widget.styleSheet()
        if source:
            last = getattr(widget, "_appearance_qss_rendered", None)
            if source != last:
                widget._appearance_qss_source = source
            rendered = style_sheet(widget._appearance_qss_source)
            widget._appearance_qss_rendered = rendered
            if source != rendered:
                self._styling = True
                try:
                    widget.setStyleSheet(rendered)
                finally:
                    self._styling = False

    def system_changed(self, *_):
        if _appearance == "auto":
            self.apply("auto")

    def apply(self, name):
        global _appearance, _effective, _theme_style
        from picklight.themes import theme_manager
        active_theme = theme_manager().active
        _theme_style = active_theme.manifest.get("style", {})
        if _theme_style:
            _theme_style = {**_theme_style, "colors": {
                key.lower(): value for key, value in _theme_style.get("colors", {}).items()}}
        effective = ("gray" if self.app.styleHints().colorScheme() == Qt.ColorScheme.Dark else "light") if name == "auto" else name
        state = (name, effective, active_theme.id, repr(_theme_style))
        changed = getattr(self, "_last_state", None) != state
        _appearance = name
        _effective = effective
        from picklight.theme import STYLE
        from picklight.ui.graphics import clear_theme_caches, theme_icon
        old_icons = dict(self.icon_specs)
        if changed:
            self.icon_specs.clear()
            clear_theme_caches()
        palette = self.app.palette()
        for role, value in ((QPalette.ColorRole.Window, "#18191c"),
                            (QPalette.ColorRole.Base, "#191a1c"),
                            (QPalette.ColorRole.Button, "#242528"),
                            (QPalette.ColorRole.WindowText, "#ffffff"),
                            (QPalette.ColorRole.Text, "#ffffff"),
                            (QPalette.ColorRole.ButtonText, "#ffffff")):
            palette.setColor(role, ui_color(value))
        self._app_style = style_sheet(STYLE)
        self._last_state = state
        windows = [window for window in self.app.topLevelWidgets()
                   if hasattr(window, "_refresh_preference_effects") and not
                   (getattr(window, "loader", None) is not None and window.loader.closed)]
        if changed:
            for window in windows:
                if hasattr(window, "filmstrip"):
                    if not getattr(window, "_appearance_refresh_pending", False):
                        window._appearance_restore_scroll = window.filmstrip.verticalScrollBar().value()
                        window._appearance_restore_updates = window.updatesEnabled()
                        window.setUpdatesEnabled(False)
                    window._appearance_refresh_pending = True
        new_windows = [window for window in windows if
                       getattr(window, "_appearance_root_style", None) != self._app_style]
        # A window-scoped sheet reaches its child dialogs/popups too. Avoid
        # QApplication.setStyleSheet(), which restyles every closed widget tree.
        for window in new_windows:
            window.setPalette(palette)
            # The normal dark sheet is already inherited from QApplication.
            # Duplicating it on every root doubles selector work on first paint.
            source = "" if _effective == "dark" and not _theme_style and self.app.styleSheet() == STYLE else STYLE
            set_ui_style(window, source)
            window._appearance_root_style = self._app_style
        if not changed:
            return
        for widget in self.app.allWidgets():
            owner = widget
            while owner is not None and owner not in windows:
                owner = owner.parentWidget()
            if owner is None:
                continue
            self.style_widget(widget)
            if isinstance(widget, QAbstractButton):
                spec = old_icons.get(widget.icon().cacheKey())
                if spec:
                    widget.setIcon(theme_icon(*spec))
            widget.update()
        for window in windows:
            if hasattr(window, "title_bar"):
                window._refresh_preference_effects()
                QTimer.singleShot(0, lambda owner=window: self._finish_window_style(owner))

    def _finish_window_style(self, window):
        if not getattr(window, "_appearance_refresh_pending", False):
            return
        window._appearance_refresh_pending = False
        try:
            if not window.loader.closed:
                # QAbstractItemView resets free item positions during a style
                # change. Flush that layout before restoring our waterfall/grid.
                window._grid_resize_timer.stop()
                window.filmstrip.doItemsLayout()
                window._grid_layout_key = None
                window._folder_cards_layout_key = None
                window._resize_grid()
                window.filmstrip.verticalScrollBar().setValue(window._appearance_restore_scroll)
        finally:
            window.setUpdatesEnabled(window._appearance_restore_updates)
            window.update()


def configure_appearance(name):
    global _manager
    app = QApplication.instance()
    if _manager is None or _manager.app is not app:
        _manager = AppearanceManager(app)
    _manager.apply(name)


def register_icon(icon, key, size):
    if _manager is not None:
        _manager.icon_specs[icon.cacheKey()] = (key, size)


def set_ui_style(widget, source):
    widget._appearance_qss_source = source
    widget._appearance_qss_rendered = style_sheet(source)
    if widget.styleSheet() != widget._appearance_qss_rendered:
        widget.setStyleSheet(widget._appearance_qss_rendered)


def sidebar_counts(widget):
    return getattr(widget.window(), "preferences", None) is None or widget.window().preferences.sidebar_counts
