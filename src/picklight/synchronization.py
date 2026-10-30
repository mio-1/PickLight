"""Apply source snapshots while retaining library choices and the current view."""

from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from picklight.library import PhotoPair


class SourceSyncMixin:
    def _watch_source_folders(self):
        if hasattr(self, "source_monitor"):
            self.source_monitor.set_sources(project["folder"] for project in self.store.projects()
                                            if project.get("folder"))

    def _source_updated(self, snapshot):
        previous = self._pending_source_update
        if previous is not None:
            snapshot.changed |= previous.changed
            snapshot.renamed = previous.renamed | snapshot.renamed
            snapshot.ratings = previous.ratings | snapshot.ratings
        self._pending_source_update = snapshot
        self._apply_pending_source_update()

    def _apply_pending_source_update(self):
        if self.loader.closed or self._pending_source_update is None:
            return
        if self.batch_rating_loader.busy or self.photo_file_loader.busy:
            self._source_apply_timer.start()
            return
        focused = self.focusWidget()
        if (QApplication.activeModalWidget() or QApplication.activePopupWidget()
                or self.filmstrip.state() == self.filmstrip.State.EditingState
                or self.project_list._folder_drag_active
                or (focused in (self.folder_inspector_name, self.folder_inspector_description)
                    and focused.hasFocus())):
            self._source_apply_timer.start()
            return
        snapshot, self._pending_source_update = self._pending_source_update, None
        self._apply_source_snapshot(snapshot)

    def _apply_source_snapshot(self, snapshot):
        # Explicit renames also preserve selection before the monitor's first scan.
        hints = getattr(self, "_photo_rename_hints", {})
        applied = {old: new for old, new in hints.items()
                   if old not in snapshot.files and new in snapshot.files}
        snapshot.renamed.update(applied)
        self._photo_rename_hints = {old: new for old, new in hints.items() if old not in applied}
        key = self.store.photo_path_key
        self.save_timer.stop()
        self._save_session()
        current = self._current_pair()
        selected_paths = [path for path in (self._current_preview_path(),
                          current.jpg if current else None, current.raw if current else None) if path]
        old_ratings = {key(pair.display_path): self.ratings.get(pair.key, 0) for pair in self.pairs}
        decisions = self.store.data.get("photo_decisions", {}).copy()
        for pair in self.pairs:
            state = "reject" if pair.key in self.marked else "keep" if pair.key in self.kept else ""
            decisions.update({key(path): state for path in (pair.jpg, pair.raw) if path})
        renamed = {key(old): new for old, new in snapshot.renamed.items()}
        for old, new in renamed.items():
            if old in decisions:
                value = decisions[old]
                decisions[key(new)] = value
                decisions[old] = ""
                stored = self.store.data.setdefault("photo_decisions", {})
                stored[key(new)] = value
                stored[old] = ""

        def moved(path):
            seen = set()
            while key(path) in renamed and key(path) not in seen:
                seen.add(key(path))
                path = renamed[key(path)]
            return key(path)

        selected_paths = list(dict.fromkeys(moved(path) for path in selected_paths))
        for loader in (self.loader, self.details_loader, self.palette_loader):
            loader.invalidate(snapshot.changed)
        self._reset_color_index()
        self._aspect_cache.clear()
        expansion = self.project_list.folder_expansion_state()
        scroll = self.filmstrip.verticalScrollBar().value()
        mode = self.center_stack.currentIndex()
        photo_details = self.inspector_stack.currentWidget() is self.inspector_scroll
        preview_source = self.preview_source
        children_expanded = self.folder_children_heading.isChecked()
        project = self.store.project_by_id(self.project_id) if self.project_id else None
        for source in self.store.projects():
            folder = source.get("folder")
            if folder and str(Path(folder).resolve()) in snapshot.pairs:
                source["photo_count"] = len(snapshot.pairs[str(Path(folder).resolve())])

        pairs = None
        if self.session_key == "collection":
            pairs, origins, seen = [], {}, set()
            sources = sorted((p for p in self.store.projects() if p.get("folder")),
                             key=lambda p: len(Path(p["folder"]).parts))
            for source in sources:
                root = str(Path(source["folder"]).resolve())
                # An inaccessible source retains its current collection rows.
                values = snapshot.pairs.get(root)
                if values is None:
                    values = [PhotoPair(origin[2], pair.jpg, pair.raw, pair.conflict)
                              for pair in self.pairs
                              if (origin := self._collection_origins.get(pair.key)) and origin[0]["id"] == source["id"]]
                for pair in values:
                    paths = {key(path) for path in (pair.jpg, pair.raw) if path}
                    if paths & seen:
                        continue
                    seen |= paths
                    identity = "collection:" + key(pair.display_path)
                    pairs.append(PhotoPair(identity, pair.jpg, pair.raw, pair.conflict))
                    origins[identity] = (source, self.store.session_key(Path(root)), pair.key)
            self._collection_origins = origins
        elif self.project_folder is not None:
            pairs = snapshot.pairs.get(str(self.project_folder.resolve()))

        if pairs is not None:
            self.pairs = pairs
            self.pairs_by_key = {pair.key: pair for pair in pairs}
            self.ratings, self.marked, self.kept = {}, set(), set()
            for pair in pairs:
                rating, failed = snapshot.ratings.get(str(pair.display_path), (old_ratings.get(key(pair.display_path), 0), False))
                self.ratings[pair.key] = old_ratings.get(key(pair.display_path), rating) if failed else rating
                state = next((decisions[key(path)] for path in (pair.display_path, pair.jpg, pair.raw)
                              if path is not None and key(path) in decisions), "")
                if state == "reject":
                    self.marked.add(pair.key)
                elif state == "keep":
                    self.kept.add(pair.key)
            preferred = next((pair.key for selected in selected_paths for pair in pairs
                              if any(key(path) == selected for path in (pair.jpg, pair.raw) if path)), None)
            self._apply_filter(preferred=preferred)
            if preview_source == "raw" and self._current_pair() and self._current_pair().raw:
                self._set_preview_source("raw")
            if mode == 1 and self.visible:
                self.center_stack.setCurrentIndex(1)
        if project and mode != 1:
            self._show_folder_overview(project, source_pairs=snapshot.pairs)
            self.folder_children_heading.setChecked(children_expanded)
        if photo_details and self._current_pair() is not None:
            self.inspector_stack.setCurrentWidget(self.inspector_scroll)
        self._refresh_project_list(expansion_state=expansion)
        self._update_decision_ui()
        self._save_session()
        if self.session_key is None:
            self.store.save()
        self._on_photo_selection_changed()
        QTimer.singleShot(0, lambda: self.filmstrip.verticalScrollBar().setValue(scroll)
                          if not self.loader.closed else None)
