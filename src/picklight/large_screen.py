"""Enter and leave immersive review without duplicating photos or selection."""

from dataclasses import dataclass

from PySide6.QtCore import QSignalBlocker, QTimer, Qt
from PySide6.QtWidgets import QListView

@dataclass(frozen=True)
class LargeScreenRestore:
    view_index: int
    splitter_sizes: tuple[int, ...]


class LargeScreenMixin:
    def _large_screen_active(self):
        return hasattr(self, "large_screen_page") and self.large_screen_page.immersive

    def _enter_large_screen(self):
        if self._large_screen_active() or self._current_pair() is None:
            return
        self._large_screen_restore = LargeScreenRestore(
            self.center_stack.currentIndex(), tuple(self.splitter.sizes()))
        if self.center_stack.currentIndex() != 1:
            self._show_loupe()
        self.large_screen_page.set_immersive(True)
        self.preview_canvas.fill_canvas = True
        self.browser_panel.hide()
        self.inspector.hide()
        self.viewer.layout().setContentsMargins(0, 0, 0, 0)
        self._position_sidebar_toggle()
        self._adapt_viewer_toolbar()
        self._sync_large_screen()
        self.preview_canvas.fit_to_canvas()
        QTimer.singleShot(0, lambda: self.preview_canvas.fit_to_canvas()
                          if self._large_screen_active() and self.preview_canvas.fitted else None)
        self.preview_canvas.setFocus(Qt.FocusReason.OtherFocusReason)

    def _exit_large_screen(self, *, restore_view=True):
        if not self._large_screen_active():
            return
        self.review_feedback.dismiss()
        self.large_screen_page.set_immersive(False)
        self.preview_canvas.fill_canvas = False
        if self.preview_canvas.fitted:
            self.preview_canvas.fit_to_canvas()
        self.viewer.layout().setContentsMargins(7, 0, 7, 10)
        self.inspector.show()
        self.browser_panel.setVisible(not self._sidebar_collapsed)
        state = self._large_screen_restore
        self.splitter.setSizes(state.splitter_sizes)
        self._adapt_viewer_toolbar()
        self._position_sidebar_toggle()
        if restore_view and state.view_index == 0:
            self._show_grid()
            self.filmstrip.setFocus(Qt.FocusReason.OtherFocusReason)
        else:
            self.preview_canvas.setFocus(Qt.FocusReason.OtherFocusReason)

    def _exit_photo_view(self):
        if self._large_screen_active():
            self._exit_large_screen()
        else:
            self._show_grid()

    def _sync_large_screen(self):
        if not self._large_screen_active():
            return
        page = self.large_screen_page
        pair = self._current_pair()
        if pair is None or not self.visible:
            self._exit_large_screen(restore_view=False)
            return
        path = self._current_preview_path()
        self.large_screen_title.setText(path.name)
        self.large_screen_title.setToolTip(str(path))
        row = self.filmstrip.currentRow()
        page.counter.setText(f"{row + 1} / {len(self.visible)}")
        page.counter.setFixedWidth(max(64, page.counter.fontMetrics().horizontalAdvance(page.counter.text()) + 12))
        page.previous_button.setEnabled(row > 0)
        page.next_button.setEnabled(row < len(self.visible) - 1)
        page.stars.set_rating(self.ratings.get(pair.key, 0))
        for button, checked in ((page.keep_button, pair.key in self.kept),
                                (page.reject_button, pair.key in self.marked),
                                (page.jpg_button, self.preview_source == "jpg"),
                                (page.raw_button, self.preview_source == "raw"),
                                (page.auto_action, self.review_auto_advance_button.isChecked())):
            with QSignalBlocker(button):
                button.setChecked(checked)
        page.jpg_button.setEnabled(pair.jpg is not None)
        page.raw_button.setEnabled(pair.raw is not None)
        paired_sources = pair.jpg is not None and pair.raw is not None
        page.jpg_button.setVisible(paired_sources)
        page.raw_button.setVisible(paired_sources)
        page._sync_zoom_controls(self.preview_canvas.zoom)
        state = "已保留" if pair.key in self.kept else "待删除" if pair.key in self.marked else ""
        rating = self.ratings.get(pair.key, 0)
        values = (page.counter.text(), state, f"{rating} 星" if rating else "",
                  path.suffix.lstrip(".").upper(), self.dimensions_label.text(), self.size_label.text())
        page.status.setText("   ·   ".join(value for value in values if value and value != "—"))
        page.status.setToolTip("\n".join((str(path), page.status.text(), self.capture_date_label.text())))
        for button, title, command in (
            (page.previous_button, "上一张", "photo.previous"),
            (page.next_button, "下一张", "photo.next"),
            (page.keep_button, "保留", "photo.keep"),
            (page.reject_button, "待删除", "photo.reject"),
            (page.jpg_button, "查看 JPG 原图", "photo.source"),
            (page.raw_button, "查看 RAW 原图", "photo.source"),
        ):
            shortcut = self.shortcuts.get(command, "")
            button.setToolTip(f"{title}（{shortcut}）" if shortcut else title)
        page._position_controls()
        index = self.filmstrip.currentIndex()
        page.strip.scrollTo(index, QListView.ScrollHint.EnsureVisible)
        page.strip.schedule_refresh()
