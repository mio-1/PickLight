"""Switch workspace modes and route sidebar selections."""

from __future__ import annotations

from math import log

from PySide6.QtCore import QEvent, QKeyCombination, QSignalBlocker, QTimer, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QComboBox, QLineEdit,
                              QListWidget, QPlainTextEdit, QTextEdit, QWidget)

from picklight.message_dialogs import MessageBox as QMessageBox


class WorkspaceMixin:
    def _set_review_auto_advance(self, enabled):
        key = "review_auto_advance"
        existed = key in self.store.data
        previous = self.store.data.get(key)
        self.store.data[key] = bool(enabled)
        try:
            self.store.save()
        except OSError as error:
            if existed:
                self.store.data[key] = previous
            else:
                self.store.data.pop(key, None)
            with QSignalBlocker(self.review_auto_advance_button):
                self.review_auto_advance_button.setChecked(previous is True)
            QMessageBox.warning(self, "无法保存设置", str(error))

    def _route_loupe_shortcut(self, watched, event):
        if (self.center_stack.currentIndex() != 1 or not isinstance(watched, QWidget)
                or watched.window() is not self or QApplication.activeModalWidget() is not None
                or QApplication.activePopupWidget() is not None):
            return False
        focus = self.focusWidget()
        while focus is not None and focus is not self:
            if isinstance(focus, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox, QComboBox)) or focus is self.project_list:
                return False
            focus = focus.parentWidget()
        sequence = QKeySequence(QKeyCombination(event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier,
                                                Qt.Key(event.key()))).toString(QKeySequence.SequenceFormat.PortableText)
        commands = ("photo.keep", "photo.reject", "photo.clear", "photo.source", "photo.previous", "photo.next")
        command = next((key for key in commands if sequence and self.shortcuts[key] == sequence), None)
        if command is None:
            return False
        event.accept()
        if event.type() == QEvent.Type.KeyPress:
            if command in ("photo.previous", "photo.next"):
                self.move_selection(-1 if command == "photo.previous" else 1)
            elif command == "photo.source" and not event.isAutoRepeat():
                self._toggle_preview_source()
            elif not event.isAutoRepeat():
                self._set_photo_decision({"photo.keep": "keep", "photo.reject": "reject", "photo.clear": ""}[command])
        return True

    def _make_actions(self):
        from picklight.shortcuts import read_shortcuts
        self.shortcuts = read_shortcuts(self.store.data.get("shortcuts"))
        self.shortcut_actions = {}

        def add(command, callback, *, folder=False, gallery=False, repeat=True):
            parent = self.project_list if folder else self.viewer if gallery else self
            action = QAction(parent)
            action.setShortcut(QKeySequence(self.shortcuts[command]))
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut if folder or gallery
                                      else Qt.ShortcutContext.WindowShortcut)
            action.setAutoRepeat(repeat)
            action.triggered.connect(callback)
            parent.addAction(action)
            self.shortcut_actions[command] = action
            return action

        for stars in range(6):
            add(f"rating.{stars}", lambda checked=False, value=stars: self.set_rating(value), repeat=False)
        for command, delta in (("photo.previous", -1), ("photo.next", 1)):
            add(command, lambda checked=False, step=delta: self.move_selection(step))
        select_all = add("photo.select_all", self._select_all_visible_photos, gallery=True, repeat=False)
        self.viewer_toolbar.addAction(select_all)
        self.filmstrip.select_all_shortcut = self.shortcuts["photo.select_all"]
        add("view.fullscreen", self.toggle_fullscreen)
        add("photo.toggle_reject", self._delete_from_focused_view)
        add("view.toggle", self._toggle_view)
        add("view.grid", self._escape_view)
        add("search.photos", self._focus_photo_search)
        self._folder_shortcuts = []
        for command in ("new", "child", "rename", "expand_all"):
            action = add("folder." + command, lambda checked=False, value=command: self._folder_menu_command(
                value, self.project_list.currentItem().data(0, Qt.ItemDataRole.UserRole)
                if self.project_list.currentItem() is not None else None), folder=True)
            self._folder_shortcuts.append(action)

    def _refresh_shortcuts(self):
        from picklight.shortcuts import read_shortcuts
        self.shortcuts = read_shortcuts(self.store.data.get("shortcuts"))
        for command, action in self.shortcut_actions.items():
            action.setShortcut(QKeySequence(self.shortcuts[command]))
        self.filmstrip.select_all_shortcut = self.shortcuts["photo.select_all"]

    def _select_all_visible_photos(self):
        if self.center_stack.currentIndex() == 0:
            self.filmstrip.selectAll()

    def _escape_view(self):
        if self.project_list._folder_drag_active:
            self.project_list.finish_folder_drag(cancel=True)
        else:
            self._show_grid()

    def _delete_from_focused_view(self):
        if self.project_list.hasFocus() and self.project_list.currentItem() is not None:
            self._remove_project_item(self.project_list.currentItem())
        else:
            self.toggle_mark()

    def _show_grid(self):
        self.review_feedback.dismiss()
        if self._sidebar_selection != "folder":
            self.folder_section.hide()
            self.folder_content_heading.hide()
            self.filmstrip.show()
        self.browser_panel.setVisible(not self._sidebar_collapsed)
        self.sidebar_toggle.show()
        QTimer.singleShot(0, self._position_sidebar_toggle)
        if self._sidebar_collapsed:
            QTimer.singleShot(0, self._size_collapsed_splitter)
        self.center_stack.setCurrentIndex(0)
        QTimer.singleShot(0, self._resize_grid)
        self.filter_bar.setVisible(self.filter_button.isChecked())
        self.grid_button.setChecked(True)
        self._update_toolbar_folder_title()
        self._adapt_viewer_toolbar()
        if self.visible:
            QTimer.singleShot(0, self._request_visible_thumbnails)
            QTimer.singleShot(0, lambda: self.filmstrip.scrollToItem(
                self.filmstrip.currentItem(), QListWidget.ScrollHint.EnsureVisible)
                if self.filmstrip.currentItem() is not None else None)

    def _show_loupe(self):
        if not self._current_pair():
            return
        self.center_stack.setCurrentIndex(1)
        self.browser_panel.setVisible(not self._sidebar_collapsed)
        self.sidebar_toggle.show()
        self.filter_bar.hide()
        self.grid_button.setChecked(False)
        self.inspector_stack.setCurrentWidget(self.inspector_scroll)
        self._position_sidebar_toggle()
        self._adapt_viewer_toolbar()
        self._update_loupe_navigation()
        self.preview_canvas.fit_to_canvas()
        QTimer.singleShot(0, self.preview_canvas.fit_to_canvas)
        self.preview_canvas.setFocus(Qt.FocusReason.OtherFocusReason)

    def _update_loupe_navigation(self):
        row = self.filmstrip.currentRow()
        if self.center_stack.currentIndex() == 1:
            self.file_label.setText(f"{row + 1 if row >= 0 else 0} / {len(self.visible)}")
            path = self._current_preview_path()
            self.file_label.setToolTip(path.name if path else "")
        self.previous_button.setEnabled(row > 0)
        self.next_button.setEnabled(0 <= row < len(self.visible) - 1)

    def _sync_loupe_zoom(self, zoom):
        value = round(log(max(0.05, min(8.0, zoom)) / 0.05) / log(160) * 1000)
        self.image_zoom_slider.blockSignals(True)
        self.image_zoom_slider.setValue(value)
        self.image_zoom_slider.blockSignals(False)
        percent = zoom * 100
        self.image_zoom_label.setText(f"{percent:.0f}%" if percent >= 10 else f"{percent:.1f}%")
        image = self.preview_canvas.image
        path = self._current_preview_path()
        if self.center_stack.currentIndex() == 1 and image is not None and path:
            native_width = round(self.preview_canvas.source_size.width())
            required = native_width * min(1.0, zoom)
            if required > image.width() * 1.15:
                requested = min(native_width, 4400 if required <= 4400 else native_width)
                requested = max(2200, requested)
                cached = self.loader.cached(path, requested)
                # Some RAW previews cannot provide more pixels than their
                # embedded thumbnail. Re-requesting that same cached image from
                # zoomChanged would synchronously re-enter set_image forever.
                if cached is None or cached.width() > image.width():
                    self.loader.request(path, requested)

    def _set_loupe_zoom(self, value):
        self.preview_canvas.set_zoom(0.05 * 160 ** (value / 1000))

    def _open_sidebar_view(self, view: str):
        self._load_collection()
        self._sidebar_selection = "collection"
        self.project_list.blockSignals(True)
        self.project_list.setCurrentItem(None)
        self.project_list.clearSelection()
        self.project_list.blockSignals(False)
        self.filters.clear()
        if view == "rated":
            self.filters.rating_min = 1
        elif view == "marked":
            self.filters.states = {"reject"}
        if view == "marked":
            self.filter_button.setChecked(True)
            self._toggle_filter_bar(True)
        self.inspector_stack.setCurrentWidget(self.inspector_scroll)
        self._apply_filter(preferred=self.current_key)
        if self.visible:
            self._show_grid()
        else:
            self._show_empty()
        self._show_collection_overview()

    def _show_collection_overview(self):
        title = ("待删除" if self.filters.states == {"reject"} else
                 "已评分" if self.filters.rating_min == 1 else "全部")
        self.collection_inspector_name.setText(title)
        paths = {str(path): path for pair in self.visible for path in self.filters.paths(pair)}
        size = 0
        for name, path in paths.items():
            stamp = self.source_monitor.files.get(name)
            try:
                size += stamp[2] if stamp is not None else path.stat().st_size
            except OSError:
                continue
        self.collection_inspector_count.setText(str(len(paths)))
        self.collection_inspector_size.setText(self._folder_size_text(size))
        self.inspector_stack.setCurrentWidget(self.collection_inspector)

    def _toggle_view(self):
        if self.center_stack.currentIndex() == 0:
            self._show_loupe()
        else:
            self._show_grid()

    def _update_toolbar_folder_title(self):
        if self.center_stack.currentIndex() == 1:
            self._update_loupe_navigation()
            return
        project = self.store.project_by_id(self.project_id) if self.project_id else None
        title = str(project["name"]) if project else (
            "待删除" if self.filters.states == {"reject"} else
            "已评分" if self.filters.rating_min == 1 else "全部")
        if self.filters.active:
            title += f" / 搜索结果 ({len(self.visible)})"
        self.file_label.setText(title)
        self.file_label.setToolTip(self._filter_title())

    def _show_empty(self, *, preserve_details=False):
        if not self.store.projects() and self._sidebar_selection != "collection":
            self._sidebar_selection = "collection"
            self.filters.clear()
            self._update_count()
        collection = self._sidebar_selection == "collection"
        unbound = (self.store.project_by_id(self.project_id)
                   if self.project_id and not self.project_folder else None)
        if self.project_folder or self.store.projects():
            self._show_workspace()
            self.empty_title.setText("此文件夹还没有照片" if unbound else
                                     "选择左侧照片文件夹" if not self.project_folder else
                                     "此文件夹还没有照片" if not self.pairs else "当前筛选没有照片")
            self.empty_hint.setText("关联照片目录，或导入为新的子文件夹。" if unbound else
                                    "来源文件夹不可用时，请添加新的项目。" if not self.project_folder else
                                    "导入本地文件夹，作为新的子文件夹添加照片。" if not self.pairs else
                                    "可在中栏顶部切换筛选条件。")
            if self.pairs and self.filters.active:
                self.empty_title.setText("正在分析图片颜色…" if self.color_index_busy else "没有找到相关文件")
                self.empty_hint.setText("首次颜色筛选需要分析当前文件夹。" if self.color_index_busy
                                        else "也许换个搜索规则就能找到它！")
            elif collection:
                self.empty_title.setText("还没有照片")
                self.empty_hint.setText("关联或导入本地文件夹，开始整理照片。")
            self.center_stack.setCurrentWidget(self.empty_page)
        else:
            self._show_workspace()
            self.empty_title.setText("还没有照片")
            self.empty_hint.setText("添加或导入本地文件夹，开始整理照片。")
            self.center_stack.setCurrentWidget(self.empty_page)
        if not preserve_details:
            self.current_image = None
            self.preview_canvas.set_message("导入照片文件夹，开始挑选照片" if not self.pairs else "当前筛选没有照片")
            self.inspector_preview.set_message("暂无照片")
            self.palette_strip.set_colors([])
        empty_library = not self.project_folder and not self.store.projects()
        empty_folder = bool(self.project_id and not self.pairs)
        self.empty_folder_art.setVisible(empty_folder or empty_library)
        self.empty_search_art.setVisible(bool(self.pairs and self.filters.active and not self.color_index_busy))
        self.empty_actions.setVisible(empty_folder or empty_library)
        self.empty_link_button.setVisible(not empty_library)
        self.empty_link_button.setEnabled(bool(unbound))
        self.empty_link_button.setToolTip("将本地照片目录关联到当前文件夹" if unbound
                                          else "当前文件夹已关联本地目录")
        if self.project_id or self._sidebar_selection == "collection":
            self._update_toolbar_folder_title()
        else:
            self.file_label.clear()
        if collection:
            self._show_collection_overview()
        if preserve_details:
            self._update_mark_button()
            return
        self.info_name.setText("—")
        self.inspector_stars.set_rating(0)
        self._update_mark_button()
        for field in (self.camera_label, self.lens_label, self.focal_label,
                      self.aperture_label, self.shutter_label, self.iso_label,
                      self.capture_date_label, self.dimensions_label,
                      self.size_label, self.type_label,
                      self.edited_label, self.imported_label,
                      self.modified_label):
            field.setText("—")
        self.source_path_link.set_path(None)
        self.jpg_source_button.hide()
        self.raw_source_button.hide()

    def _show_workspace(self):
        self.splitter.show()
        self._show_grid()
