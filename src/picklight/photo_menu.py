"""Photo context menu and asynchronous source-file commands."""

from pathlib import Path
import subprocess

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog

from picklight.folder_dialogs import DeleteFilesDialog, NoticeDialog
from picklight.folder_menu import FolderContextMenu
from picklight.library import JPEG_EXTENSIONS, RAW_EXTENSIONS
from picklight.photo_files import capture_files, group_files, recycle_files, rename_files
from picklight.loading import TaskLoader
from picklight.ui.graphics import theme_icon


class PhotoFileLoader(TaskLoader):
    def __init__(self, parent):
        super().__init__(parent, name="picklight-photo-files")

    def load(self, operation, files, stem=""):
        def work():
            try:
                renamed = rename_files(files, stem) if operation == "rename" else {}
                errors = recycle_files(files) if operation == "delete" else []
                return files, renamed, errors
            except Exception as error:
                return files, {}, [str(error)]

        self._submit(work)


class PhotoMenuMixin:
    def _photo_task_failed(self, message):
        self._update_rating_actions()
        self.source_monitor.refresh()
        NoticeDialog("文件操作未完成", message, self).exec()

    def _photo_context_menu(self, position):
        item = self.filmstrip.itemAt(position)
        if item is None:
            return
        if not item.isSelected():
            self.filmstrip.setCurrentRow(self.filmstrip.row(item))
        pairs = tuple(self._selected_photo_pairs())
        if not pairs:
            return
        menu = self._build_photo_menu(pairs)
        try:
            menu.exec(self.filmstrip.viewport().mapToGlobal(position))
        finally:
            menu.deleteLater()

    def _build_photo_menu(self, pairs):
        menu = FolderContextMenu(self)
        menu.setObjectName("folderContextMenu")
        menu.setMinimumWidth(240)

        def add(title, key, command):
            action = menu.addAction(theme_icon("photo.menu." + key, 16), title)
            action.setData(key)
            action.triggered.connect(command)
            return action

        add("在文件管理器打开", "explorer", lambda: self._open_photo_explorer(pairs))
        location = add("打开文件所在位置", "location", lambda: None)
        paths = group_files(pairs)
        submenu = FolderContextMenu(menu)
        submenu.setObjectName("folderContextMenu")
        locations = self._photo_locations(pairs) if len(pairs) == 1 else []
        for project in locations:
            action = submenu.addAction(theme_icon("photo.menu.explorer", 16), project["name"])
            action.triggered.connect(lambda checked=False, project_id=project["id"]:
                                     self._reveal_photo_project(project_id, paths))
        location.setMenu(submenu)
        location.setEnabled(bool(locations))
        menu.addSeparator()
        rename = add("重命名", "rename", lambda: self._rename_photo_group(pairs))
        rename.setEnabled(len(pairs) == 1 and not self.photo_file_loader.busy and not self.batch_rating_loader.busy)
        add("复制文件路径", "copy_path", lambda: QApplication.clipboard().setText("\n".join(map(str, paths))))
        menu.addSeparator()
        remove = add("删除文件", "delete", lambda: self._delete_photo_groups(pairs))
        remove.setEnabled(not self.photo_file_loader.busy and not self.batch_rating_loader.busy)
        return menu

    def _open_photo_explorer(self, pairs):
        # One window per source directory, selecting a representative file.
        folders = {}
        for path in group_files(pairs):
            folders.setdefault(path.parent, path)
        try:
            for path in folders.values():
                if not path.is_file():
                    raise FileNotFoundError(f"文件不存在：{path}")
                subprocess.Popen(["explorer.exe", "/select,", str(path)])
        except OSError as error:
            NoticeDialog("无法打开文件管理器", str(error), self).exec()

    def _photo_locations(self, pairs):
        paths = group_files(pairs)
        return [project for project in self.store.projects() if project.get("folder")
                and any(path.resolve().is_relative_to(Path(project["folder"]).resolve()) for path in paths)]

    def _reveal_photo_project(self, project_id, paths):
        project = self.store.project_by_id(project_id)
        if project is None or not project.get("folder"):
            return
        self._clear_filters()
        if not self.open_project(Path(project["folder"])):
            return
        self._sidebar_selection = "folder"
        targets = {self.store.photo_path_key(path) for path in paths}
        row = next((row for row, pair in enumerate(self.visible)
                    if any(self.store.photo_path_key(path) in targets for path in (pair.jpg, pair.raw) if path)), None)
        self._show_grid()
        if row is not None:
            self.filmstrip.setCurrentRow(row)
            self.filmstrip.scrollToItem(self.filmstrip.item(row))
            self.inspector_stack.setCurrentWidget(self.inspector_scroll)
        item = self._project_items.get(project_id)
        if item is not None:
            parent = item.parent()
            while parent is not None:
                parent.setExpanded(True)
                parent = parent.parent()
            self.project_list.scrollToItem(item)
        self._update_decision_ui()

    def _rename_photo_group(self, pairs):
        if len(pairs) != 1 or self.photo_file_loader.busy or self.batch_rating_loader.busy:
            return
        try:
            files = capture_files(group_files(pairs, sidecars=True))
            item = next((self.filmstrip.item(row) for row, pair in enumerate(self.visible)
                         if pair.key == pairs[0].key), None)
            if item is None:
                return
            self._pending_photo_rename = (pairs[0].key, pairs[0].display_path.stem, files)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            self.filmstrip.scrollToItem(item)
            self.filmstrip.editItem(item)
        except (OSError, ValueError) as error:
            NoticeDialog("无法重命名", str(error), self).exec()

    def _commit_photo_rename(self, key, stem):
        pending = getattr(self, "_pending_photo_rename", None)
        self._pending_photo_rename = None
        if (pending is None or pending[0] != key or pending[1] == stem
                or self.photo_file_loader.busy or self.batch_rating_loader.busy):
            return
        self.photo_file_loader.load("rename", pending[2], stem)
        self._update_rating_actions()

    def _delete_photo_groups(self, pairs):
        if self.photo_file_loader.busy or self.batch_rating_loader.busy:
            return
        try:
            paths = group_files(pairs)
            files = capture_files(group_files(pairs, sidecars=True))
            jpg = sum(path.suffix.casefold() in JPEG_EXTENSIONS for path in paths)
            raw = sum(path.suffix.casefold() in RAW_EXTENSIONS for path in paths)
            extra = len(files) - len(paths)
            dialog = DeleteFilesDialog(len(pairs), jpg, raw, extra, self)
            try:
                if dialog.exec() == QDialog.DialogCode.Accepted:
                    self.photo_file_loader.load("delete", files)
                    self._update_rating_actions()
            finally:
                dialog.deleteLater()
        except (OSError, ValueError) as error:
            NoticeDialog("无法删除文件", str(error), self).exec()

    def _photo_files_finished(self, result):
        files, renamed, errors = result
        self._photo_rename_hints = getattr(self, "_photo_rename_hints", {}) | {
            str(old): str(new) for old, new in renamed.items()}
        # Persist marks under the new file names even before the monitor's first scan.
        decisions = self.store.data.setdefault("photo_decisions", {})
        for pair in self.pairs:
            state = "reject" if pair.key in self.marked else "keep" if pair.key in self.kept else ""
            for old in (pair.jpg, pair.raw):
                if old in renamed:
                    decisions[self.store.photo_path_key(renamed[old])] = state
                    decisions[self.store.photo_path_key(old)] = ""
        try:
            self.store.save()
        except OSError as error:
            errors.append(f"无法保存文件标记：{error}")
        self.source_monitor.refresh([*map(str, files), *map(str, renamed.values())])
        self._update_rating_actions()
        if errors:
            NoticeDialog("文件操作未全部完成", "\n".join(errors[:10])
                         + (f"\n另有 {len(errors) - 10} 项失败" if len(errors) > 10 else ""), self).exec()
