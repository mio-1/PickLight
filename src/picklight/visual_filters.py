"""Coordinate color indexing and the color, rating and status filter menus."""

from collections import Counter
from uuid import uuid4

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor
from picklight.filters import FORMAT_LABELS


class VisualFiltersMixin:
    def _reset_color_index(self):
        self.color_index_loader.cancel()
        self.color_palettes.clear()
        self.color_index_token = ""
        self.color_index_paths = ()
        self.color_index_busy = False

    def _ensure_color_index(self):
        if self.filters.color_rgb is None and not self.filters.color_gray:
            return
        missing = []
        for pair in self.pairs:
            key = str(pair.display_path)
            cached = self.palette_loader.cached(key)
            if key not in self.color_palettes and cached is not None:
                self.color_palettes[key] = cached
            if key not in self.color_palettes:
                missing.append(pair.display_path)
        if not missing:
            return
        paths = tuple(map(str, missing))
        if self.color_index_busy and paths == self.color_index_paths:
            return
        self.color_index_paths = paths
        self.color_index_busy = True
        self.color_index_token = uuid4().hex
        self.color_index_loader.request(self.color_index_token, missing)

    def _color_index_ready(self, token, palettes):
        if token != self.color_index_token:
            return
        self.color_palettes.update(palettes)
        self.color_index_busy = False
        self.color_index_paths = ()
        if self.filters.color_rgb is not None or self.filters.color_gray:
            self._apply_filter(preferred=self.current_key)

    def _set_color_filter(self, value):
        if self.color_index_loader.closed:
            return
        color = QColor(value) if value.startswith("#") else None
        rgb = (color.red(), color.green(), color.blue()) if color and color.isValid() else None
        gray = value == "gray"
        if (rgb, gray) == (self.filters.color_rgb, self.filters.color_gray):
            return
        self.filters.color_rgb, self.filters.color_gray = rgb, gray
        self._filter_changed()

    def _filter_from_palette(self, value):
        self.color_filter_panel.delay.stop()
        self.color_filter_panel.set_value(value)
        self.color_filter_panel.hex_edit.setText(value)
        self._set_color_filter(value)
        self.filter_button.setChecked(True)
        self._show_grid()
        self._toggle_filter_bar(True)

    def _selected_ratings(self):
        if self.filters.rating_values:
            return set(self.filters.rating_values)
        if self.filters.rating_min is not None or self.filters.rating_max is not None:
            return {value for value in range(6)
                    if (self.filters.rating_min is None or value >= self.filters.rating_min)
                    and (self.filters.rating_max is None or value <= self.filters.rating_max)}
        return set()

    def _toggle_rating_value(self, value):
        selected = self._selected_ratings()
        if value in selected:
            selected.remove(value)
        else:
            selected.add(value)
        self.filters.rating_min = None
        self.filters.rating_max = None
        self.filters.rating_values = selected
        self._filter_changed()

    def _update_visual_facets(self):
        selected = self._selected_ratings()
        counts = Counter(self.ratings.get(pair.key, 0) for pair in self.pairs
                         if self._matches_filter(pair, except_facet="rating"))
        self.rating_facet.set_counts(counts, selected)
        title = ",".join(str(value) if value else "未评分" for value in sorted(selected, reverse=True))
        if self.filters.rating_min == 1 and self.filters.rating_max is None:
            title = "已评分"
        self.quick_facet_buttons["rating"].setText(title or "评分")
        self.quick_facet_buttons["rating"].set_active(bool(selected))
        states = self.filters.states
        counts = Counter("reject" if pair.key in self.marked else "keep" if pair.key in self.kept else "none"
                         for pair in self.pairs if self._matches_filter(pair, except_facet="status"))
        self.status_facet.set_counts(counts, states)
        mode = self.filters.format_mode
        counts = Counter()
        for pair in self.pairs:
            key = "both" if pair.jpg and pair.raw else "jpg" if pair.jpg else "raw"
            if self._matches_filter(pair, except_facet="format"):
                counts[key] += 1
        self.format_facet.set_counts(counts, mode)
        button = self.quick_facet_buttons["format"]
        button.setText(FORMAT_LABELS[mode] if mode is not None else "格式")
        button.setToolTip("格式")
        button.set_active(mode is not None)
        status_title = ",".join(title for state, title in
                               (("keep", "保留"), ("reject", "待删除"), ("none", "无")) if state in states)
        self.quick_facet_buttons["status"].setText(status_title or "状态")
        self.quick_facet_buttons["status"].set_active(bool(states))
        self.color_filter_button.color = self.filters.color_rgb
        self.color_filter_button.asset = ("filter.gray" if self.filters.color_gray
                                          else "filter.color")
        self.color_filter_button.set_active(self.filters.color_rgb is not None or self.filters.color_gray)
        self.color_filter_button.update()
        self.palette_strip.set_selected_color(self.filters.color_rgb)

    def _toggle_status_value(self, value):
        if value in self.filters.states:
            self.filters.states.remove(value)
        else:
            self.filters.states.add(value)
        self._filter_changed()

    def _set_format_filter(self, mode):
        if mode not in FORMAT_LABELS or mode == self.filters.format_mode:
            return
        self.filters.format_mode = mode
        self._filter_changed()

    def _clear_visual_facet(self, facet):
        if facet == "rating":
            self.filters.rating_values.clear()
            self.filters.rating_min = self.filters.rating_max = None
        elif facet == "status":
            self.filters.states.clear()
        elif facet == "format":
            self.filters.format_mode = None
        elif facet == "color":
            self.color_filter_panel.delay.stop()
            self.color_filter_panel.set_value("")
            self.color_filter_panel.hex_edit.clear()
            self.filters.color_rgb, self.filters.color_gray = None, False
        else:
            return
        self._filter_changed()

    def _open_color_filter(self):
        value = (QColor(*self.filters.color_rgb).name().upper() if self.filters.color_rgb is not None
                 else "gray" if self.filters.color_gray else "")
        self.color_filter_panel.set_value(value)
        QTimer.singleShot(0, self.color_filter_panel.hex_edit.setFocus)
