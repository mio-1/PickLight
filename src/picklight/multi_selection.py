"""Shared photo multi-selection inspector and batch rating."""

from pathlib import Path

from picklight.folder_dialogs import NoticeDialog
from picklight.metadata import read_pair_rating, write_pair_rating
from picklight.file_access import path_key
from picklight.loading import TaskLoader


class BatchRatingLoader(TaskLoader):
    def __init__(self, parent):
        super().__init__(parent, name="picklight-batch-rating")

    def load(self, pairs, stars):
        def work():
            results, failures = {}, []
            for pair in pairs:
                if self.stop.is_set():
                    break
                try:
                    write_pair_rating(pair, stars)
                    actual = stars
                except Exception as error:
                    failures.append(f"{pair.display_path.name}：{error}")
                    try:
                        actual = read_pair_rating(pair)
                    except Exception:
                        continue
                for path in (pair.jpg, pair.raw):
                    if path is not None:
                        results[path_key(path)] = actual
            return results, failures

        self._submit(work)


class MultiSelectionMixin:
    def _update_rating_actions(self):
        if hasattr(self, "multi_selection_stars"):
            enabled = not self.batch_rating_loader.busy and not self.photo_file_loader.busy
            self.multi_selection_stars.setEnabled(enabled)
            self.inspector_stars.setEnabled(enabled)

    def _selected_photo_pairs(self):
        selected = self.filmstrip.selectedItems()
        if len(selected) == len(self.visible):
            return list(self.visible)
        rows = sorted(self.filmstrip.row(item) for item in selected)
        return [self.visible[row] for row in rows if 0 <= row < len(self.visible)]

    def _on_photo_selection_changed(self, *_args, show_single=False):
        if self._building_list or not hasattr(self, "multi_inspector"):
            return
        self._update_rating_actions()
        pairs = self._selected_photo_pairs()
        self.multi_preview.set_paths([str(self._filtered_display_path(pair)) for pair in pairs],
                                     incoming=self.filmstrip.stack_addition)
        if len(pairs) > 1 and self.center_stack.currentIndex() == 0:
            files = {path_key(path): path for pair in pairs for path in (pair.jpg, pair.raw) if path}
            self.multi_selection_count.setText(
                f'已选 <span style="color: #3297ff">{len(pairs)}</span> 组图片，'
                f'<span style="color: #3297ff">{len(files)}</span> 个文件')
            size = 0
            for path in files.values():
                try:
                    stamp = self.source_monitor.files.get(str(path))
                    size += stamp[2] if stamp is not None else path.stat().st_size
                except OSError:
                    pass
            self.multi_selection_size.setText(self._folder_size_text(size))
            ratings = {self.ratings.get(pair.key, 0) for pair in pairs}
            self.multi_selection_stars.set_rating(next(iter(ratings)) if len(ratings) == 1 else 0)
            self.multi_selection_stars.setToolTip(
                "所选照片评分不同，点击可统一评分" if len(ratings) > 1 else "为所选照片统一评分")
            self.multi_selection_stars.setEnabled(not self.batch_rating_loader.busy and not self.photo_file_loader.busy)
            for path in self.multi_preview.paths:
                cached = self.loader.cached(Path(path), 420)
                if cached is not None:
                    self.multi_preview.set_image(path, cached)
                else:
                    self.loader.request(Path(path), 420)
            self.inspector_stack.setCurrentWidget(self.multi_inspector)
        elif (show_single or self.inspector_stack.currentWidget() is self.multi_inspector):
            if self._current_pair() is not None:
                self.inspector_stack.setCurrentWidget(self.inspector_scroll)
            elif self._sidebar_selection == "collection":
                self._show_collection_overview()

    def _set_selected_rating(self, stars):
        if self.batch_rating_loader.busy or self.photo_file_loader.busy:
            return
        pairs = self._selected_photo_pairs()
        if not pairs:
            return
        self.batch_rating_loader.load(pairs, stars)
        self.multi_selection_stars.setEnabled(False)
        self._update_rating_actions()

    def _batch_rating_finished(self, result):
        values, failures = result
        for pair in self.pairs:
            value = next((values[path_key(path)] for path in (pair.jpg, pair.raw)
                          if path is not None and path_key(path) in values), None)
            if value is not None:
                self.ratings[pair.key] = value
        self._update_rating_display()
        self._apply_filter(preferred=self.current_key)
        self.source_monitor.refresh(values)
        if failures:
            NoticeDialog("部分评分未能写入", "\n".join(failures[:6]), self).exec()
