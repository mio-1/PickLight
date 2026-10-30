"""Compose the desktop window and initialize its shared state."""

from __future__ import annotations

from pathlib import Path
from copy import deepcopy

from PySide6.QtCore import QPoint, QPointF, QSizeF, QTimer, Qt
from PySide6.QtWidgets import QApplication, QMainWindow

from picklight.details import DetailsLoader
from picklight.message_dialogs import MessageBox as QMessageBox
from picklight.color_management import valid_color_mode
from picklight.filtering import FilterMixin
from picklight.filters import PhotoFilter
from picklight.folders import FolderMixin
from picklight.gallery import GalleryMixin
from picklight.library import PhotoPair
from picklight.palette import ColorIndexLoader, PaletteLoader
from picklight.photos import PhotoSelectionMixin
from picklight.multi_selection import BatchRatingLoader, MultiSelectionMixin
from picklight.photo_menu import PhotoFileLoader, PhotoMenuMixin
from picklight.preview import PreviewLoader
from picklight.projects import ProjectSessionMixin
from picklight.session import SessionStore
from picklight.source_monitor import SourceMonitor
from picklight.synchronization import SourceSyncMixin
from picklight.ui.layout import WindowLayoutMixin
from picklight.ui_motion import ScrollVisibilityManager
from picklight.window_chrome import WindowChromeMixin
from picklight.workspace import WorkspaceMixin
from picklight.visual_filters import VisualFiltersMixin


class MainWindow(
    WindowLayoutMixin,
    WorkspaceMixin,
    FolderMixin,
    ProjectSessionMixin,
    SourceSyncMixin,
    FilterMixin,
    VisualFiltersMixin,
    GalleryMixin,
    PhotoSelectionMixin,
    MultiSelectionMixin,
    PhotoMenuMixin,
    WindowChromeMixin,
    QMainWindow,
):
    """Own the workspace state and compose its focused UI controllers."""

    def _show_about_dialog(self):
        from picklight.about_dialog import AboutDialog
        AboutDialog(self).exec()

    def _show_update_dialog(self):
        from picklight.update_dialog import UpdateDialog
        dialog = UpdateDialog(self)
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()

    def _show_preferences(self, search=None):
        from picklight.preferences_dialog import PreferencesDialog
        existing = getattr(self, "_preferences_dialog", None)
        if existing is not None:
            existing.raise_()
            existing.activateWindow()
            return
        dialog = PreferencesDialog(self)
        if isinstance(search, str):
            dialog.search.setText(search)
        self._preferences_dialog = dialog
        try:
            dialog.exec()
        finally:
            self._preferences_dialog = None
            dialog.deleteLater()

    def _apply_preferences(self, preferences, *, shortcuts=None):
        from picklight.preferences import save_preferences
        from picklight.appearance import configure_appearance
        save_preferences(self.store, preferences, shortcuts=shortcuts)
        self.preferences = preferences
        self._refresh_shortcuts()
        configure_appearance(preferences.appearance)
        self.project_header_label.setText(
            f"文件夹 ({len(self.store.projects())})" if preferences.sidebar_counts else "文件夹")
        self.project_list.viewport().update()
        for button in self.sidebar_nav.values():
            button.update()
        self._refresh_preference_effects()
        self.preview_canvas.set_gpu_enabled(preferences.gpu)

    def _refresh_preference_effects(self):
        from picklight.appearance import is_light
        from picklight.platform_effects import set_backdrop
        set_backdrop(self, self.preferences.transparency, is_light())
        self.centralWidget().update_window_shape()
        # Shared QSS already owns panel colors; a second panel sheet repolishes
        # both widget trees and blocks the startup animation unnecessarily.
        self.title_bar.update()

    def _restart_application(self, dialog):
        from PySide6.QtCore import QProcess, QProcessEnvironment
        from picklight.preferences import launch_command
        self.save_timer.stop()
        self._save_folder_name()
        self._save_folder_description()
        self._save_session()
        command = launch_command()
        process = QProcess()
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("PYINSTALLER_RESET_ENVIRONMENT", "1")
        process.setProcessEnvironment(environment)
        process.setProgram(command[0])
        process.setArguments(command[1:])
        started, _ = process.startDetached()
        if started:
            dialog.accept()
            self.close()
        else:
            dialog.status.setText("无法重启，请关闭后重新启动 PickLight")

    def _switch_theme_from_preferences(self, theme_id, reopen, search):
        try:
            replacement = self._apply_icon_theme(theme_id)
            if replacement is None:
                QMessageBox.warning(self, "无法切换主题", "所选主题已不可用")
        except OSError as error:
            replacement = None
            QMessageBox.warning(self, "无法切换主题", str(error))
        if reopen:
            (replacement or self)._show_preferences(search)

    def _apply_icon_theme(self, theme_id):
        from picklight.themes import theme_manager
        if theme_id == theme_manager().active.id:
            return self
        if theme_id not in {theme.id for theme in theme_manager().themes()}:
            return
        self._save_folder_name()
        self._save_folder_description()
        self._save_session()
        existed = "icon_theme" in self.store.data
        previous_theme = self.store.data.get("icon_theme")
        self.store.data["icon_theme"] = theme_id
        try:
            self.store.save()
        except OSError:
            if existed:
                self.store.data["icon_theme"] = previous_theme
            else:
                self.store.data.pop("icon_theme", None)
            raise
        geometry = self.geometry()
        maximized = self.isMaximized()
        fullscreen = self.isFullScreen()
        current_path = self._current_preview_path()
        preview_source = self.preview_source
        canvas = self.preview_canvas
        view_state = (canvas.rotation, canvas.zoom, QPointF(canvas.pan), canvas.fitted, QSizeF(canvas.source_size))
        sidebar = self._sidebar_selection
        photo_details = self.inspector_stack.currentWidget() is self.inspector_scroll
        loupe = self.center_stack.currentIndex() == 1
        folder_page = self.center_stack.currentWidget() is self.folder_page
        filters = deepcopy(self.filters)
        scroll = self.filmstrip.verticalScrollBar().value()
        # Rebuild widgets so stored QIcons, SVG renderers and cursor pixmaps all refresh.
        replacement = MainWindow(restore_project=False)
        if current_path is not None and self.current_image is not None:
            replacement.loader.remember(str(current_path), 2200, self.current_image)
        replacement.setGeometry(geometry)
        project = replacement.store.project_by_id(self.project_id) if self.project_id else None
        if sidebar == "collection":
            replacement._open_sidebar_view("rated" if filters.rating_min == 1 else "all")
        elif project:
            if project.get("folder") and Path(project["folder"]).is_dir():
                replacement.open_project(Path(project["folder"]), record_history=False)
            elif not project.get("folder"):
                replacement._open_unbound_folder(project, record_history=False)
        replacement.filters = filters
        for scope, row in replacement.search_scope_rows.items():
            row.blockSignals(True)
            row.setChecked(scope in filters.search_scopes)
            row.blockSignals(False)
        preferred = next((pair.key for pair in replacement.pairs
                          if current_path in (pair.jpg, pair.raw)), None)
        replacement._apply_filter(preferred=preferred)
        if folder_page and project:
            replacement._show_folder_overview(project)
        elif loupe:
            replacement._show_loupe()
        elif photo_details and replacement._current_pair() is not None:
            replacement.inspector_stack.setCurrentWidget(replacement.inspector_scroll)
        if loupe and replacement._current_pair() is not None:
            replacement._set_preview_source(preview_source)
            def restore_view():
                if replacement.loader.closed or replacement._current_preview_path() != current_path:
                    return
                target = replacement.preview_canvas
                rotation, zoom, pan, fitted, size = view_state
                target.rotation = rotation
                if size.isValid() and not size.isEmpty():
                    target.source_size = QSizeF(size)
                target.fitted = fitted
                if fitted:
                    target.fit_to_canvas()
                else:
                    target.zoom, target.pan = zoom, QPointF(pan)
                    target._changed()
            QTimer.singleShot(0, restore_view)
        replacement.filter_button.setChecked(self.filter_button.isChecked())
        if loupe:
            replacement.filter_bar.hide()
        replacement._folder_history = list(self._folder_history)
        replacement._folder_history_index = self._folder_history_index
        replacement._update_folder_navigation()
        QApplication.instance()._main_window = replacement
        if fullscreen:
            replacement.toggle_fullscreen()
        elif maximized:
            replacement.showMaximized()
        else:
            replacement.show()
        QTimer.singleShot(0, lambda: replacement.filmstrip.verticalScrollBar().setValue(scroll))
        self.close()
        return replacement

    def __init__(self, *, restore_project=True):
        super().__init__()
        self.setWindowTitle("PickLight — 照片精选")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(1360, 800)
        self.setMinimumSize(960, 620)
        self._resize_edges = Qt.Edge(0)
        self._resize_start = QPoint()
        self._resize_geometry = self.geometry()
        self.store = SessionStore()
        from picklight.preferences import Preferences
        from picklight.appearance import configure_appearance
        self.preferences = Preferences.from_data(self.store.data.get("preferences"))
        self.startup_scale = getattr(QApplication.instance(), "_picklight_startup_scale", self.preferences.scale)
        self.color_mode = valid_color_mode(self.store.data.get("color_mode", "srgb"))
        from picklight.themes import configure_theme
        from picklight.ui.graphics import clear_theme_caches, apply_theme_font
        configure_theme(self.store.path.parent / "themes", self.store.data.get("icon_theme"))
        configure_appearance(self.preferences.appearance)
        clear_theme_caches()
        apply_theme_font()
        self._sidebar_collapsed = bool(self.store.data.get("sidebar_collapsed", False))
        # Older builds saved an incidental layout width, without distinguishing
        # it from a user's drag. Start those layouts at the current default once.
        saved_sidebar_width = (self.store.data.get("sidebar_width", 230)
                               if self.store.data.get("sidebar_width_customized") is True else 230)
        self._expanded_sidebar_width = max(210, min(340, saved_sidebar_width)) if isinstance(saved_sidebar_width, int) else 230
        self._inspector_width = 265
        self.loader = PreviewLoader(self, color_mode=self.color_mode)
        from picklight.importing import ImportLoader
        self.import_loader = ImportLoader(self)
        self._pending_import = None
        self.import_loader.ready.connect(self._finish_import)
        self.import_loader.failed.connect(self._import_failed)
        self.import_loader.cancelled.connect(self._import_cancelled)
        self.batch_rating_loader = BatchRatingLoader(self)
        self.photo_file_loader = PhotoFileLoader(self)
        self.photo_file_loader.finished.connect(self._photo_files_finished)
        self.batch_rating_loader.finished.connect(self._batch_rating_finished)
        for task_loader in (self.photo_file_loader, self.batch_rating_loader):
            task_loader.failed.connect(self._photo_task_failed)
        self.loader.ready.connect(self._preview_ready)
        self.loader.failed.connect(self._preview_failed)
        self.details_loader = DetailsLoader(self)
        self.details_loader.ready.connect(self._details_ready)
        self.details_loader.failed.connect(self._details_failed)
        self.palette_loader = PaletteLoader(self)
        self.palette_loader.ready.connect(self._palette_ready)
        self.color_index_loader = ColorIndexLoader(self)
        self.color_index_loader.ready.connect(self._color_index_ready)
        self.color_palettes = {}
        self.color_index_token = ""
        self.color_index_paths = ()
        self.color_index_busy = False
        self.pairs: list[PhotoPair] = []
        self.pairs_by_key: dict[str, PhotoPair] = {}
        self.visible: list[PhotoPair] = []
        self.visible_row_by_path: dict[str, int] = {}
        self._aspect_cache: dict[str, float] = {}
        self.ratings: dict[str, int] = {}
        self.marked: set[str] = set()
        self.kept: set[str] = set()
        self.current_key: str | None = None
        self.current_image = None
        self.preview_source = "jpg"
        self.project_folder: Path | None = None
        self.project_id: str | None = None
        self._sidebar_selection = "collection"
        self._folder_history: list[str] = []
        self._folder_history_index = -1
        saved_layout = self.store.data.get("gallery_layout")
        self.gallery_layout = saved_layout if saved_layout in ("waterfall", "grid") else "waterfall"
        self.session_key: str | None = None
        self.filters = PhotoFilter()
        self._building_list = False
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(350)
        self.save_timer.timeout.connect(self._save_session)
        self.thumbnail_save_timer = QTimer(self)
        self.thumbnail_save_timer.setSingleShot(True)
        self.thumbnail_save_timer.setInterval(300)
        self.thumbnail_save_timer.timeout.connect(self.store.save)
        self.sidebar_save_timer = QTimer(self)
        self.sidebar_save_timer.setSingleShot(True)
        self.sidebar_save_timer.setInterval(300)
        self.sidebar_save_timer.timeout.connect(self.store.save)
        self._make_ui()
        self._make_actions()
        self.center_stack.currentChanged.connect(lambda: self._adapt_viewer_toolbar())
        self.center_stack.currentChanged.connect(self._on_photo_selection_changed)
        self.scroll_visibility = ScrollVisibilityManager(self)
        self._pending_source_update = None
        self._source_apply_timer = QTimer(self)
        self._source_apply_timer.setSingleShot(True)
        self._source_apply_timer.setInterval(250)
        self._source_apply_timer.timeout.connect(self._apply_pending_source_update)
        self.source_monitor = SourceMonitor(self)
        self.source_monitor.updated.connect(self._source_updated)
        QApplication.instance().installEventFilter(self)
        self._refresh_project_list()
        self._update_decision_ui()
        if not restore_project:
            self._show_empty()
            return
        active = self.store.project_by_id(self.store.data.get("active_project_id", ""))
        if active and not active.get("folder"):
            self._open_unbound_folder(active)
            self.project_list.blockSignals(True)
            self.project_list.setCurrentItem(self._project_items[active["id"]])
            self.project_list.blockSignals(False)
            return
        recent_project = self.store.recent_project()
        if recent_project and Path(recent_project).is_dir():
            QTimer.singleShot(0, lambda: self.open_project(Path(recent_project))
                              if not self.loader.closed and self.project_folder is None else None)
        else:
            self._show_empty()

    def _set_color_mode(self, mode):
        mode = valid_color_mode(mode)
        if mode == self.color_mode:
            return
        self.color_mode = mode
        self.loader.set_color_mode(mode)
        self.color_mode_actions[mode].setChecked(True)
        self.store.data["color_mode"] = mode
        self.store.save()
        for row in self._painted_thumbnail_rows:
            item = self.filmstrip.item(row)
            if item is not None:
                item.setData(Qt.ItemDataRole.UserRole + 5, None)
        self._request_visible_thumbnails()
        for path in self._active_cover_paths():
            self.loader.request(Path(path), 420)
        path = self._current_preview_path()
        if path is not None:
            # Keep the previous frame/pan/zoom until the new mode's pixels arrive.
            self.current_image = None
            self.loader.request(path, 2200)
