"""Lay out thumbnail grids and preserve selection when ratings change."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from PySide6.QtCore import QPoint, QSize, QTimer, Qt
from PySide6.QtWidgets import QListWidget

from picklight.library import PhotoPair
from picklight.ui.common import DEFAULT_THUMBNAIL_WIDTH
from picklight.ui.graphics import oriented_jpeg_size, thumbnail_icon


class GalleryMixin:
    def _remember_thumbnail_width(self, width: int):
        self.store.data["thumbnail_width"] = width
        self.thumbnail_save_timer.start()

    def _set_gallery_layout(self, layout: str):
        if layout not in ("waterfall", "grid"):
            return
        self.gallery_layout = layout
        self.arrangement_actions[layout].setChecked(True)
        for key, row in self.arrangement_rows.items():
            row.setChecked(key == layout)
        self.grid_button.setToolTip("布局方式")
        self.store.data["gallery_layout"] = layout
        self.store.save()
        if self.center_stack.currentWidget() is self.empty_page:
            return
        if self.center_stack.currentIndex() != 0:
            self._show_grid()
        self._resize_grid()
        selected = self.filmstrip.currentItem()
        if selected is not None:
            QTimer.singleShot(0, lambda: self.filmstrip.scrollToItem(
                selected, QListWidget.ScrollHint.EnsureVisible))

    def _aspect_for_pair(self, pair: PhotoPair) -> float:
        path = self._filtered_display_path(pair)
        key = str(path)
        if key not in self._aspect_cache:
            size = oriented_jpeg_size(path) if path.suffix.casefold() in (".jpg", ".jpeg") else QSize()
            self._aspect_cache[key] = (size.height() / size.width()
                                       if size.isValid() and size.width() else 2 / 3)
        return self._aspect_cache[key]

    def _thumbnail_size_for_row(self, row: int) -> QSize:
        if 0 <= row < self.filmstrip.count():
            size = self.filmstrip.item(row).data(Qt.ItemDataRole.UserRole + 4)
            if isinstance(size, QSize):
                return size
        return self.thumbnail_size

    def _schedule_grid_resize(self):
        if not self._grid_resize_timer.isActive():
            self._grid_resize_timer.start()

    def _resize_grid(self, slider_value: int | None = None):
        self._layout_folder_cards()
        viewport_width = self.filmstrip.viewport().width()
        if viewport_width < 200:
            return
        target_width = self.zoom_slider.value() if hasattr(self, "zoom_slider") else DEFAULT_THUMBNAIL_WIDTH
        gap = 11
        columns = max(1, min(7, (viewport_width - gap) // (target_width + gap)))
        self.gallery_header.setFixedWidth(viewport_width)
        self.gallery_header.layout().activate()
        header_height = (0 if self.folder_section.isHidden()
                         else self.gallery_header.layout().sizeHint().height())
        self.gallery_header.setFixedHeight(header_height)
        self.gallery_header.setVisible(header_height > 0)
        self.filmstrip._position_header()
        layout_key = (viewport_width, columns, self.gallery_layout, header_height, len(self.visible))
        if layout_key == getattr(self, "_grid_layout_key", None):
            self.filmstrip.set_content_height(self._grid_content_height)
            self._schedule_visible_thumbnails()
            return
        self._grid_layout_key = layout_key
        cell_width = max(100, (viewport_width - gap * (columns + 1)) // columns)
        image_width = cell_width - 6
        caption_space = 48
        self.thumbnail_size = QSize(image_width, round(image_width * 2 / 3))
        heights = [header_height] * columns
        grid_image_height = self.thumbnail_size.height()
        row_extents = []
        for row, pair in enumerate(self.visible):
            item = self.filmstrip.item(row)
            if item is None:
                continue
            if self.gallery_layout == "waterfall":
                aspect = float(item.data(Qt.ItemDataRole.UserRole + 3) or 2 / 3)
                image_height = round(image_width * max(0.3, min(3.0, aspect)))
                column = min(range(columns), key=lambda candidate: heights[candidate])
                top = heights[column]
                heights[column] += image_height + caption_space + gap
            else:
                image_height = grid_image_height
                column = row % columns
                top = header_height + (row // columns) * (grid_image_height + caption_space + gap)
            image_size = QSize(image_width, image_height)
            row_extents.append((top, top + image_height + caption_space))
            item.setData(Qt.ItemDataRole.UserRole + 4, image_size)
            item.setSizeHint(QSize(cell_width, image_height + caption_space))
            self.filmstrip.setPositionForIndex(
                QPoint(gap + column * (cell_width + gap), top),
                self.filmstrip.model().index(row, 0))
        content_height = (max(heights, default=header_height) - gap if self.gallery_layout == "waterfall"
                          else header_height + ((len(self.visible) + columns - 1) // columns) *
                          (grid_image_height + caption_space + gap) - gap)
        content_height = max(header_height, content_height)
        self._grid_content_height = content_height
        self._grid_row_extents = row_extents
        self._grid_row_tops = [top for top, _bottom in row_extents]
        self._grid_max_row_height = max((bottom - top for top, bottom in row_extents), default=0)
        self.filmstrip.set_content_height(content_height)
        self.filmstrip.verticalScrollBar().setSingleStep(32)
        self._request_visible_thumbnails()

    def _refresh_changed_pair(self, pair: PhotoPair):
        if not self._matches_filter(pair):
            row = self.filmstrip.currentRow()
            neighbor = self.visible[min(row + 1, len(self.visible) - 1)].key if self.visible else None
            if neighbor == pair.key and row > 0:
                neighbor = self.visible[row - 1].key
            self._apply_filter(preferred=neighbor)
            return
        if (hasattr(self, "sort_combo") and
                self.sort_combo.currentData() in ("rating_desc", "rating_asc")):
            self._apply_filter(preferred=pair.key)
            return
        row = self.filmstrip.currentRow()
        if 0 <= row < self.filmstrip.count():
            item = self.filmstrip.item(row)
            item.setText(self._item_text(pair))
            stars = self.ratings.get(pair.key, 0)
            item.setData(Qt.ItemDataRole.UserRole + 1, stars)
            item.setData(Qt.ItemDataRole.UserRole + 7,
                         "reject" if pair.key in self.marked else "keep" if pair.key in self.kept else "")
        self._update_count()
        self._update_mark_button()

    def _item_text(self, pair: PhotoPair) -> str:
        return self._filtered_display_path(pair).name

    def _filtered_display_path(self, pair: PhotoPair):
        paths = self.filters.paths(pair)
        return paths[0] if paths else pair.display_path

    def _schedule_visible_thumbnails(self, _value=None):
        if not self._thumbnail_scroll_timer.isActive():
            self._thumbnail_scroll_timer.start()

    def _active_cover_paths(self):
        return () if self.folder_section.isHidden() else getattr(self, "_folder_cover_cards", {})

    def _request_visible_thumbnails(self):
        if not self.visible:
            return
        padding = max(300, self.filmstrip.viewport().height() // 2)
        top = self.filmstrip.verticalScrollBar().value() - padding
        bottom = top + self.filmstrip.viewport().height() + padding * 2
        extents = getattr(self, "_grid_row_extents", [])
        tops = getattr(self, "_grid_row_tops", [])
        first = bisect_left(tops, top - getattr(self, "_grid_max_row_height", 0))
        last = min(len(extents), len(self.visible), bisect_right(tops, bottom))
        rows = [row for row in range(first, last) if extents[row][1] >= top]
        visible_rows = set(rows)
        for row in self._painted_thumbnail_rows - visible_rows:
            item = self.filmstrip.item(row)
            if item is not None:
                item.setIcon(self.placeholder_icon)
                item.setData(Qt.ItemDataRole.UserRole + 5, None)
        self._painted_thumbnail_rows.intersection_update(visible_rows)
        self.loader.keep_thumbnails({str(self._filtered_display_path(self.visible[row])) for row in rows}
                                    | set(self._active_cover_paths()))
        for row in rows:
            pair = self.visible[row]
            path = self._filtered_display_path(pair)
            cached = self.loader.cached(path, 420)
            if cached is None:
                self.loader.request(path, 420)
            else:
                self._paint_thumbnail(row, cached)

    def _paint_thumbnail(self, row: int, image):
        item = self.filmstrip.item(row)
        if item is None:
            return
        size = self._thumbnail_size_for_row(row)
        signature = (size.width(), size.height())
        if item.data(Qt.ItemDataRole.UserRole + 5) == signature:
            return
        item.setIcon(thumbnail_icon(image, size))
        item.setData(Qt.ItemDataRole.UserRole + 5, signature)
        self._painted_thumbnail_rows.add(row)
