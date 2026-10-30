"""Open photo sources and preserve browsing history and session state."""

from __future__ import annotations

from concurrent.futures import CancelledError, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, QTimer, Qt
from PySide6.QtWidgets import QFileDialog, QTreeWidgetItem

from picklight.metadata import MetadataError, read_dng_ratings
from picklight.message_dialogs import MessageBox as QMessageBox
from picklight.library import PhotoPair, scan_pairs
from picklight.ui.graphics import safe_rating
from picklight.file_access import file_stamp, path_key


@dataclass(frozen=True)
class PreparedProject:
    folder: Path
    pairs: list[PhotoPair]
    ratings: dict[str, int]
    errors: int
    files: dict = field(default_factory=dict)


def source_stamps(pairs):
    """Capture the watcher signature before loading pixels or metadata."""
    files = {}
    seen = set()
    for pair in pairs:
        for source in (pair.jpg, pair.raw):
            if source is None:
                continue
            for path in (source, source.with_suffix(".xmp")):
                key = path_key(path)
                if key in seen:
                    continue
                seen.add(key)
                try:
                    files[str(path)] = file_stamp(path)
                except OSError:
                    continue
    return files


def prepare_project(folder: Path, *, capture_files=False, progress=None, cancel=None) -> PreparedProject:
    """Read source files and ratings without touching widgets or session settings."""
    folder = folder.resolve()
    pairs = scan_pairs(folder)
    if cancel is not None and cancel.is_set():
        raise CancelledError()
    total = sum(bool(pair.jpg) + bool(pair.raw) for pair in pairs)
    if progress:
        progress(0, total, str(folder))
    files = source_stamps(pairs) if capture_files else {}
    dng_paths = [pair.raw for pair in pairs if pair.raw and pair.raw.suffix.casefold() == ".dng"]
    dng_ratings, dng_error = {}, 0
    if dng_paths:
        try:
            dng_ratings = dict(zip(dng_paths, read_dng_ratings(dng_paths)))
        except MetadataError:
            dng_error = len(dng_paths)
            dng_ratings = {path: None for path in dng_paths}
    results, completed = {}, 0
    with ThreadPoolExecutor(max_workers=8, thread_name_prefix="picklight-project-rating") as pool:
        futures = {pool.submit(safe_rating, pair, dng_ratings): pair for pair in pairs}
        for future in as_completed(futures):
            if cancel is not None and cancel.is_set():
                for pending in futures:
                    pending.cancel()
                raise CancelledError()
            pair = futures[future]
            results[pair.key] = future.result()
            completed += bool(pair.jpg) + bool(pair.raw)
            if progress:
                progress(completed, total, str(pair.display_path))
    if cancel is not None and cancel.is_set():
        raise CancelledError()
    return PreparedProject(folder, pairs, {pair.key: results[pair.key][0] for pair in pairs},
                           sum(result[1] for result in results.values()) + dng_error, files)


class ProjectSessionMixin:
    def _restore_photo_decisions(self):
        decisions = self.store.data.get("photo_decisions", {})
        for pair in self.pairs:
            paths = (pair.display_path, pair.jpg, pair.raw)
            state = next((decisions[self.store.photo_path_key(path)] for path in paths
                          if path is not None and self.store.photo_path_key(path) in decisions), None)
            if state not in ("keep", "reject", ""):
                continue
            self.marked.discard(pair.key)
            self.kept.discard(pair.key)
            if state == "reject":
                self.marked.add(pair.key)
            elif state == "keep":
                self.kept.add(pair.key)

    def _load_collection(self):
        """Load every linked source with stable keys, retaining source ownership."""
        self.save_timer.stop()
        self._save_session()
        previous_ratings = {self.store.photo_path_key(pair.display_path):
                            self.ratings.get(pair.key, 0) for pair in self.pairs}
        sources = [project for project in self.store.projects()
                   if project.get("folder") and Path(project["folder"]).is_dir()]
        # Scan ancestors first so a JPG/RAW pair is not split by overlapping sources.
        sources.sort(key=lambda project: len(Path(project["folder"]).parts))
        pairs, origins, marked, kept, seen = [], {}, set(), set(), set()
        legacy_decisions = {}
        for project in sources:
            folder = Path(project["folder"])
            try:
                source_pairs = scan_pairs(folder)
            except (OSError, ValueError):
                continue
            source_key = self.store.session_key(folder)
            source_marked = set(self.store.state_for(source_key).get("marked", []))
            source_kept = set(self.store.state_for(source_key).get("kept", []))
            for pair in source_pairs:
                paths = {self.store.photo_path_key(path) for path in (pair.jpg, pair.raw) if path}
                state = "reject" if pair.key in source_marked else "keep" if pair.key in source_kept else ""
                if state:
                    for path in paths:
                        if state == "reject" or path not in legacy_decisions:
                            legacy_decisions[path] = state
                if paths & seen:
                    continue
                seen.update(paths)
                key = "collection:" + self.store.photo_path_key(pair.display_path)
                pairs.append(PhotoPair(key, pair.jpg, pair.raw, pair.conflict))
                origins[key] = (project, source_key, pair.key)
                if pair.key in source_marked:
                    marked.add(key)
                elif pair.key in source_kept:
                    kept.add(key)
        results = [previous_ratings.get(self.store.photo_path_key(pair.display_path))
                   for pair in pairs]
        missing = [pair for pair, value in zip(pairs, results) if value is None]
        with ThreadPoolExecutor(max_workers=8) as pool:
            loaded = dict(zip((pair.key for pair in missing),
                              pool.map(lambda pair: safe_rating(pair, {}), missing)))
        self._reset_color_index()
        self.project_id = None
        self.project_folder = None
        self.session_key = "collection"
        self._collection_origins = origins
        self.pairs = pairs
        self.pairs_by_key = {pair.key: pair for pair in pairs}
        self.ratings = {pair.key: value if value is not None else loaded[pair.key][0]
                        for pair, value in zip(pairs, results)}
        self.marked = marked
        self.kept = kept
        for pair in pairs:
            state = legacy_decisions.get(self.store.photo_path_key(pair.display_path))
            if state == "reject":
                self.marked.add(pair.key)
                self.kept.discard(pair.key)
            elif state == "keep":
                self.kept.add(pair.key)
        self._restore_photo_decisions()
        self.current_key = None
        self._aspect_cache.clear()

    def _photo_project(self, pair):
        if self.session_key == "collection" and pair is not None:
            origin = self._collection_origins.get(pair.key)
            return origin[0] if origin else None
        return self.store.project_by_id(self.project_id) if self.project_id else None

    def _activate_project_from_list(self, current: QTreeWidgetItem | None,
                                    _previous: QTreeWidgetItem | None):
        if current is None or self.project_list._drag_expansion_state is not None:
            return
        project_id = current.data(0, Qt.ItemDataRole.UserRole)
        project = self.store.project_by_id(project_id)
        if project is None:
            return
        was_collection = self._sidebar_selection == "collection"
        self._sidebar_selection = "folder"
        if project_id == self.project_id:
            if was_collection:
                self.filters.clear()
                self._apply_filter(preferred=self.current_key)
            self._show_folder_overview(project)
            return
        if not project.get("folder"):
            self._open_unbound_folder(project)
            return
        folder = Path(project["folder"])
        if not folder.is_dir():
            QMessageBox.warning(self, "找不到来源文件夹", f"请确认文件夹仍在原位置：\n{folder}")
            self._refresh_project_list()
            return
        if self.open_project(folder):
            self._show_folder_overview(project)

    def _open_unbound_folder(self, project: dict, *, record_history: bool = True, source_pairs=None):
        self._reset_color_index()
        self._sidebar_selection = "folder"
        self.save_timer.stop()
        self._save_session()
        self.store.activate_project(project["id"])
        self.project_id = project["id"]
        self.project_folder = None
        self.session_key = None
        self.pairs = []
        self.pairs_by_key = {}
        self.visible = []
        self.visible_row_by_path = {}
        self.ratings = {}
        self.marked = set()
        self.kept = set()
        self.current_key = None
        self.filters.clear()
        self.filmstrip.clear()
        self._update_count()
        self._show_empty()
        self._show_folder_overview(project, source_pairs=source_pairs)
        if record_history:
            self._record_folder_visit(project["id"])

    def choose_project(self, _checked: bool = False, *, parent_id: str | None = None,
                       bind_to_id: str | None = None):
        if self.import_loader.busy:
            return
        recent = self.store.data.get("last_import_directory")
        if not isinstance(recent, str) or not recent or not Path(recent).is_dir():
            recent = self.store.recent_project()
        start = recent if recent and Path(recent).is_dir() else str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "选择项目来源文件夹", start)
        if chosen:
            try:
                folder = self._validate_import_target(Path(chosen), parent_id, bind_to_id)
            except (OSError, ValueError, RuntimeError) as error:
                QMessageBox.warning(self, "无法关联文件夹" if bind_to_id else "无法导入照片", str(error))
                return
            self._pending_import = (parent_id, bind_to_id)
            self.import_progress.begin()
            self.import_loader.load(folder)

    def _validate_import_target(self, folder, parent_id, bind_to_id):
        try:
            folder = folder.resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise ValueError("所选目录不存在或不可用，请重新选择") from error
        if not folder.is_dir():
            raise ValueError("所选目录不存在或不可用，请重新选择")
        if parent_id is not None and self.store.project_by_id(parent_id) is None:
            raise ValueError("目标文件夹已不存在，请重新选择导入位置")
        if bind_to_id is not None:
            target = self.store.project_by_id(bind_to_id)
            if target is None:
                raise ValueError("目标文件夹已不存在，请重新选择关联位置")
            if target.get("folder"):
                raise ValueError("该文件夹已经关联照片目录")
        existing = self.store.project_for_folder(folder)
        if existing is not None:
            raise ValueError(f'该目录已关联至“{existing["name"]}”，请选择其他文件夹')
        return folder

    def _finish_import(self, prepared):
        pending, self._pending_import = self._pending_import, None
        if pending is None:
            return
        parent_id, bind_to_id = pending
        try:
            self._validate_import_target(prepared.folder, parent_id, bind_to_id)
            self.source_monitor.files.update(prepared.files)
            opened = self.open_project(prepared.folder, parent_id=parent_id, bind_to_id=bind_to_id,
                                       prepared=prepared)
            if opened:
                previous = self.store.data.get("last_import_directory")
                self.store.data["last_import_directory"] = str(prepared.folder)
                try:
                    self.store.save()
                except OSError:
                    if previous is None:
                        self.store.data.pop("last_import_directory", None)
                    else:
                        self.store.data["last_import_directory"] = previous
                if not self.pairs:
                    project = self.store.project_by_id(self.project_id)
                    if project:
                        self._show_folder_overview(project)
                self._reveal_imported_folder()
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "无法关联文件夹" if bind_to_id else "无法导入照片", str(error))
        finally:
            self.import_progress.finish()

    def _import_failed(self, error):
        pending, self._pending_import = self._pending_import, None
        self.import_progress.finish()
        QMessageBox.warning(self, "无法关联文件夹" if pending and pending[1] else "无法导入照片", error)

    def _import_cancelled(self):
        self._pending_import = None
        self.import_progress.finish()

    def _reveal_imported_folder(self):
        self._set_sidebar_collapsed(False)
        if self._folder_section_collapsed:
            self._toggle_folder_section()
        self.folder_filter_edit.clear()
        project_id = self.project_id
        with QSignalBlocker(self.project_list):
            item = self._project_items.get(project_id)
            while item is not None:
                item.setExpanded(True)
                item = item.parent()
        self._save_folder_expansion(None)

        def reveal_import():
            item = self._project_items.get(project_id)
            if not self.loader.closed and self.project_id == project_id and item is not None:
                self.project_list.scrollToItem(item)

        QTimer.singleShot(0, reveal_import)

    def _history_project(self, project_id: str) -> dict | None:
        project = self.store.project_by_id(project_id)
        if not project:
            return None
        folder = project.get("folder")
        return project if not folder or Path(folder).is_dir() else None

    def _update_folder_navigation(self):
        if not hasattr(self, "folder_back_button") or self.folder_back_button is None:
            return
        self.folder_back_button.setEnabled(any(
            self._history_project(project_id) is not None
            for project_id in self._folder_history[:self._folder_history_index]))
        self.folder_forward_button.setEnabled(any(
            self._history_project(project_id) is not None
            for project_id in self._folder_history[self._folder_history_index + 1:]))

    def _record_folder_visit(self, project_id: str):
        if (self._folder_history_index >= 0 and
                self._folder_history[self._folder_history_index] == project_id):
            self._update_folder_navigation()
            return
        self._folder_history = self._folder_history[:self._folder_history_index + 1]
        self._folder_history.append(project_id)
        self._folder_history_index = len(self._folder_history) - 1
        self._update_folder_navigation()

    def _navigate_folder_history(self, direction: int):
        index = self._folder_history_index + direction
        while 0 <= index < len(self._folder_history):
            project_id = self._folder_history[index]
            project = self._history_project(project_id)
            if project is not None:
                if project.get("folder"):
                    opened = self.open_project(Path(project["folder"]), record_history=False)
                    if opened:
                        self._show_folder_overview(project)
                else:
                    self._open_unbound_folder(project, record_history=False)
                    item = self._project_items.get(project_id)
                    if item is not None:
                        self.project_list.blockSignals(True)
                        self.project_list.setCurrentItem(item)
                        self.project_list.blockSignals(False)
                    opened = True
                if opened:
                    self._folder_history_index = index
                    self._update_folder_navigation()
                return
            index += direction
        self._update_folder_navigation()

    def open_project(self, project_folder: Path, *, parent_id: str | None = None,
                     record_history: bool = True, bind_to_id: str | None = None,
                     prepared: PreparedProject | None = None, source_pairs=None) -> bool:
        project_folder = project_folder.resolve()
        try:
            prepared = prepared or prepare_project(project_folder)
            if prepared.folder != project_folder:
                raise ValueError("预载入的照片目录不匹配")
            pairs = prepared.pairs
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "无法打开项目", str(exc))
            self._refresh_project_list()
            return False
        if bind_to_id is not None:
            try:
                self.store.bind_folder(bind_to_id, project_folder)
            except ValueError as exc:
                QMessageBox.warning(self, "无法绑定照片目录", str(exc))
                return False
        self.save_timer.stop()
        self._save_session()
        self._sidebar_selection = "folder"
        project = self.store.add_project(project_folder, parent_id)
        if project["id"] != self.project_id:
            self.filters.clear()
        self.store.activate_project(project["id"])
        self.project_id = project["id"]
        project["photo_count"] = len(pairs)
        self.project_folder = project_folder
        self.store.migrate_legacy_session(project_folder)
        self.session_key = self.store.session_key(project_folder)
        state = self.store.state_for(self.session_key)
        self._reset_color_index()
        self.pairs = pairs
        self.pairs_by_key = {pair.key: pair for pair in pairs}
        self._aspect_cache.clear()
        self.folder_section.hide()
        self.folder_content_heading.hide()
        self.filmstrip.show()
        self._show_workspace()
        self.inspector_stack.setCurrentWidget(self.inspector_scroll)
        keys = {pair.key for pair in pairs}
        by_stem: dict[str, str | None] = {}
        for pair in pairs:
            stem = pair.display_path.stem.casefold()
            by_stem[stem] = pair.key if stem not in by_stem else None

        def restore_key(value: str | None) -> str | None:
            if not value:
                return None
            return value if value in keys else by_stem.get(value.casefold())

        saved_key = restore_key(state.get("last_key"))
        self.marked = {mapped for value in state.get("marked", [])
                       if (mapped := restore_key(value)) is not None}
        self.kept = {mapped for value in state.get("kept", [])
                     if (mapped := restore_key(value)) is not None} - self.marked
        self._restore_photo_decisions()
        self.ratings = dict(prepared.ratings)
        errors = prepared.errors
        self.current_key = None
        self._apply_filter(preferred=saved_key)
        self._refresh_project_list()
        if any(child.get("parent_id") == project["id"] for child in self.store.projects()):
            self._show_folder_overview(project, source_pairs=source_pairs)
        self._save_session()
        if errors:
            self.statusBar().showMessage(f"{errors} 组元数据读取失败", 7000)
        else:
            self.statusBar().clearMessage()
        if record_history:
            self._record_folder_visit(project["id"])
        return True

    def _save_session(self):
        if not self.session_key:
            return
        if self.session_key == "collection":
            # Collection keys are absolute; source sessions retain their relative keys.
            for field, selected in (("marked", self.marked), ("kept", self.kept)):
                source_states = {}
                for key, (_project, source_key, original_key) in self._collection_origins.items():
                    if source_key not in source_states:
                        source_states[source_key] = set(self.store.state_for(source_key).get(field, []))
                    if key in selected:
                        source_states[source_key].add(original_key)
                    else:
                        source_states[source_key].discard(original_key)
                for source_key, values in source_states.items():
                    self.store.state_for(source_key)[field] = sorted(values)
        state = self.store.state_for(self.session_key)
        state["marked"] = sorted(self.marked)
        state["kept"] = sorted(self.kept)
        state["last_key"] = self.current_key
        self.store.save()

    def _queue_session_save(self):
        self.save_timer.start()
