"""Load the selected photo, previews, ratings and capture details."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize, QUrl
from PySide6.QtGui import QDesktopServices
from picklight.message_dialogs import MessageBox as QMessageBox

from picklight.library import PhotoPair
from picklight.metadata import MetadataError, read_pair_rating, write_pair_rating
from picklight.ui.graphics import format_detail_date, oriented_jpeg_size


class PhotoSelectionMixin:
    def _on_row_changed(self, row: int):
        if self._building_list or row < 0 or row >= len(self.visible):
            return
        if self.inspector_stack.currentWidget() is self.collection_inspector:
            self.inspector_stack.setCurrentWidget(self.inspector_scroll)
        pair = self.visible[row]
        if pair.key != self.current_key:
            self.review_feedback.dismiss()
        if hasattr(self, "source_monitor"):
            paths = [path for path in (pair.jpg, pair.raw) if path]
            self.source_monitor.watch_current(paths + [path.with_suffix(".xmp") for path in paths])
        self.current_key = pair.key
        self.preview_source = "jpg" if self._filtered_display_path(pair) == pair.jpg else "raw"
        self.jpg_source_button.setEnabled(pair.jpg is not None)
        self.raw_source_button.setEnabled(pair.raw is not None)
        self.jpg_source_button.setVisible(pair.jpg is not None)
        self.raw_source_button.setVisible(pair.raw is not None)
        self.jpg_source_button.setChecked(self.preview_source == "jpg")
        self.raw_source_button.setChecked(self.preview_source == "raw")
        self._update_rating_display()
        self._update_mark_button()
        self._load_current_preview()
        self._update_loupe_navigation()
        self._request_visible_thumbnails()
        self._queue_session_save()
        self._on_photo_selection_changed(show_single=True)

    def _current_preview_path(self) -> Path | None:
        pair = self._current_pair()
        if not pair:
            return None
        return pair.raw if self.preview_source == "raw" and pair.raw else pair.display_path

    def _set_file_details(self, path: Path, image_size=QSize()):
        self.source_path_link.set_path(path)
        self.type_label.setText(path.suffix.lstrip(".").upper() or "—")
        self.dimensions_label.setText("—")
        if image_size.isValid():
            self.dimensions_label.setText(f"{image_size.width()} × {image_size.height()}")
        try:
            stats = path.stat()
        except OSError:
            self.size_label.setText("—")
            self.modified_label.setText("—")
        else:
            size = stats.st_size
            self.size_label.setText(f"{size / (1024 * 1024):.1f} MB" if size >= 1024 * 1024
                                    else f"{size / 1024:.0f} KB")
            self.modified_label.setText(format_detail_date(datetime.fromtimestamp(stats.st_mtime)))
        self.edited_label.setText("—")
        project = self._photo_project(self._current_pair())
        self.imported_label.setText(format_detail_date(project.get("imported_at")) if project else "—")

    def _open_current_photo_folder(self):
        path = self._current_preview_path()
        if path and path.parent.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    def _set_preview_source(self, source: str):
        pair = self._current_pair()
        if pair and ((source == "jpg" and pair.jpg) or (source == "raw" and pair.raw)):
            self.preview_source = source
            self.jpg_source_button.setChecked(source == "jpg")
            self.raw_source_button.setChecked(source == "raw")
            self._load_current_preview()

    def _toggle_preview_source(self):
        pair = self._current_pair()
        if pair is not None and pair.jpg is not None and pair.raw is not None:
            self._set_preview_source("raw" if self.preview_source == "jpg" else "jpg")

    def _load_current_preview(self):
        path = self._current_preview_path()
        if path is None:
            return
        native_size = oriented_jpeg_size(path) if path.suffix.casefold() in (".jpg", ".jpeg") else QSize()
        self.preview_canvas.begin_image(str(path), native_size)
        self.file_label.setText(path.name)
        self.info_name.setText(path.name)
        self.info_name.setToolTip(path.name)
        self._set_file_details(path, native_size)
        for field in (self.camera_label, self.lens_label, self.focal_label,
                      self.aperture_label, self.shutter_label, self.iso_label,
                      self.capture_date_label):
            field.setText("—")
        self.details_loader.request(path)
        self.current_image = None
        self.palette_strip.set_colors(self.palette_loader.cached(str(path)) or [])
        hero = self.loader.cached(path, 2200)
        cached = hero if hero is not None else self.loader.cached(path, 420)
        # request() delivers a cached hero synchronously without a blank intermediate frame.
        if hero is None:
            if cached is not None:
                self.preview_canvas.set_image(cached)
                self.inspector_preview.set_image(cached)
            else:
                self.preview_canvas.set_loading()
                self.inspector_preview.set_loading()
        self.loader.request(path, 2200)
        if self.center_stack.currentIndex() == 0:
            self._update_toolbar_folder_title()
        elif self.center_stack.currentIndex() == 1:
            self._update_loupe_navigation()

    def _update_rating_display(self):
        stars = self.ratings.get(self.current_key or "", 0)
        self.inspector_stars.set_rating(stars)

    def _preview_ready(self, path: str, width: int, image):
        self.loader.remember(path, width, image)
        if width == 420:
            self.multi_preview.set_image(path, image)
            for card in getattr(self, "_folder_cover_cards", {}).get(path, []):
                card.set_cover(image)
        current = self._current_preview_path()
        if width >= 2200:
            if current and str(current) == path:
                if self.current_image is None or image.width() >= self.current_image.width():
                    self.current_image = image
                    self.preview_canvas.set_image(image)
                    self.inspector_preview.set_image(image)
                    self.palette_loader.request(path, image, from_source=self.color_mode != "srgb")
        else:
            if current and str(current) == path and self.current_image is None:
                self.preview_canvas.set_image(image)
                self.inspector_preview.set_image(image)
            row = self.visible_row_by_path.get(path)
            if row is not None and row < self.filmstrip.count():
                viewport = self.filmstrip.viewport().rect().adjusted(0, -250, 0, 250)
                if self.filmstrip.visualItemRect(self.filmstrip.item(row)).intersects(viewport):
                    self._paint_thumbnail(row, image)

    def _preview_failed(self, path: str, width: int, error: str):
        self.loader.forget_failed(path, width)
        current = self._current_preview_path()
        if width == 2200 and current and str(current) == path:
            self.preview_canvas.set_message("无法显示预览\n" + error)
            self.inspector_preview.set_message("无法显示预览")
        self.statusBar().showMessage(error, 7000)

    def _palette_ready(self, path: str, colors):
        self.palette_loader.remember(path, colors)
        if any(str(pair.display_path) == path for pair in self.pairs):
            self.color_palettes[path] = colors
        current = self._current_preview_path()
        if current is not None and str(current) == path:
            self.palette_strip.set_colors(colors)

    def _details_ready(self, path: str, details: dict):
        self.details_loader.remember(path, details)
        pair = self._current_pair()
        if not pair:
            return
        if str(self._current_preview_path()) != path:
            return
        self.camera_label.setText(str(details.get("Model") or "—"))
        self.lens_label.setText(str(details.get("LensModel") or "—"))
        self.edited_label.setText(str(details.get("Software") or "—"))
        for field in (self.camera_label, self.lens_label, self.edited_label):
            field.setToolTip(field.text())
        focal = details.get("FocalLength")
        aperture = details.get("FNumber")
        shutter = details.get("ExposureTime")
        iso = details.get("ISO")
        self.focal_label.setText(f"{focal:g} mm" if isinstance(focal, (int, float)) else "—")
        self.aperture_label.setText(f"f/{aperture:g}" if isinstance(aperture, (int, float)) else "—")
        self.shutter_label.setText((f"1/{round(1 / shutter)}s" if shutter < 1 else f"{shutter:g}s")
                                   if isinstance(shutter, (int, float)) and shutter > 0 else "—")
        self.iso_label.setText(f"ISO {iso:g}" if isinstance(iso, (int, float)) else "—")
        width, height = details.get("ImageWidth"), details.get("ImageHeight")
        if width and height and Path(path).suffix.casefold() not in (".jpg", ".jpeg"):
            self.dimensions_label.setText(f"{width} × {height}")
            self.preview_canvas.set_source_size(QSize(int(width), int(height)))
        date = details.get("DateTimeOriginal")
        self.capture_date_label.setText(format_detail_date(date))


    def _details_failed(self, path: str, _error: str):
        self.details_loader.forget_failed(path)
        pair = self._current_pair()
        if pair and str(self._current_preview_path()) == path:
            self.camera_label.setText("拍摄信息不可用")

    def _current_pair(self) -> PhotoPair | None:
        return self.pairs_by_key.get(self.current_key or "")

    def move_selection(self, delta: int):
        row = self.filmstrip.currentRow()
        target = row + delta
        if 0 <= target < len(self.visible):
            self.filmstrip.setCurrentRow(target)
            self.filmstrip.scrollToItem(self.filmstrip.item(target))

    def set_rating(self, stars: int):
        if self.batch_rating_loader.busy or self.photo_file_loader.busy:
            return
        if self.center_stack.currentIndex() == 0 and len(self.filmstrip.selectedItems()) > 1:
            self._set_selected_rating(stars)
            return
        pair = self._current_pair()
        if not pair:
            return
        self.review_feedback.dismiss()
        try:
            write_pair_rating(pair, stars)
        except (OSError, MetadataError, ValueError) as exc:
            try:
                self.ratings[pair.key] = read_pair_rating(pair)
                self._update_rating_display()
            except (OSError, MetadataError):
                pass
            QMessageBox.warning(self, "星级写入失败", f"{pair.display_path.name}\n\n{exc}")
            return
        self.ratings[pair.key] = stars
        self._update_rating_display()
        self._refresh_changed_pair(pair)
        self._show_review_feedback(pair, "rating", stars)

    def toggle_mark(self):
        self._set_inspector_mark(True)

    def _set_inspector_mark(self, marked: bool):
        self._set_photo_decision("reject" if marked else "keep", toggle=True)

    def _set_photo_decision(self, state: str, *, toggle=False):
        pair = self._current_pair()
        if pair is None:
            return
        previous = "reject" if pair.key in self.marked else "keep" if pair.key in self.kept else ""
        if toggle and previous == state:
            state = ""
        if previous == state:
            self._show_review_feedback(pair, state or "none")
            self._advance_review_after_mark(pair, state)
            return
        self.marked.discard(pair.key)
        self.kept.discard(pair.key)
        if state == "reject":
            self.marked.add(pair.key)
        elif state == "keep":
            self.kept.add(pair.key)
        self._record_photo_decision(pair)
        self._queue_session_save()
        self._refresh_changed_pair(pair)
        self._show_review_feedback(pair, state or "none")
        self._advance_review_after_mark(pair, state)

    def _advance_review_after_mark(self, pair, state):
        if (state in ("keep", "reject") and self.center_stack.currentIndex() == 1
                and self.review_auto_advance_button.isChecked() and self.current_key == pair.key):
            # Filtering may already have selected a new photo. Only advance when
            # the marked photo is still current, so a filtered list never skips one.
            self.move_selection(1)

    def _show_review_feedback(self, pair, kind, stars=None):
        if self.center_stack.currentIndex() == 1 and self.current_key == pair.key:
            from picklight.shortcuts import display_shortcut
            command = f"rating.{stars}" if kind == "rating" else {
                "keep": "photo.keep", "reject": "photo.reject", "none": "photo.clear"}[kind]
            self.review_feedback.present(kind, stars, key_label=display_shortcut(self.shortcuts, command))

    def _record_photo_decision(self, pair):
        state = "reject" if pair.key in self.marked else "keep" if pair.key in self.kept else ""
        decisions = self.store.data.setdefault("photo_decisions", {})
        for path in (pair.jpg, pair.raw):
            if path is not None:
                decisions[self.store.photo_path_key(path)] = state
