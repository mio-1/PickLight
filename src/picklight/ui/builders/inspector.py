"""Build the inspector region."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from picklight.chrome import WINDOW_RESIZE_BORDER
from picklight.ui.common import ElidedLabel, label
from picklight.ui.graphics import expand_icon
from picklight.ui.palette import PaletteStrip
from picklight.ui.inspector import (
    DirectoryPathLink,
    FolderPathLink,
    FolderDescriptionEdit,
    InspectorFlagButton,
    InspectorSectionButton,
    PhotoCanvas,
    PhotoStackPreview,
    StarRatingControl,
)


def build_inspector(self):
    inspector = QFrame(objectName="inspector")
    self.inspector = inspector
    inspector.setMinimumWidth(self._inspector_width)
    inspector.setMaximumWidth(350)
    inspector_layout = QVBoxLayout(inspector)
    inspector_layout.setContentsMargins(0, 0, WINDOW_RESIZE_BORDER, 0)
    inspector_layout.setSpacing(0)
    self.inspector_scroll = QScrollArea()
    self.inspector_scroll.setWidgetResizable(True)
    self.inspector_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    info_content = QWidget(objectName="inspectorContent")
    info = QVBoxLayout(info_content)
    info.setContentsMargins(16, 6, 16, 22)
    info.setSpacing(0)
    self.preview_controls = QWidget(objectName="previewControls")
    self.preview_controls.setFixedHeight(22)
    preview_controls_layout = QHBoxLayout(self.preview_controls)
    preview_controls_layout.setContentsMargins(0, 0, 0, 0)
    preview_controls_layout.setSpacing(4)
    self.source_group = QButtonGroup(self)
    self.source_group.setExclusive(True)
    self.jpg_source_button = QPushButton("JPG", self.preview_controls)
    self.raw_source_button = QPushButton("RAW", self.preview_controls)
    for button, source in ((self.jpg_source_button, "jpg"), (self.raw_source_button, "raw")):
        button.setObjectName("source")
        button.setCheckable(True)
        button.setFixedSize(35, 19)
        button.clicked.connect(lambda checked=False, value=source: self._set_preview_source(value))
        self.source_group.addButton(button)
        preview_controls_layout.addWidget(button)
    preview_controls_layout.addStretch()
    self.preview_expand_button = QToolButton(objectName="previewExpand")
    self.preview_expand_button.setAutoRaise(True)
    self.preview_expand_button.setIcon(expand_icon())
    self.preview_expand_button.setIconSize(QSize(16, 16))
    self.preview_expand_button.setFixedSize(22, 22)
    self.preview_expand_button.setEnabled(False)
    self.preview_expand_button.setAccessibleName("大图模式（尚未开放）")
    preview_controls_layout.addWidget(self.preview_expand_button)
    info.addWidget(self.preview_controls)
    info.addSpacing(7)
    self.inspector_preview = PhotoCanvas(inspector=True)
    self.inspector_preview.setFixedHeight(220)
    info.addWidget(self.inspector_preview)
    self.palette_strip = PaletteStrip()
    self.palette_strip.colorSelected.connect(self._filter_from_palette)
    palette_row = QHBoxLayout()
    palette_row.setContentsMargins(0, 8, 0, 0)
    palette_row.addWidget(self.palette_strip, 0, Qt.AlignmentFlag.AlignHCenter)
    info.addLayout(palette_row)
    self.info_name = label("—", "inspectorName")
    self.info_name.setWordWrap(False)
    self.info_name.setFixedHeight(24)
    self.info_name.setMinimumWidth(0)
    self.info_name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    info.addSpacing(13)
    info.addWidget(self.info_name)
    info.addSpacing(8)

    self.inspector_sections = {}

    def add_section(title: str) -> QVBoxLayout:
        header = InspectorSectionButton(title)
        header.setProperty("muted", True)
        info.addWidget(header)
        body = QWidget()
        body.setObjectName("inspectorSectionBody")
        rows = QVBoxLayout(body)
        rows.setContentsMargins(0, 2, 0, 0)
        rows.setSpacing(0)
        info.addWidget(body)
        header.toggled.connect(body.setVisible)
        self.inspector_sections[title] = header
        info.addSpacing(17)
        return rows

    def add_detail_row(rows: QVBoxLayout, title: str, value: QWidget,
                       height: int = 25):
        row = QWidget()
        row.setFixedHeight(height)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)
        key = label(title, "detailKey")
        key.setFixedWidth(84)
        row_layout.addWidget(key)
        if isinstance(value, QLabel):
            if isinstance(value, ElidedLabel):
                value.elide_mode = Qt.TextElideMode.ElideRight
            value.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            value.setTextFormat(Qt.TextFormat.PlainText)
            value.setWordWrap(False)
            value.setMinimumWidth(0)
            value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            row_layout.addWidget(value, 1)
        elif isinstance(value, FolderPathLink):
            row_layout.addWidget(value, 1)
        else:
            row_layout.addWidget(value, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            row_layout.addStretch()
        rows.addWidget(row)

    attributes = add_section("属性")
    self.inspector_stars = StarRatingControl()
    self.inspector_stars.muted = True
    self.inspector_stars.star_spacing = 18
    self.inspector_stars.star_offset = -2
    self.inspector_stars.star_radius = 5.8
    self.inspector_stars.setFixedSize(90, 24)
    self.inspector_stars.ratingSelected.connect(self.set_rating)
    add_detail_row(attributes, "评分", self.inspector_stars)
    flag_actions = QWidget()
    flag_actions.setFixedSize(118, 26)
    flag_layout = QHBoxLayout(flag_actions)
    flag_layout.setContentsMargins(0, 0, 0, 0)
    flag_layout.setSpacing(6)
    self.keep_flag_button = InspectorFlagButton("保留", "keep")
    self.reject_flag_button = InspectorFlagButton("待删除", "delete")
    self.keep_flag_button.setToolTip("保留照片，取消待删除标记")
    self.reject_flag_button.setToolTip("标记为待删除，不会删除原始照片")
    for button in (self.keep_flag_button, self.reject_flag_button):
        flag_layout.addWidget(button)
    self.keep_flag_button.clicked.connect(lambda: self._set_inspector_mark(False))
    self.reject_flag_button.clicked.connect(lambda: self._set_inspector_mark(True))
    add_detail_row(attributes, "状态", flag_actions)
    self.dimensions_label = label("—", "detailValue")
    self.size_label = label("—", "detailValue")
    self.type_label = label("—", "detailValue")
    add_detail_row(attributes, "尺寸", self.dimensions_label)
    add_detail_row(attributes, "大小", self.size_label)
    add_detail_row(attributes, "类型", self.type_label)

    source = add_section("源文件")
    self.source_path_link = FolderPathLink()
    self.source_path_link.clicked.connect(self._open_current_photo_folder)
    self.edited_label = label("—", "detailValue")
    add_detail_row(source, "路径", self.source_path_link, 42)
    add_detail_row(source, "上次编辑", self.edited_label)

    camera = add_section("相机")
    self.camera_label = label("—", "detailValue")
    self.lens_label = label("—", "detailValue")
    add_detail_row(camera, "相机", self.camera_label)
    add_detail_row(camera, "镜头", self.lens_label)

    exposure = add_section("曝光")
    self.focal_label = label("—", "detailValue")
    self.aperture_label = label("—", "detailValue")
    self.shutter_label = label("—", "detailValue")
    self.iso_label = label("—", "detailValue")
    add_detail_row(exposure, "焦距", self.focal_label)
    add_detail_row(exposure, "光圈", self.aperture_label)
    add_detail_row(exposure, "快门", self.shutter_label)
    add_detail_row(exposure, "ISO", self.iso_label)

    dates = add_section("日期")
    self.imported_label = label("—", "detailValue")
    self.capture_date_label = label("—", "detailValue")
    self.modified_label = label("—", "detailValue")
    add_detail_row(dates, "导入时间", self.imported_label)
    add_detail_row(dates, "拍摄时间", self.capture_date_label)
    add_detail_row(dates, "修改时间", self.modified_label)
    info.addStretch()
    self.inspector_scroll.setWidget(info_content)
    self.inspector_stack = QStackedWidget()
    self.inspector_stack.addWidget(self.inspector_scroll)
    self.folder_inspector = QWidget(objectName="folderInspector")
    folder_info = QVBoxLayout(self.folder_inspector)
    folder_info.setContentsMargins(16, 6, 16, 20)
    folder_info.setSpacing(0)
    self.folder_inspector_name = QLineEdit()
    self.folder_inspector_name.setObjectName("folderInspectorField")
    self.folder_inspector_name.setProperty("role", "name")
    self.folder_inspector_name.setFixedHeight(32)
    self.folder_inspector_name.editingFinished.connect(self._save_folder_name)
    folder_info.addWidget(self.folder_inspector_name)
    folder_info.addSpacing(8)
    self.folder_inspector_description = FolderDescriptionEdit()
    self.folder_inspector_description.setObjectName("folderInspectorField")
    self.folder_inspector_description.setPlaceholderText("描述")
    self.folder_inspector_description.editingFinished.connect(self._save_folder_description)
    folder_info.addWidget(self.folder_inspector_description)
    folder_info.addSpacing(20)
    divider = QFrame()
    divider.setFrameShape(QFrame.Shape.HLine)
    divider.setObjectName("folderInspectorDivider")
    folder_info.addWidget(divider)
    folder_info.addSpacing(12)
    self.folder_inspector_section = InspectorSectionButton("基本信息")
    self.folder_inspector_section.setProperty("muted", True)
    self.folder_inspector_section.setProperty("eagleArrow", True)
    self.folder_inspector_section.setFixedHeight(26)
    folder_info.addWidget(self.folder_inspector_section)
    folder_rows = QWidget(objectName="inspectorSectionBody")
    folder_rows_layout = QVBoxLayout(folder_rows)
    folder_rows_layout.setContentsMargins(0, 4, 0, 0)
    folder_rows_layout.setSpacing(0)
    self.folder_inspector_section.toggled.connect(folder_rows.setVisible)
    folder_info.addWidget(folder_rows)
    self.folder_inspector_count = label("0", "detailValue")
    self.folder_inspector_size = label("0.00 bytes", "detailValue")
    self.folder_inspector_date = label("—", "detailValue")
    self.folder_inspector_link = DirectoryPathLink()
    for title, value in (("文件数", self.folder_inspector_count),
                         ("占用空间", self.folder_inspector_size),
                         ("添加日期", self.folder_inspector_date),
                         ("关联文件夹", self.folder_inspector_link)):
        row = QWidget()
        row.setFixedHeight(20)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)
        key = label(title, "detailKey")
        key.setFixedWidth(84)
        row_layout.addWidget(key)
        value.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        value.setMinimumWidth(0)
        value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        row_layout.addWidget(value, 1)
        folder_rows_layout.addWidget(row)
    folder_info.addStretch()
    self.inspector_stack.addWidget(self.folder_inspector)
    self.collection_inspector = QWidget(objectName="collectionInspector")
    collection_info = QVBoxLayout(self.collection_inspector)
    collection_info.setContentsMargins(16, 6, 16, 20)
    collection_info.setSpacing(0)
    self.collection_inspector_name = QLineEdit(objectName="collectionInspectorName")
    self.collection_inspector_name.setFixedHeight(32)
    self.collection_inspector_name.setReadOnly(True)
    self.collection_inspector_name.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    self.collection_inspector_name.setAccessibleName("当前分类")
    collection_info.addWidget(self.collection_inspector_name)
    collection_info.addSpacing(18)
    collection_divider = QFrame(objectName="folderInspectorDivider")
    collection_divider.setFixedHeight(1)
    collection_info.addWidget(collection_divider)
    collection_info.addSpacing(12)
    collection_heading = label("基本信息", "section")
    collection_heading.setFixedHeight(26)
    collection_info.addWidget(collection_heading)
    self.collection_inspector_count = label("0", "detailValue")
    self.collection_inspector_size = label("0.00 bytes", "detailValue")
    for title, value in (("文件数", self.collection_inspector_count),
                         ("占用空间", self.collection_inspector_size)):
        row = QWidget()
        row.setFixedHeight(20)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)
        key = label(title, "detailKey")
        key.setFixedWidth(84)
        row_layout.addWidget(key)
        row_layout.addWidget(value, 1)
        collection_info.addWidget(row)
    collection_info.addStretch()
    self.inspector_stack.addWidget(self.collection_inspector)
    self.multi_inspector = QWidget(objectName="multiInspector")
    multi = QVBoxLayout(self.multi_inspector)
    multi.setContentsMargins(16, 6, 16, 20)
    multi.setSpacing(0)
    self.multi_preview = PhotoStackPreview()
    multi.addWidget(self.multi_preview)
    self.multi_selection_count = QLabel()
    self.multi_selection_count.setTextFormat(Qt.TextFormat.RichText)
    self.multi_selection_count.setMinimumWidth(0)
    self.multi_selection_count.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    self.multi_selection_count.setAlignment(Qt.AlignmentFlag.AlignCenter)
    self.multi_selection_count.setFixedHeight(28)
    multi.addWidget(self.multi_selection_count)
    multi.addSpacing(18)
    multi_divider = QFrame(objectName="folderInspectorDivider")
    multi_divider.setFixedHeight(1)
    multi.addWidget(multi_divider)
    multi.addSpacing(12)
    self.multi_info_heading = InspectorSectionButton("基本信息")
    self.multi_info_heading.setProperty("muted", True)
    self.multi_info_heading.setProperty("strong", True)
    self.multi_info_heading.setProperty("alwaysArrow", True)
    self.multi_info_heading.setFixedHeight(26)
    multi.addWidget(self.multi_info_heading)
    self.multi_info_body = QWidget(objectName="inspectorSectionBody")
    multi_rows = QVBoxLayout(self.multi_info_body)
    multi_rows.setContentsMargins(0, 2, 0, 0)
    multi_rows.setSpacing(0)
    self.multi_info_heading.toggled.connect(self.multi_info_body.setVisible)
    multi.addWidget(self.multi_info_body)
    self.multi_selection_stars = StarRatingControl()
    self.multi_selection_stars.muted = True
    self.multi_selection_stars.star_spacing = 18
    self.multi_selection_stars.star_offset = -2
    self.multi_selection_stars.star_radius = 5.8
    self.multi_selection_stars.setFixedSize(90, 20)
    self.multi_selection_stars.ratingSelected.connect(self._set_selected_rating)
    self.multi_selection_size = label("0.00 bytes", "detailValue")
    for title, value in (("评分", self.multi_selection_stars), ("文件大小", self.multi_selection_size)):
        row = QWidget()
        row.setFixedHeight(20)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)
        key = label(title, "detailKey")
        key.setFixedWidth(84)
        row_layout.addWidget(key)
        row_layout.addWidget(value, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        row_layout.addStretch()
        multi_rows.addWidget(row)
    multi.addStretch()
    self.inspector_stack.addWidget(self.multi_inspector)
    inspector_layout.addWidget(self.inspector_stack, 1)

    self.splitter.addWidget(inspector)
