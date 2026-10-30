"""Apply search, color, rating and status filters and synchronize the workspace."""

from PySide6.QtCore import QItemSelectionModel, QPoint, Qt
from PySide6.QtWidgets import QListWidgetItem

from picklight.library import PhotoPair
from picklight.filters import FORMAT_LABELS


class FilterMixin:
    def _apply_filter(self, *_args, preferred: str | None = None):
        selected_paths = {item.data(Qt.ItemDataRole.UserRole + 6) for item in self.filmstrip.selectedItems()}
        collection_overview = self.inspector_stack.currentWidget() is self.collection_inspector
        self._ensure_color_index()
        self.visible = [pair for pair in self.pairs if self._matches_filter(pair)]
        sort_mode = self.sort_combo.currentData() if hasattr(self, "sort_combo") else "name_asc"
        if sort_mode == "name_desc":
            self.visible.sort(key=lambda pair: (pair.display_path.stem.casefold(), pair.key),
                              reverse=True)
        elif sort_mode in ("rating_desc", "rating_asc"):
            reverse = sort_mode == "rating_desc"
            self.visible.sort(key=lambda pair: (self.ratings.get(pair.key, 0),
                                                pair.display_path.stem.casefold()),
                              reverse=reverse)
        else:
            self.visible.sort(key=lambda pair: (pair.display_path.stem.casefold(), pair.key))
        self._grid_layout_key = None
        self._building_list = True
        self.filmstrip.clear()
        self._painted_thumbnail_rows.clear()
        self.visible_row_by_path = {}
        for row, pair in enumerate(self.visible):
            display_path = self._filtered_display_path(pair)
            item = QListWidgetItem(self._item_text(pair))
            item.setData(Qt.ItemDataRole.UserRole, pair.key)
            item.setData(Qt.ItemDataRole.UserRole + 1, self.ratings.get(pair.key, 0))
            item.setData(Qt.ItemDataRole.UserRole + 2, pair.display_path.stem)
            item.setData(Qt.ItemDataRole.UserRole + 3, self._aspect_for_pair(pair))
            item.setData(Qt.ItemDataRole.UserRole + 6, str(display_path))
            item.setData(Qt.ItemDataRole.UserRole + 7,
                         "reject" if pair.key in self.marked else "keep" if pair.key in self.kept else "")
            item.setIcon(self.placeholder_icon)
            self.filmstrip.addItem(item)
            self.visible_row_by_path[str(display_path)] = row
        self._building_list = False
        self._resize_grid()
        self._update_count()
        if self.center_stack.currentIndex() == 0:
            self._update_toolbar_folder_title()
        target = preferred or self.current_key
        index = next((i for i, p in enumerate(self.visible) if p.key == target), 0)
        if self.visible:
            if self.center_stack.currentWidget() is self.empty_page:
                self._show_grid()
            if selected_paths:
                self.filmstrip.setCurrentRow(index, QItemSelectionModel.SelectionFlag.NoUpdate)
                for row in range(self.filmstrip.count()):
                    item = self.filmstrip.item(row)
                    item.setSelected(item.data(Qt.ItemDataRole.UserRole + 6) in selected_paths)
            else:
                self.filmstrip.setCurrentRow(index)
            self._request_visible_thumbnails()
        else:
            self.current_key = None
            self._show_empty(preserve_details=bool(self.pairs and self.filters.active))
        if collection_overview and self._sidebar_selection == "collection":
            self._show_collection_overview()
        self._on_photo_selection_changed()

    def _toggle_filter_bar(self, visible: bool):
        self.filter_bar.setVisible(visible)
        self.filter_button.setToolTip("筛选")

    def _search_photos(self, value: str):
        for edit in (self.search_edit, self.compact_search_edit):
            if edit is not self.sender() and edit.text() != value:
                edit.blockSignals(True)
                edit.setText(value)
                edit.blockSignals(False)
                edit._update_filter_state(value)
        value = value.strip()
        if self.filters.path_contains == value:
            return
        self.filters.path_contains = value
        self._filter_changed()

    def _set_search_scope(self, scope: str, checked: bool):
        if checked:
            self.filters.search_scopes.add(scope)
        else:
            self.filters.search_scopes.discard(scope)
        if self.filters.path_contains:
            self._filter_changed()

    def _focus_photo_search(self):
        if self.search_edit.isVisible():
            self.search_edit.setFocus()
            self.search_edit.selectAll()
        else:
            self.search_popup.popup(self.search_toggle.mapToGlobal(
                QPoint(self.search_toggle.width() - 200, self.search_toggle.height())))

    def _filter_changed(self):
        self._apply_filter()

    def _clear_filters(self):
        self.color_filter_panel.delay.stop()
        self.color_filter_panel.set_value("")
        self.color_filter_panel.hex_edit.clear()
        self.filters.clear()
        self._filter_changed()

    def _update_decision_ui(self):
        total = len(self.pairs)
        marked = sum(pair.key in self.marked for pair in self.pairs)
        rated = sum(self.ratings.get(pair.key, 0) > 0 for pair in self.pairs)
        self.sidebar_nav["all"].set_state(
            total, self._sidebar_selection == "collection" and not self.filters.active)
        self.sidebar_nav["rated"].set_state(
            rated, self._sidebar_selection == "collection" and
            self.filters.rating_min == 1 and self.filters.rating_max is None)
        self.sidebar_nav["marked"].set_state(marked, self._sidebar_selection == "collection"
                                            and self.filters.states == {"reject"})
        dim_rejected = not (self._sidebar_selection == "collection" and self.filters.states == {"reject"})
        if self.filmstrip.dim_rejected != dim_rejected:
            self.filmstrip.dim_rejected = dim_rejected
            self.filmstrip.viewport().update()

    def _update_mark_button(self):
        marked = self.current_key in self.marked if self.current_key else False
        self.keep_flag_button.setChecked(self.current_key in self.kept if self.current_key else False)
        self.reject_flag_button.setChecked(marked)
        self.keep_flag_button.setEnabled(self.current_key is not None)
        self.reject_flag_button.setEnabled(self.current_key is not None)
        state = "reject" if marked else "keep" if self.current_key in self.kept else ""
        self.preview_canvas.set_decision_state(state)
        self.inspector_preview.set_decision_state(state)

    def _matches_filter(self, pair: PhotoPair, except_facet=None, candidate_paths=None) -> bool:
        project = (self._photo_project(pair) if self.filters.path_contains and
                   "folder.description" in self.filters.search_scopes else None)
        return self.filters.matches(pair, self.ratings.get(pair.key, 0), pair.key in self.marked,
                                    kept=pair.key in self.kept,
                                    except_facet=except_facet,
                                    palettes=self.color_palettes.get(str(pair.display_path)),
                                    folder_description=str(project.get("description") or "") if project else "",
                                    candidate_paths=candidate_paths)

    def _update_count(self):
        for edit in (self.search_edit, self.compact_search_edit):
            if edit.text() != self.filters.path_contains:
                edit.blockSignals(True)
                edit.setText(self.filters.path_contains)
                edit.blockSignals(False)
                edit._update_filter_state(edit.text())
        self._update_decision_ui()
        self.filter_button.setProperty("filtered", "true" if self.filters.active else "false")
        self.filter_button.style().unpolish(self.filter_button)
        self.filter_button.style().polish(self.filter_button)
        active_count = int(self.filters.rating_min is not None or self.filters.rating_max is not None)
        active_count += len(self.filters.rating_values)
        active_count += len(self.filters.states)
        active_count += int(self.filters.format_mode is not None)
        active_count += int(self.filters.color_rgb is not None or self.filters.color_gray)
        active_count += int(bool(self.filters.path_contains))
        self.filter_badge.setText(str(active_count))
        self.filter_badge.setVisible(active_count > 0)
        self._update_visual_facets()
        self.filter_clear_button.setVisible(self.filters.active)

    def _filter_title(self) -> str:
        parts = []
        if self.filters.color_rgb is not None:
            parts.append("颜色: #{:02X}{:02X}{:02X}".format(*self.filters.color_rgb))
        elif self.filters.color_gray:
            parts.append("灰度图片")
        if self.filters.rating_values:
            parts.append("、".join(f"{value} 星" if value else "未评分"
                                  for value in sorted(self.filters.rating_values, reverse=True)))
        elif self.filters.rating_min == 1 and self.filters.rating_max is None:
            parts.append("已评分")
        if self.filters.path_contains:
            parts.append(f"路径: {self.filters.path_contains}")
        if self.filters.states:
            parts.append("、".join(title for state, title in
                                  (("keep", "保留"), ("reject", "待删除"), ("none", "无"))
                                  if state in self.filters.states))
        if self.filters.format_mode is not None:
            parts.append("格式: " + FORMAT_LABELS[self.filters.format_mode])
        project = self.store.project_by_id(self.project_id) if self.project_id else None
        return " · ".join(parts) if parts else str(project["name"]) if project else "所有照片"
