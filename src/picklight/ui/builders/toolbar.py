"""Build the toolbar region."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, QTimer, Qt
from PySide6.QtGui import QAction, QActionGroup, QColor, QPalette
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QSizePolicy,
    QToolButton,
    QWidget,
    QWidgetAction,
)

from picklight.ui.common import DEFAULT_THUMBNAIL_WIDTH, ElidedLabel, TOOLBAR_ICON_SIZE, label
from picklight.ui.graphics import (
    arrangement_icon,
    theme_icon,
    filter_icon,
    navigation_icon,
    search_icon,
)
from picklight.ui.toolbar import (
    ArrangementPanel,
    GalleryZoomSlider,
    ToolbarIconButton,
    ToolbarSearchEdit,
    SearchScopePanel,
    ZoomStepButton,
)


def build_toolbar(self):
    header = QHBoxLayout(self.viewer_toolbar)
    header.setContentsMargins(14, 8, 14, 0)
    header.setSpacing(6)
    self.folder_back_button = None
    self.folder_forward_button = None
    folder_navigation = QWidget()
    self.folder_navigation = folder_navigation
    self.loupe_back_button = ToolbarIconButton()
    self.loupe_back_button.setObjectName("imageBack")
    self.loupe_back_button.setIcon(theme_icon("loupe.back"))
    self.loupe_back_button.setIconSize(QSize(24, 24))
    self.loupe_back_button.setFixedSize(26, 26)
    self.loupe_back_button.setToolTip("返回照片列表")
    self.loupe_back_button.setAccessibleName("返回照片列表")
    self.loupe_back_button.clicked.connect(self._show_grid)
    header.addWidget(self.loupe_back_button)
    self.loupe_back_button.hide()
    navigation_layout = QHBoxLayout(folder_navigation)
    navigation_layout.setContentsMargins(0, 0, 0, 0)
    navigation_layout.setSpacing(0)
    for direction, title in ((-1, "返回上一个文件夹"), (1, "前进到下一个文件夹")):
        button = ToolbarIconButton()
        button.setObjectName("folderNavigate")
        button.setIcon(navigation_icon(direction))
        button.setIconSize(QSize(24, 24))
        button.setFixedSize(26, 26)
        button.setToolTip(title)
        button.setAccessibleName(title)
        button.clicked.connect(
            lambda checked=False, step=direction: self._navigate_folder_history(step))
        if direction < 0:
            self.folder_back_button = button
        else:
            self.folder_forward_button = button
        navigation_layout.addWidget(button)
    header.addWidget(folder_navigation)
    self._update_folder_navigation()
    self.file_label = ElidedLabel("", objectName="filename")
    self.file_label.elide_mode = Qt.TextElideMode.ElideRight
    self.file_label.setMinimumWidth(40)
    self.file_label.setMaximumWidth(420)
    self.file_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
    header.addWidget(self.file_label)
    header.addStretch(1)
    self.header_leading_spacer = header.count() - 1
    self.zoom_controls = QWidget()
    zoom_layout = QHBoxLayout(self.zoom_controls)
    zoom_layout.setContentsMargins(0, 0, 0, 0)
    zoom_layout.setSpacing(0)
    self.zoom_out_button = ZoomStepButton(-1)
    self.zoom_out_button.setObjectName("zoomAdjust")
    self.zoom_out_button.setFixedSize(26, 26)
    self.zoom_out_button.setToolTip("缩小缩略图")
    self.zoom_out_button.clicked.connect(lambda: self.zoom_slider.setValue(
        self.zoom_slider.value() - self.zoom_slider.singleStep()))
    zoom_layout.addWidget(self.zoom_out_button)
    self.zoom_slider = GalleryZoomSlider(Qt.Orientation.Horizontal)
    self.zoom_slider.setObjectName("thumbnailZoom")
    self.zoom_slider.setRange(160, 460)
    self.zoom_slider.setSingleStep(20)
    self.zoom_slider.setPageStep(20)
    saved_zoom = self.store.data.get("thumbnail_width")
    self.zoom_slider.setValue(saved_zoom if type(saved_zoom) is int and 160 <= saved_zoom <= 460
                              else DEFAULT_THUMBNAIL_WIDTH)
    self.zoom_slider.setFixedWidth(96)
    self.zoom_slider.setCursor(Qt.CursorShape.PointingHandCursor)
    self.zoom_slider.setToolTip("缩略图大小")
    self.zoom_slider.valueChanged.connect(self._resize_grid)
    self.zoom_slider.valueChanged.connect(self._remember_thumbnail_width)
    zoom_layout.addWidget(self.zoom_slider)
    self.zoom_in_button = ZoomStepButton(1)
    self.zoom_in_button.setObjectName("zoomAdjust")
    self.zoom_in_button.setFixedSize(26, 26)
    self.zoom_in_button.setToolTip("放大缩略图")
    self.zoom_in_button.clicked.connect(lambda: self.zoom_slider.setValue(
        self.zoom_slider.value() + self.zoom_slider.singleStep()))
    zoom_layout.addWidget(self.zoom_in_button)
    self.zoom_slider.valueChanged.connect(lambda value: (
        self.zoom_out_button.setEnabled(value > self.zoom_slider.minimum()),
        self.zoom_in_button.setEnabled(value < self.zoom_slider.maximum())))
    header.addWidget(self.zoom_controls)
    self.loupe_zoom_controls = QWidget()
    loupe_zoom_layout = QHBoxLayout(self.loupe_zoom_controls)
    loupe_zoom_layout.setContentsMargins(0, 0, 0, 0)
    loupe_zoom_layout.setSpacing(8)
    self.image_zoom_slider = GalleryZoomSlider(Qt.Orientation.Horizontal)
    self.image_zoom_slider.setRange(0, 1000)
    self.image_zoom_slider.setSingleStep(10)
    self.image_zoom_slider.setPageStep(40)
    self.image_zoom_slider.setFixedWidth(112)
    self.image_zoom_slider.setCursor(Qt.CursorShape.PointingHandCursor)
    self.image_zoom_slider.setToolTip("图片缩放")
    loupe_zoom_layout.addWidget(self.image_zoom_slider)
    self.image_zoom_label = label("100%", "imageZoomPercent")
    self.image_zoom_label.setFixedWidth(42)
    loupe_zoom_layout.addWidget(self.image_zoom_label)
    header.addWidget(self.loupe_zoom_controls)
    self.loupe_zoom_controls.hide()
    header.addStretch(1)
    self.header_trailing_spacer = header.count() - 1
    right_tools = QWidget()
    right_tools_layout = QHBoxLayout(right_tools)
    right_tools_layout.setContentsMargins(0, 0, 0, 0)
    right_tools_layout.setSpacing(1)
    self.filter_container = QWidget()
    self.filter_container.setFixedSize(30, 28)
    self.filter_button = ToolbarIconButton(self.filter_container)
    self.filter_button.setObjectName("filterButton")
    self.filter_button.setIcon(filter_icon())
    self.filter_button.setIconSize(QSize(24, 24))
    self.filter_button.setGeometry(0, 2, 24, 24)
    self.filter_button.setCheckable(True)
    self.filter_button.setProperty("filtered", "false")
    self.filter_button.setAccessibleName("筛选照片")
    self.filter_button.setToolTip("筛选")
    self.filter_button.clicked.connect(self._toggle_filter_bar)
    self.filter_badge = QLabel("", self.filter_container)
    self.filter_badge.setObjectName("filterBadge")
    self.filter_badge.setGeometry(16, 0, 13, 13)
    self.filter_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
    self.filter_badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    self.filter_badge.hide()
    self.grid_button = ToolbarIconButton()
    self.grid_button.setObjectName("viewMode")
    self.grid_button.setIcon(arrangement_icon())
    self.grid_button.setIconSize(QSize(24, 24))
    self.grid_button.setFixedSize(24, 24)
    self.grid_button.setCheckable(True)
    self.grid_button.setAccessibleName("排列方式")
    right_tools_layout.addWidget(self.grid_button)
    self.arrangement_menu = QMenu(self.grid_button)
    self.arrangement_menu.setObjectName("toolbarArrangementMenu")
    arrangement_panel = ArrangementPanel()
    self.arrangement_rows = arrangement_panel.rows
    arrangement_group = QActionGroup(self.arrangement_menu)
    arrangement_group.setExclusive(True)
    self.arrangement_actions: dict[str, QAction] = {}
    for layout, title in (("waterfall", "瀑布流"), ("grid", "网格")):
        action = QAction(title, self.arrangement_menu)
        action.setIcon(theme_icon("layout.waterfall" if layout == "waterfall"
                                          else "layout.grid", 16))
        action.setCheckable(True)
        action.setChecked(self.gallery_layout == layout)
        action.triggered.connect(
            lambda checked=False, selected=layout: self._set_gallery_layout(selected))
        arrangement_group.addAction(action)
        self.arrangement_actions[layout] = action
        row = self.arrangement_rows[layout]
        row.setChecked(self.gallery_layout == layout)
        row.clicked.connect(lambda checked=False, selected=layout: (
            self.arrangement_actions[selected].trigger(), self.arrangement_menu.hide()))
    arrangement_widget_action = QWidgetAction(self.arrangement_menu)
    arrangement_widget_action.setDefaultWidget(arrangement_panel)
    self.arrangement_menu.addAction(arrangement_widget_action)
    self.grid_button.clicked.connect(lambda: self.arrangement_menu.popup(
        self.grid_button.mapToGlobal(QPoint(self.grid_button.width() - 1,
                                            self.grid_button.height() - 1))))
    self.grid_button.setToolTip("布局方式")
    self.search_edit = ToolbarSearchEdit()
    self.search_edit.setObjectName("photoSearch")
    self.search_edit.setPlaceholderText("搜索")
    self.search_edit.setFixedSize(200, 32)
    self.search_edit.setToolTip("")
    search_palette = self.search_edit.palette()
    search_palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#97999f"))
    self.search_edit.setPalette(search_palette)
    self.search_edit.textChanged.connect(self._search_photos)
    self.search_toggle = ToolbarIconButton()
    self.search_toggle.setObjectName("searchToggle")
    self.search_toggle.setIcon(search_icon())
    self.search_toggle.setIconSize(TOOLBAR_ICON_SIZE)
    self.search_toggle.setFixedSize(26, 26)
    self.search_toggle.setToolTip("搜索照片")
    self.search_toggle.setAccessibleName("搜索照片")
    self.search_toggle.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    self.search_popup = QMenu(self.search_toggle)
    self.search_popup.setObjectName("toolbarSearchPopup")
    search_container = QWidget()
    search_layout = QHBoxLayout(search_container)
    search_layout.setContentsMargins(8, 7, 8, 7)
    self.compact_search_edit = ToolbarSearchEdit()
    self.compact_search_edit.setObjectName("compactPhotoSearch")
    self.compact_search_edit.setPlaceholderText("搜索")
    self.compact_search_edit.setFixedSize(200, 32)
    self.compact_search_edit.textChanged.connect(self._search_photos)
    self.search_scope_menu = QMenu(self.search_edit)
    self.search_scope_menu.setObjectName("toolbarSearchScopeMenu")
    search_scope_panel = SearchScopePanel()
    self.search_scope_rows = search_scope_panel.rows
    for scope, row in self.search_scope_rows.items():
        row.setChecked(scope in self.filters.search_scopes)
        row.toggled.connect(lambda checked, key=scope: self._set_search_scope(key, checked))
    scope_action = QWidgetAction(self.search_scope_menu)
    scope_action.setDefaultWidget(search_scope_panel)
    self.search_scope_menu.addAction(scope_action)
    self.search_edit.scope_menu = self.search_scope_menu
    self.compact_search_edit.scope_menu = self.search_scope_menu
    search_layout.addWidget(self.compact_search_edit)
    search_action = QWidgetAction(self.search_popup)
    search_action.setDefaultWidget(search_container)
    self.search_popup.addAction(search_action)
    self.search_popup.aboutToShow.connect(
        lambda: QTimer.singleShot(0, self.compact_search_edit.setFocus))
    self.search_toggle.setMenu(self.search_popup)
    self.sort_combo = QComboBox(self)
    self.sort_combo.setObjectName("sortPicker")
    self.sort_combo.addItem("名称 ↑", "name_asc")
    self.sort_combo.addItem("名称 ↓", "name_desc")
    self.sort_combo.addItem("星级 ↓", "rating_desc")
    self.sort_combo.addItem("星级 ↑", "rating_asc")
    self.sort_combo.setToolTip("排序方式")
    self.sort_combo.currentIndexChanged.connect(
        lambda: self._apply_filter(preferred=self.current_key))
    self.sort_combo.hide()
    right_tools_layout.addWidget(self.filter_container)
    right_tools_layout.addWidget(self.search_toggle)
    right_tools_layout.addWidget(self.search_edit)
    header.addWidget(right_tools)
    self.grid_right_tools = right_tools
    self.loupe_right_tools = QWidget()
    loupe_tools_layout = QHBoxLayout(self.loupe_right_tools)
    loupe_tools_layout.setContentsMargins(0, 0, 0, 0)
    loupe_tools_layout.setSpacing(0)
    self.image_rotate_button = ToolbarIconButton()
    self.image_rotate_button.setObjectName("imageRotate")
    self.image_rotate_button.setIcon(theme_icon("loupe.rotate", 16))
    self.image_rotate_button.setIconSize(QSize(16, 16))
    self.image_rotate_button.setFixedSize(26, 26)
    self.image_rotate_button.setToolTip("旋转")
    self.image_rotate_button.setAccessibleName("逆时针旋转 90°")
    self.image_rotate_button.clicked.connect(lambda: self.preview_canvas.rotate_counterclockwise())
    loupe_tools_layout.addWidget(self.image_rotate_button)
    self.review_auto_advance_button = ToolbarIconButton()
    self.review_auto_advance_button.setObjectName("reviewAutoAdvance")
    self.review_auto_advance_button.setIcon(theme_icon("loupe.auto.advance", 16))
    self.review_auto_advance_button.setIconSize(QSize(16, 16))
    self.review_auto_advance_button.setFixedSize(26, 26)
    self.review_auto_advance_button.setCheckable(True)
    self.review_auto_advance_button.setChecked(self.store.data.get("review_auto_advance") is True)
    self.review_auto_advance_button.setAccessibleName("标记后自动下一张")
    self.review_auto_advance_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    self.review_auto_advance_button.toggled.connect(self._set_review_auto_advance)
    loupe_tools_layout.addWidget(self.review_auto_advance_button)
    self.image_fit_button = ToolbarIconButton()
    self.image_fit_button.setObjectName("imageFit")
    self.image_fit_button.setIcon(theme_icon("loupe.fit", 14))
    self.image_fit_button.setIconSize(QSize(14, 14))
    self.image_fit_button.setFixedSize(26, 26)
    self.image_fit_button.setEnabled(False)
    self.image_fit_button.setAccessibleName("大图模式（尚未开放）")
    loupe_tools_layout.addWidget(self.image_fit_button)
    self.previous_button = ToolbarIconButton()
    self.next_button = ToolbarIconButton()
    for button, direction, title in ((self.previous_button, -1, "上一张"),
                                      (self.next_button, 1, "下一张")):
        button.setObjectName("imagePrevious" if direction < 0 else "imageNext")
        button.setIcon(navigation_icon(direction))
        button.setIconSize(QSize(24, 24))
        button.setFixedSize(26, 26)
        button.setToolTip(title)
        button.setAccessibleName(title)
        button.clicked.connect(lambda checked=False, step=direction: self.move_selection(step))
        loupe_tools_layout.addWidget(button)
    header.addWidget(self.loupe_right_tools)
    self.loupe_right_tools.hide()
    self.header_layout = header
