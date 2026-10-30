"""Build the color, rating and status filter row with per-facet clearing."""

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QFrame, QHBoxLayout, QMenu, QWidget, QWidgetAction

from picklight.ui.graphics import theme_icon
from picklight.ui.toolbar import ToolbarIconButton
from picklight.ui.visual_filters import ColorFilterPanel, FormatFilterPanel, RatingFilterPanel, StatusFilterPanel, VisualFacetButton


def build_filter_bar(self, viewer_layout):
    self.filter_bar = QFrame(objectName="filterBar")
    self.filter_bar.setFixedHeight(35)
    bar_layout = QHBoxLayout(self.filter_bar)
    bar_layout.setContentsMargins(5, 0, 5, 5)
    bar_layout.setSpacing(0)
    self.filter_content = QWidget(objectName="filterContent")
    facets = QHBoxLayout(self.filter_content)
    facets.setContentsMargins(0, 0, 0, 0)
    facets.setSpacing(0)
    self.color_filter_button = VisualFacetButton("颜色", "filter.color")
    self.color_filter_button.clear_button.clicked.connect(lambda: self._clear_visual_facet("color"))
    color_menu = QMenu(self.color_filter_button)
    color_menu.setObjectName("colorFilterMenu")
    self.color_filter_panel = ColorFilterPanel()
    color_action = QWidgetAction(color_menu)
    color_action.setDefaultWidget(self.color_filter_panel)
    color_menu.addAction(color_action)
    color_menu.aboutToShow.connect(self._open_color_filter)
    color_menu.aboutToHide.connect(self.color_filter_panel.commit_pending)
    self.color_filter_panel.colorChanged.connect(self._set_color_filter)
    self.color_filter_button.setMenu(color_menu)
    facets.addWidget(self.color_filter_button)
    self.rating_facet, self.status_facet = RatingFilterPanel(), StatusFilterPanel()
    self.format_facet = FormatFilterPanel()
    self.format_facet.formatSelected.connect(self._set_format_filter)
    self.rating_facet.ratingToggled.connect(self._toggle_rating_value)
    self.status_facet.stateToggled.connect(self._toggle_status_value)
    self.rating_buttons = {stars: self.rating_facet.rows[stars] for stars in range(1, 6)}
    self.unrated_button = self.rating_facet.rows[0]
    self.quick_facet_buttons = {}
    for key, title, panel in (("rating", "评分", self.rating_facet),
                              ("status", "状态", self.status_facet),
                              ("format", "格式", self.format_facet)):
        button = VisualFacetButton(title, "filter." + key)
        button.clear_button.clicked.connect(
            lambda checked=False, facet=key: self._clear_visual_facet(facet))
        menu = QMenu(button)
        menu.setObjectName(key + "FilterMenu")
        menu.aboutToShow.connect(self._update_visual_facets)
        action = QWidgetAction(menu)
        action.setDefaultWidget(panel)
        menu.addAction(action)
        button.setMenu(menu)
        self.quick_facet_buttons[key] = button
        facets.addWidget(button)
    bar_layout.addWidget(self.filter_content)
    bar_layout.addStretch(1)
    self.filter_clear_button = ToolbarIconButton()
    self.filter_clear_button.setObjectName("filterClear")
    self.filter_clear_button.setFixedSize(24, 24)
    self.filter_clear_button.setIcon(theme_icon("filter.clear", 16))
    self.filter_clear_button.setIconSize(QSize(16, 16))
    self.filter_clear_button.setToolTip("清除筛选")
    self.filter_clear_button.setAccessibleName("清除筛选")
    self.filter_clear_button.clicked.connect(self._clear_filters)
    self.filter_clear_button.hide()
    bar_layout.addWidget(self.filter_clear_button)
    self.filter_bar.hide()
    viewer_layout.addWidget(self.filter_bar)
