"""Manage software folders, context menus and folder cards."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, QTimer, Qt
from PySide6.QtWidgets import (
    QDialog,
    QMenu,
    QTreeWidgetItem,
    QWidgetAction,
)

from picklight.folder_dialogs import DeleteFolderDialog, MoveFolderDialog, InputDialog as QInputDialog
from picklight.message_dialogs import MessageBox as QMessageBox
from picklight.library import scan_pairs
from picklight.folder_menu import FolderColorRow, FolderContextMenu, FolderIconPicker
from picklight.ui.folders import FolderCard, ProjectListDelegate, ProjectTree
from picklight.ui.graphics import theme_icon, folder_tree_icon, folder_triangle_icon
from picklight.ui_motion import PageTransitionOverlay


class FolderMixin:
    def _refresh_project_list(self, *, expansion_state=None):
        previous = getattr(self, "_project_items", {})
        expanded = ({project_id for project_id, value in expansion_state.items() if value}
                    if expansion_state is not None else
                    {project_id for project_id, item in previous.items()
                     if item.isExpanded() or item.childCount() == 0})
        first_render = not previous
        saved_collapsed = self.store.data.get("collapsed_folder_ids", [])
        collapsed = set(saved_collapsed) if isinstance(saved_collapsed, list) else set()
        self.project_list.blockSignals(True)
        self.project_list.clear()
        projects = self.store.projects()
        self.project_header_label.setText(f"文件夹 ({len(projects)})" if self.preferences.sidebar_counts else "文件夹")
        counts = {project["id"]: int(project.get("photo_count", 0) or 0)
                  if project.get("folder") else None for project in projects}

        items: dict[str, QTreeWidgetItem] = {}
        for project in projects:
            folder = project.get("folder")
            name = project.get("name") or (Path(folder).name if folder else "未命名文件夹")
            item = QTreeWidgetItem([str(name)])
            item.setData(0, Qt.ItemDataRole.UserRole, project["id"])
            item.setData(0, Qt.ItemDataRole.UserRole + 1, folder)
            item.setData(0, Qt.ItemDataRole.UserRole + 2, counts[project["id"]])
            item.setData(0, Qt.ItemDataRole.UserRole + 3, bool(folder) and not Path(folder).is_dir())
            item.setData(0, Qt.ItemDataRole.UserRole + 4, str(project.get("icon") or ""))
            item.setData(0, Qt.ItemDataRole.UserRole + 5, str(project.get("color") or ""))
            item.setToolTip(0, f"绑定目录：{folder}" if folder else "PickLight 文件夹 · 未绑定磁盘目录")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsDropEnabled)
            items[project["id"]] = item
        for project in projects:
            item = items[project["id"]]
            parent = items.get(project.get("parent_id"))
            if parent is not None and parent is not item:
                parent.addChild(item)
            else:
                self.project_list.addTopLevelItem(item)
        for project_id, item in items.items():
            item.setExpanded(project_id not in collapsed if first_render else
                             project_id in expanded if project_id in previous else True)
        active = items.get(self.project_id)
        if active is not None:
            if expansion_state is None:
                parent = active.parent()
                while parent is not None:
                    parent.setExpanded(True)
                    parent = parent.parent()
            if self._sidebar_selection == "folder":
                self.project_list.setCurrentItem(active)
        self._project_items = items
        self.project_list.blockSignals(False)
        if hasattr(self, "folder_filter_edit"):
            self._apply_folder_filter(self.folder_filter_edit.text())
        self.project_list.restore_folder_expansion(expansion_state)
        self._watch_source_folders()

    def _set_folder_header_hover(self, hovered: bool):
        # The add button appears when the folder section is hovered. The pill
        # gets its own hover state so hovering the plus never highlights text.
        self.project_add_button.setVisible(hovered)

    def _set_folder_header_pill_hover(self, hovered: bool):
        state = "true" if hovered else "false"
        for widget in (self.project_header_pill, self.project_header_label):
            widget.setProperty("hovered", state)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        self._update_folder_header_arrow()

    def _update_folder_header_arrow(self):
        collapsed = self._folder_section_collapsed
        hovered = self.project_header_pill.property("hovered") == "true"
        self.project_header_arrow.setPixmap(folder_triangle_icon(not collapsed).pixmap(QSize(12, 12)))
        self.project_header_arrow.setVisible(hovered or collapsed)
        self.project_header_pill.setToolTip("展开文件夹" if collapsed else "收起文件夹")

    def _toggle_folder_section(self):
        self._folder_section_collapsed = not self._folder_section_collapsed
        self.project_list.setVisible(not self._folder_section_collapsed)
        self._update_folder_header_arrow()
        self.store.data["folder_section_collapsed"] = self._folder_section_collapsed
        self.store.save()

    def _apply_folder_filter(self, text: str):
        query = text.strip().casefold()
        self.project_list.filter_query = text.strip()
        self.project_list.viewport().update()
        if query and self._folder_filter_expanded is None:
            self._folder_filter_expanded = {
                project_id: item.isExpanded()
                for project_id, item in self._project_items.items()
            }
        self.project_list.blockSignals(True)
        try:
            def show_matching(item: QTreeWidgetItem) -> bool:
                matched = query in item.text(0).casefold()
                child_visible = any([show_matching(item.child(i))
                                     for i in range(item.childCount())])
                visible = matched or child_visible
                item.setHidden(not visible)
                if query and child_visible:
                    item.setExpanded(True)
                return visible

            for index in range(self.project_list.topLevelItemCount()):
                show_matching(self.project_list.topLevelItem(index))
            if not query and self._folder_filter_expanded is not None:
                for project_id, expanded in self._folder_filter_expanded.items():
                    item = self._project_items.get(project_id)
                    if item is not None:
                        item.setExpanded(expanded)
                self._folder_filter_expanded = None
        finally:
            self.project_list.blockSignals(False)
        self.project_list.doItemsLayout()
        self.project_list.viewport().update()

    def _save_folder_expansion(self, _item: QTreeWidgetItem | None):
        if self.project_list._drag_expansion_state is not None:
            return
        snapshot = self._folder_filter_expanded
        if snapshot is not None and _item is not None:
            snapshot[_item.data(0, Qt.ItemDataRole.UserRole)] = _item.isExpanded()
        collapsed = [project_id for project_id, item in self._project_items.items()
                     if item.childCount() and not (snapshot.get(project_id, item.isExpanded())
                                                  if snapshot is not None else item.isExpanded())]
        self.store.data["collapsed_folder_ids"] = collapsed
        self.store.save()

    def _update_folder_inspector(self, project: dict, pairs=None):
        if self.folder_inspector_name.property("projectId") != project["id"]:
            self._save_folder_name()
            self._save_folder_description()
        self.inspector_stack.setCurrentWidget(self.folder_inspector)
        self.folder_inspector_name.setProperty("projectId", project["id"])
        self.folder_inspector_description.setProperty("projectId", project["id"])
        self.folder_inspector_name.setText(str(project["name"]))
        self.folder_inspector_description.setText(str(project.get("description") or ""))
        self.folder_inspector_link.set_path(project.get("folder"))
        own_pairs = pairs if pairs is not None else (self.pairs if project["id"] == self.project_id else [])
        paths = [path for pair in own_pairs for path in (pair.jpg, pair.raw) if path]
        self.folder_inspector_count.setText(str(len(paths)))
        size = sum(path.stat().st_size for path in paths if path.exists())
        self.folder_inspector_size.setText(self._folder_size_text(size))
        created = project.get("created_at") or project.get("imported_at")
        self.folder_inspector_date.setText(str(created).replace("-", "/") if created else "—")

    def _show_folder_overview(self, project: dict, *, source_pairs=None):
        own_pairs = (self.pairs if project["id"] == self.project_id and project.get("folder") else [])
        self._update_folder_inspector(project, own_pairs)
        children = [child for child in self.store.projects()
                    if child.get("parent_id") == project["id"]]
        self._folder_cover_cards = {}
        self._folder_cards = []
        self._folder_cards_layout_key = None
        self._folder_card_pairs = {}
        while self.folder_cards_layout.count():
            item = self.folder_cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.folder_children_heading.setText(f"子文件夹 ({len(children)})")
        show_children = bool(children and not own_pairs)
        self.folder_children_heading.setChecked(show_children)
        self.folder_section.setVisible(bool(children))
        self.folder_cards_container.setVisible(show_children)
        self.folder_content_heading.setText(f"内容 ({len(own_pairs)})")
        self.folder_content_heading.hide()
        self.filmstrip.setVisible(bool(children or own_pairs))
        counts_changed = project.get("photo_count") != len(own_pairs)
        if counts_changed:
            project["photo_count"] = len(own_pairs)
        for index, child in enumerate(children):
            try:
                child_pairs = ((source_pairs.get(str(Path(child["folder"]).resolve()), [])
                                if source_pairs is not None else scan_pairs(Path(child["folder"])))
                               if child.get("folder") else [])
            except (OSError, ValueError):
                child_pairs = []
            if child.get("photo_count") != len(child_pairs):
                child["photo_count"] = len(child_pairs)
                counts_changed = True
            count = len(child_pairs)
            child_count = sum(folder.get("parent_id") == child["id"]
                              for folder in self.store.projects())
            self._folder_card_pairs[child["id"]] = child_pairs
            cover = child_pairs[0].display_path if child_pairs else None
            card = FolderCard(child, count, cover, child_count)
            card.clicked.connect(self._select_folder_card)
            card.activated.connect(self._open_folder_card)
            card.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            card.customContextMenuRequested.connect(
                lambda point, target=card: self._show_folder_card_menu(target, point))
            self._folder_cards.append(card)
            if cover:
                self._folder_cover_cards.setdefault(str(cover), []).append(card)
                cached = self.loader.cached(cover, 420)
                if cached is not None:
                    card.set_cover(cached)
                else:
                    self.loader.request(cover, 420)
        self._layout_folder_cards()
        self.gallery_header.install_wheel_filters()
        if counts_changed:
            self.store.save()
        if children or counts_changed:
            self._refresh_project_list()
        if children or own_pairs:
            self._show_workspace()
            self.center_stack.setCurrentWidget(self.folder_page)
        else:
            self._show_empty()
        self._update_toolbar_folder_title()
        self._resize_grid()
        QTimer.singleShot(0, lambda: self.filmstrip.verticalScrollBar().setValue(0))

    def _toggle_folder_children(self, expanded: bool):
        # Commit the header and photo positions together. A queued grid resize
        # could otherwise paint the new header above photos at their old y.
        updates_enabled = self.filmstrip.updatesEnabled()
        self.filmstrip.setUpdatesEnabled(False)
        try:
            self.filmstrip._stop_wheel()
            self._grid_resize_timer.stop()
            self.folder_cards_container.setVisible(expanded)
            self.folder_section.layout().setContentsMargins(16, 6, 16, 0 if expanded else 14)
            self.folder_content_heading.setVisible(
                expanded and not self.folder_section.isHidden() and bool(self.filmstrip.count()))
            self.folder_section.layout().activate()
            self.gallery_header.layout().invalidate()
            self._resize_grid()
        finally:
            self.filmstrip.setUpdatesEnabled(updates_enabled)

    def _layout_folder_cards(self):
        cards = getattr(self, "_folder_cards", [])
        if not cards:
            return
        available = max(180, self.filmstrip.viewport().width() - 32)
        target = max(120, round(self.zoom_slider.value() * 0.85))
        columns = max(1, (available + 16) // (target + 16))
        width = min(available, target)
        layout_key = (columns, width, len(cards))
        if layout_key == getattr(self, "_folder_cards_layout_key", None):
            return
        self._folder_cards_layout_key = layout_key
        while self.folder_cards_layout.count():
            self.folder_cards_layout.takeAt(0)
        for index, card in enumerate(cards):
            card.set_card_width(width)
            self.folder_cards_layout.addWidget(card, index // columns, index % columns)
        rows = (len(cards) + columns - 1) // columns
        self.folder_cards_container.setFixedHeight(
            rows * cards[0].height() + max(0, rows - 1) * self.folder_cards_layout.verticalSpacing())
        self.folder_cards_layout.activate()
        self.folder_cards_container.updateGeometry()
        self.folder_section.layout().invalidate()
        self.folder_section.updateGeometry()
        self.gallery_header.layout().invalidate()

    def _select_folder_card(self, project_id: str):
        project = self.store.project_by_id(project_id)
        if project is None:
            return
        for card in self._folder_cards:
            card.set_selected(card.project_id == project_id)
        self._update_folder_inspector(project, self._folder_card_pairs.get(project_id, []))

    @staticmethod
    def _folder_size_text(size: int) -> str:
        if size < 1024:
            return f"{size:.2f} bytes"
        for unit in ("KB", "MB", "GB"):
            size /= 1024
            if size < 1024:
                return f"{size:.2f} {unit}"
        return f"{size:.2f} TB"

    def _open_folder_card(self, project_id: str):
        item = self._project_items.get(project_id)
        if item is not None:
            overlay = getattr(self.center_stack, "_page_transition", None)
            if overlay is not None:
                overlay.stop()
            previous = self.center_stack.grab()
            self.project_list.setCurrentItem(item)
            PageTransitionOverlay(self.center_stack, previous).start()

    def _save_folder_name(self):
        project_id = self.folder_inspector_name.property("projectId")
        project = self.store.project_by_id(project_id) if project_id else None
        if project is None:
            return
        name = self.folder_inspector_name.text().strip()
        if not name:
            self.folder_inspector_name.setText(project["name"])
            return
        if name != project["name"]:
            self.store.rename_project(project["id"], name)
            self._refresh_project_list()
            self._update_toolbar_folder_title()
            for card in getattr(self, "_folder_cards", []):
                if card.project_id == project["id"]:
                    card.setToolTip(name)
                    card.setAccessibleName(name)
                    card.update()

    def _save_folder_description(self):
        project_id = self.folder_inspector_description.property("projectId")
        project = self.store.project_by_id(project_id) if project_id else None
        if project is None:
            return
        description = self.folder_inspector_description.text().strip()
        if description != str(project.get("description") or ""):
            self.store.set_folder_description(project_id, description)

    def _rename_project_item(self, item: QTreeWidgetItem):
        project_id = item.data(0, Qt.ItemDataRole.UserRole)
        project = self.store.project_by_id(project_id)
        if project is None:
            return
        name, accepted = QInputDialog.getText(self, "重命名文件夹", "文件夹名称：", text=project["name"])
        if not accepted:
            return
        try:
            self.store.rename_project(project_id, name)
        except ValueError as exc:
            QMessageBox.warning(self, "无法重命名项目", str(exc))
            return
        self._refresh_project_list()
        if project_id == self.project_id and self.center_stack.currentIndex() == 0:
            self._update_toolbar_folder_title()
        if project_id == self.project_id and not self.project_folder:
            self.folder_inspector_name.setText(str(self.store.project_by_id(project_id)["name"]))

    def _project_item_renamed(self, item: QTreeWidgetItem, _column: int):
        project_id = item.data(0, Qt.ItemDataRole.UserRole)
        project = self.store.project_by_id(project_id)
        if project is None:
            return
        name = item.text(0).strip() or "未命名文件夹"
        if name != project["name"]:
            self.store.rename_project(project_id, name)
        if item.text(0) != name:
            self.project_list.blockSignals(True)
            item.setText(0, name)
            self.project_list.blockSignals(False)
        if project_id == self.project_id:
            self._update_toolbar_folder_title()
        if self.folder_inspector_name.property("projectId") == project_id:
            self.folder_inspector_name.setText(name)
        for card in getattr(self, "_folder_cards", []):
            if card.project_id == project_id:
                card.setToolTip(name)
                card.setAccessibleName(name)
                card.update()

    def _build_folder_menu(self, project_id: str | None):
        menu = FolderContextMenu(self)
        menu.setObjectName("folderContextMenu")
        menu.setMinimumWidth(272)
        project = self.store.project_by_id(project_id) if project_id else None

        def add(title, icon, command, shortcut=""):
            shortcut_key = "photo.toggle_reject" if command == "delete" else "folder." + command
            if shortcut_key in self.shortcuts:
                shortcut = self.shortcuts[shortcut_key]
            action = menu.addAction(theme_icon("menu." + icon.replace("-", "."), 16), title)
            action.setData(command)
            if shortcut:
                action.setProperty("displayShortcut", shortcut)
            action.triggered.connect(lambda checked=False: self._folder_menu_command(command, project_id))
            return action

        add("新增文件夹", "folder-new-folder", "new", "Ctrl+Shift+N")
        if project is None:
            menu.addSeparator()
            action = menu.addAction("导入本地文件夹…")
            action.triggered.connect(lambda: self.choose_project())
            return menu
        add("新增子文件夹", "folder-new-sub-folder", "child", "Alt+N")
        move = add("移动文件夹", "folder-move", "move")
        move.setEnabled(True)
        menu.addSeparator()
        add("重命名", "rename", "rename", "F2")
        menu.addSeparator()
        current = add("展开/收起文件夹", "expand", "expand")
        current.setEnabled(bool(self._project_items.get(project_id) and
                                self._project_items[project_id].childCount()))
        add("展开/收起同阶层文件夹", "expand-same", "expand_same")
        add("展开/收起所有文件夹", "expand-all", "expand_all", "/")
        menu.addSeparator()
        icons = QMenu("文件夹图标", menu)
        icons.setObjectName("folderContextMenu")
        icons.setIcon(theme_icon("menu.emoji", 16))
        picker_action = QWidgetAction(icons)
        picker = FolderIconPicker(folder_tree_icon, str(project.get("icon") or ""))
        picker_action.setDefaultWidget(picker)
        icons.addAction(picker_action)
        def select_icon(name):
            self._set_folder_appearance(project_id, icon=name)
            icons.close()
            menu.close()
        picker.iconSelected.connect(select_icon)
        menu.addMenu(icons)
        colors = FolderColorRow(str(project.get("color") or ""))
        colors_action = QWidgetAction(menu)
        colors_action.setDefaultWidget(colors)
        menu.addAction(colors_action)
        def hover_colors():
            # Cancel the icon action's delayed opening as well as its visible popup.
            menu.setActiveAction(colors_action)
            icons.hide()
        colors.hovered.connect(hover_colors)
        def select_color(value):
            self._set_folder_appearance(project_id, color=value)
            menu.close()
        colors.colorSelected.connect(select_color)
        menu.addSeparator()
        add("删除文件夹", "folder-remove", "delete", "Delete")
        return menu

    def _show_project_menu(self, point):
        item = self.project_list.itemAt(point)
        project_id = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        menu = self._build_folder_menu(project_id)
        menu.exec(self.project_list.viewport().mapToGlobal(point))
        menu.deleteLater()

    def _show_folder_card_menu(self, card, point):
        self._select_folder_card(card.project_id)
        menu = self._build_folder_menu(card.project_id)
        menu.exec(card.mapToGlobal(point))
        menu.deleteLater()

    def _folder_menu_command(self, command: str, project_id: str | None):
        project = self.store.project_by_id(project_id) if project_id else None
        if command == "new":
            self._new_folder(parent_id=project.get("parent_id") if project else None,
                             use_selection=False)
        elif project is not None:
            if command == "child":
                self._new_folder(parent_id=project_id, use_selection=False)
            elif command == "rename":
                item = self._project_items.get(project_id)
                if item is not None:
                    if self.project_list.isVisible():
                        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                        self.project_list.scrollToItem(item)
                        self.project_list.editItem(item, 0)
                    else:
                        self._rename_project_item(item)
            elif command == "move":
                self._move_folder(project_id)
            elif command == "delete":
                item = self._project_items.get(project_id)
                if item is not None:
                    self._remove_project_item(item)
            elif command in ("expand", "expand_same", "expand_all"):
                self._toggle_folder_expansion(project_id, command)

    def _toggle_folder_expansion(self, project_id: str, scope: str):
        project = self.store.project_by_id(project_id)
        if project is None:
            return
        ids = ([project_id] if scope == "expand" else
               [folder["id"] for folder in self.store.projects()
                if scope == "expand_all" or folder.get("parent_id") == project.get("parent_id")])
        targets = [self._project_items[key] for key in ids
                   if key in self._project_items and self._project_items[key].childCount()]
        if not targets:
            return
        expanded = not all(item.isExpanded() for item in targets)
        blocked = self.project_list.blockSignals(True)
        for item in targets:
            item.setExpanded(expanded)
            self.project_list._animate_branch(self.project_list.indexFromItem(item), expanded)
            if self._folder_filter_expanded is not None:
                self._folder_filter_expanded[item.data(0, Qt.ItemDataRole.UserRole)] = expanded
        self.project_list.blockSignals(blocked)
        self._save_folder_expansion(None)

    def _set_folder_appearance(self, project_id, *, icon=None, color=None):
        self.store.set_folder_appearance(project_id, icon=icon, color=color)
        project = self.store.project_by_id(project_id)
        item = self._project_items.get(project_id)
        if item is not None:
            blocked = self.project_list.blockSignals(True)
            item.setData(0, Qt.ItemDataRole.UserRole + 4, str(project.get("icon") or ""))
            item.setData(0, Qt.ItemDataRole.UserRole + 5, str(project.get("color") or ""))
            self.project_list.blockSignals(blocked)
            self.project_list.viewport().update()

    def _new_folder(self, parent_id: str | None = None, *, use_selection: bool = True):
        if parent_id is None and use_selection:
            selected = self.project_list.currentItem()
            parent = selected.parent() if selected else None
            parent_id = parent.data(0, Qt.ItemDataRole.UserRole) if parent else None
        try:
            project = self.store.add_folder("未命名文件夹", parent_id)
        except ValueError as exc:
            QMessageBox.warning(self, "无法新建文件夹", str(exc))
            return
        self._refresh_project_list()
        if parent_id and parent_id in self._project_items:
            self._project_items[parent_id].setExpanded(True)
        item = self._project_items[project["id"]]
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        self.project_list.setCurrentItem(item)
        self.project_list.scrollToItem(item)
        self.project_list.editItem(item, 0)

    def _project_tree_moved(self, tree: list[tuple[str, str | None]]):
        try:
            self.store.reorder_projects(tree)
        except ValueError:
            pass
        self._refresh_project_list(expansion_state=self.project_list._drag_expansion_state)

    def _refresh_source_counts(self):
        counts = {}
        for project in self.store.projects():
            source = project.get("folder")
            if not source or not Path(source).is_dir():
                continue
            key = self.store.photo_path_key(source)
            try:
                if key not in counts:
                    counts[key] = len(scan_pairs(Path(source)))
                project["photo_count"] = counts[key]
            except (OSError, ValueError):
                continue
        self.store.save()

    def _remove_project_item(self, item: QTreeWidgetItem):
        project_id = item.data(0, Qt.ItemDataRole.UserRole)
        project = self.store.project_by_id(project_id)
        if project is None:
            return
        branch = self.store.folder_branch(project_id)
        has_files = False
        for folder in branch:
            source = Path(folder["folder"]) if folder.get("folder") else None
            if source is not None and source.is_dir():
                try:
                    has_files = any(path.is_file() for path in source.rglob("*"))
                except OSError as exc:
                    QMessageBox.warning(self, "无法删除文件夹", str(exc))
                    return
                if has_files:
                    break
        if has_files or len(branch) > 1:
            dialog = DeleteFolderDialog(str(project["name"]), self)
            result = dialog.exec()
            dialog.deleteLater()
            if result != QDialog.DialogCode.Accepted:
                return
        removed_ids = {folder["id"] for folder in branch}
        was_active = self.project_id in removed_ids
        if was_active:
            self.save_timer.stop()
            self._save_session()
        expansion = self.project_list.folder_expansion_state()
        previous_active = self.project_id if was_active else None
        deletion = self.store.delete_folder_undoable(project_id)
        self._refresh_source_counts()
        self._update_folder_navigation()
        if was_active:
            self.project_id = None
            self.project_folder = None
            self.session_key = None
            self.pairs = []
            self.pairs_by_key = {}
            self.visible = []
            self.ratings = {}
            self.marked = set()
            self.kept = set()
            self.current_key = None
            self.filters.clear()
            self.filmstrip.clear()
            self._show_empty()
        elif self.project_folder:
            self.pairs = scan_pairs(self.project_folder)
            self.pairs_by_key = {pair.key: pair for pair in self.pairs}
            self._apply_filter(preferred=self.current_key)
        elif self.session_key == "collection":
            self._load_collection()
            self._apply_filter()
        self._refresh_project_list()
        if was_active:
            next_project = next((p for p in self.store.projects()
                                 if p.get("folder") and Path(p["folder"]).is_dir()), None)
            if next_project is not None:
                self.open_project(Path(next_project["folder"]))
                self._update_decision_ui()
                self._show_folder_delete_undo(project, deletion, expansion, previous_active)
                return
        active = self.store.project_by_id(self.project_id) if self.project_id else None
        if active and self.center_stack.currentWidget() is self.folder_page:
            self._show_folder_overview(active)
        self._update_decision_ui()

        self._show_folder_delete_undo(project, deletion, expansion, previous_active)

    def _show_folder_delete_undo(self, project, deletion, expansion, previous_active):
        self.folder_delete_toast.show_deletion(
            str(project["name"]),
            lambda: self._undo_folder_deletion(deletion, expansion, previous_active))

    def _undo_folder_deletion(self, deletion, expansion, previous_active):
        try:
            self.store.undo_folder_deletion(deletion)
        except ValueError as exc:
            QMessageBox.warning(self, "无法撤销删除", str(exc))
            return
        self._refresh_source_counts()
        restored_ids = {folder["id"] for _, folder in deletion.projects}
        current_expansion = self.project_list.folder_expansion_state()
        current_expansion.update({key: value for key, value in expansion.items() if key in restored_ids})
        self._refresh_project_list(expansion_state=current_expansion)
        target = self._project_items.get(previous_active or deletion.project_id)
        if target is not None:
            self.project_list.setCurrentItem(target)
            # Opening a linked source can rebuild the tree and invalidate target.
            target = self._project_items.get(previous_active or deletion.project_id)
            if target is not None:
                self.project_list.scrollToItem(target)
        self.project_list.restore_folder_expansion(current_expansion)
        self._update_folder_navigation()
        self._update_decision_ui()

    def _move_folder(self, project_id):
        tree = ProjectTree()
        tree.setItemDelegate(ProjectListDelegate(tree))
        dialog = MoveFolderDialog(self.store.projects(), project_id, tree, self)
        result = dialog.exec()
        parent_id = dialog.selected_parent_id
        target_id = dialog.selected_target_id
        relation = dialog.selected_relation
        dialog.deleteLater()
        if result != QDialog.DialogCode.Accepted:
            return
        try:
            self.store.move_project(project_id, parent_id,
                                    before_id=target_id if relation == "before" else None,
                                    after_id=target_id if relation == "after" else None)
        except ValueError:
            return
        self._refresh_project_list()
        target = self._project_items.get(project_id)
        if target is not None:
            ancestor = target.parent()
            while ancestor is not None:
                ancestor.setExpanded(True)
                ancestor = ancestor.parent()
            self.project_list.scrollToItem(target)
        active = self.store.project_by_id(self.project_id) if self.project_id else None
        if active and self.center_stack.currentWidget() is self.folder_page:
            self._show_folder_overview(active)
