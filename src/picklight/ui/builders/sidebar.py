"""Build the sidebar region."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from picklight.ui.common import label
from picklight.ui.folders import (
    FolderFilterEdit,
    FolderHeaderPill,
    FolderSectionHeader,
    ProjectListDelegate,
    ProjectTree,
    SidebarNavButton,
)
from picklight.ui.graphics import folder_add_icon, folder_triangle_icon


def build_sidebar(self):
    browser_panel = QFrame(objectName="browserPanel")
    browser_panel.setMinimumWidth(210)
    browser_panel.setMaximumWidth(340)
    browser_layout = QVBoxLayout(browser_panel)
    browser_layout.setContentsMargins(7, 10, 11, 10)
    browser_layout.setSpacing(0)
    self.sidebar_nav: dict[str, SidebarNavButton] = {}
    for key, title in (("all", "全部"), ("rated", "已评分"), ("marked", "待删除")):
        button = SidebarNavButton(title, key)
        button.clicked.connect(lambda checked=False, view=key: self._open_sidebar_view(view))
        browser_layout.addWidget(button)
        self.sidebar_nav[key] = button
    browser_layout.addSpacing(11)
    self.project_header = FolderSectionHeader()
    self.project_header.setFixedHeight(26)
    project_header = QHBoxLayout(self.project_header)
    project_header.setContentsMargins(13, 0, 7, 0)
    project_header.setSpacing(0)
    self.project_header_pill = FolderHeaderPill()
    self._folder_section_collapsed = bool(self.store.data.get("folder_section_collapsed", False))
    self.project_header_pill.setObjectName("folderHeaderPill")
    self.project_header_pill.setAccessibleName("展开或收起文件夹")
    self.project_header_pill.setMouseTracking(True)
    self.project_header_pill.setCursor(Qt.CursorShape.PointingHandCursor)
    self.project_header_pill.setFixedHeight(22)
    pill_layout = QHBoxLayout(self.project_header_pill)
    pill_layout.setContentsMargins(5, 0, 5, 0)
    pill_layout.setSpacing(4)
    self.project_header_label = label("文件夹 (0)", "folderSection")
    self.project_header_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    pill_layout.addWidget(self.project_header_label)
    self.project_header_arrow = QLabel(objectName="folderHeaderChevron")
    self.project_header_arrow.setPixmap(folder_triangle_icon().pixmap(QSize(12, 12)))
    self.project_header_arrow.setFixedSize(12, 12)
    arrow_policy = self.project_header_arrow.sizePolicy()
    arrow_policy.setRetainSizeWhenHidden(True)
    self.project_header_arrow.setSizePolicy(arrow_policy)
    self.project_header_arrow.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    self.project_header_arrow.hide()
    pill_layout.addWidget(self.project_header_arrow)
    project_header.addWidget(self.project_header_pill)
    project_header.addStretch()
    self.project_add_button = QToolButton()
    self.project_add_button.setObjectName("projectAdd")
    self.project_add_button.setAutoRaise(True)
    self.project_add_button.setIcon(folder_add_icon())
    self.project_add_button.setIconSize(QSize(16, 16))
    self.project_add_button.setFixedSize(24, 24)
    self.project_add_button.setCursor(Qt.CursorShape.PointingHandCursor)
    self.project_add_button.setToolTip("在所选文件夹的同级新建文件夹")
    self.project_add_button.setAccessibleName("新建文件夹")
    self.project_add_button.clicked.connect(lambda _checked=False: self._new_folder())
    project_header.addWidget(self.project_add_button)
    self.project_header.hoverChanged.connect(self._set_folder_header_hover)
    self.project_header_pill.hoverChanged.connect(self._set_folder_header_pill_hover)
    self.project_header_pill.clicked.connect(self._toggle_folder_section)
    self.project_add_button.setVisible(False)
    browser_layout.addWidget(self.project_header)
    self.project_list = ProjectTree()
    self.project_list.setObjectName("projectList")
    project_palette = self.project_list.palette()
    project_palette.setColor(QPalette.ColorRole.Highlight, QColor(0, 0, 0, 0))
    self.project_list.setPalette(project_palette)
    self.project_list.setHeaderHidden(True)
    self.project_list.setIndentation(20)
    self.project_list.setRootIsDecorated(True)
    self.project_list.setItemDelegate(ProjectListDelegate(self.project_list))
    self.project_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    self.project_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    self.project_list.setMouseTracking(True)
    self.project_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
    self.project_list.setDefaultDropAction(Qt.DropAction.MoveAction)
    self.project_list.setDropIndicatorShown(True)
    self.project_list.foldersMoved.connect(self._project_tree_moved)
    self.project_list.dragFinished.connect(lambda: self._save_folder_expansion(None))
    self.project_list.currentItemChanged.connect(self._activate_project_from_list)
    self.project_list.itemChanged.connect(self._project_item_renamed)
    self.project_list.itemExpanded.connect(self._save_folder_expansion)
    self.project_list.itemCollapsed.connect(self._save_folder_expansion)
    self.project_list.itemDoubleClicked.connect(lambda item, _column: self._rename_project_item(item))
    self.project_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    self.project_list.customContextMenuRequested.connect(self._show_project_menu)
    project_tree_area = QWidget()
    project_tree_layout = QVBoxLayout(project_tree_area)
    project_tree_layout.setContentsMargins(0, 0, 0, 0)
    project_tree_layout.setSpacing(0)
    project_tree_layout.addWidget(self.project_list)
    browser_layout.addWidget(project_tree_area, 1)
    self.project_list.setVisible(not self._folder_section_collapsed)
    self._update_folder_header_arrow()
    self._folder_filter_expanded: dict[str, bool] | None = None
    self.folder_filter_edit = FolderFilterEdit()
    self.folder_filter_edit.setObjectName("folderFilterEdit")
    self.folder_filter_edit.setPlaceholderText("筛选")
    self.folder_filter_edit.setToolTip("输入名称筛选左侧文件夹")
    self.folder_filter_edit.setAccessibleName("筛选文件夹")
    self.folder_filter_edit.setFixedHeight(28)
    self.folder_filter_edit.textChanged.connect(self._apply_folder_filter)
    folder_filter_row = QHBoxLayout()
    folder_filter_row.setContentsMargins(3, 0, 0, 0)
    folder_filter_row.addWidget(self.folder_filter_edit)
    browser_layout.addLayout(folder_filter_row)
    self.browser_panel = browser_panel
    self.splitter.addWidget(browser_panel)
