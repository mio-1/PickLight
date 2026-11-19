"""Eagle-style catalog navigation and photo organization entry points."""

from picklight.folder_dialogs import NoticeDialog


class OrganizationMixin:
    def _build_organization_ui(self):
        self._comparison_dialog = None

    def _update_organization_selection(self):
        if self._comparison_dialog is not None:
            self._comparison_dialog.refresh_state()

    def _organization_pairs(self):
        if self.center_stack.currentIndex() != 0:
            pair = self._current_pair()
            return [pair] if pair else []
        return self._selected_photo_pairs()

    def _show_comparison(self):
        from picklight.comparison import ComparisonDialog
        pairs = self._selected_photo_pairs()
        if not 2 <= len(pairs) <= 4:
            NoticeDialog("照片对比", "请选择 2–4 组照片进行对比。", self).exec()
            return
        dialog = ComparisonDialog(pairs, self)
        self._comparison_dialog = dialog
        try:
            dialog.exec()
        finally:
            self._comparison_dialog = None
            dialog.deleteLater()

    def _rate_comparison_photo(self, pair, stars):
        if not self.batch_rating_loader.busy and not self.photo_file_loader.busy:
            self.batch_rating_loader.load([pair], stars)
            self._update_organization_selection()

    def _mark_comparison_photo(self, pair, state):
        current = "reject" if pair.key in self.marked else "keep" if pair.key in self.kept else ""
        if current == state:
            state = ""
        self.marked.discard(pair.key)
        self.kept.discard(pair.key)
        if state == "keep":
            self.kept.add(pair.key)
        elif state == "reject":
            self.marked.add(pair.key)
        self._record_photo_decision(pair)
        self._queue_session_save()
        self._apply_filter(preferred=self.current_key)
        self._update_organization_selection()
