"""The window palette and widget styling for PickLight's photo workspace."""

STYLE = """
QWidget { background: transparent; color: #ffffff; font-family: 'Microsoft YaHei UI'; font-size: 12px; }
QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox { selection-background-color: #2f8fe8; selection-color: #ffffff; }
QMainWindow, QWidget#root, QWidget#workspaceBody, QSplitter#workspaceSplitter { background: transparent; }
QFrame#titleBar, QFrame#viewer, QWidget#inspectorContent { background: transparent; border: 0; }
QFrame#browserPanel { background: #1f2023; border-right: 1px solid #303135; }
QFrame#inspector { background: #1f2023; border-left: 1px solid #303135; }
QFrame#folderCard { background: transparent; border: 0; }
QLabel#emptyFolderTitle { color: #ffffff; font-size: 16px; font-weight: 600; }
QLabel#emptyFolderHint { color: #898a8e; font-size: 12px; font-weight: 400; }
QPushButton#emptyFolderAction { background: #242528; border: 1px solid #343538; border-radius: 6px; color: #f7f7f8; font-size: 13px; font-weight: 400; padding: 0 12px; }
QPushButton#emptyFolderAction:hover { background: #292a2e; border-color: #404146; }
QPushButton#emptyFolderAction:pressed { background: #202124; }
QPushButton#emptyFolderAction:disabled { color: #66676c; border-color: #2e2f32; background: #202124; }
QLineEdit#folderInspectorField, QLineEdit#collectionInspectorName { background: #191a1c; border: 1px solid #2e2f32; border-radius: 6px; color: #ffffff; padding: 0 10px; font-size: 13px; }
QLineEdit#collectionInspectorName { color: #929397; }
QWidget#collectionInspector QLabel#section { color: #929397; }
QFrame#importProgressDivider { background: #303134; border: 0; }
QLabel#importProgressStatus { color: #f7f8f8; font-size: 12px; font-weight: 600; }
QProgressBar#importProgressBar { background: #303134; border: 0; border-radius: 1px; }
QProgressBar#importProgressBar::chunk { background: #3297ff; border-radius: 1px; }
QToolButton#importCancel { background: transparent; border: 0; padding: 0; }
QToolButton#importCancel:hover { background: #303134; border-radius: 4px; }
QToolTip { color: #f7f8f8; background: #131416; border: 1px solid #414246; border-radius: 3px; padding: 4px 7px; font-size: 12px; font-weight: 600; }
QFrame#iconTooltip { background: #131416; border: 1px solid #414246; border-radius: 3px; }
QLabel#iconTooltipLabel { color: #f7f8f8; font-size: 12px; font-weight: 600; background: transparent; border: 0; }
QLineEdit#folderInspectorField[role="name"] { font-weight: 400; }
QLineEdit#folderInspectorField:hover { border-color: #484a50; }
QLineEdit#folderInspectorField:focus { border-color: #2ea8f4; }
QTextEdit#folderInspectorField { background: #191a1c; border: 1px solid #2e2f32; border-radius: 6px; color: #ffffff; padding: 6px 10px; font-size: 13px; }
QTextEdit#folderInspectorField:hover { border-color: #484a50; }
QTextEdit#folderInspectorField:focus { border-color: #2ea8f4; }
QFrame#folderInspectorDivider { background: #303134; border: 0; max-height: 1px; min-height: 1px; }
QWidget#folderInspector QLabel#detailKey, QWidget#collectionInspector QLabel#detailKey { color: #e7e7eb; font-size: 11px; font-weight: 400; }
QWidget#folderInspector QLabel#detailValue, QWidget#collectionInspector QLabel#detailValue { color: #e4e4e8; font-family: 'JetBrains Mono', 'Consolas'; font-size: 11px; font-weight: 400; }
QFrame#divider { background: #34353a; max-height: 1px; min-height: 1px; }
QLabel { background: transparent; }
QLabel#section { color: rgba(255,255,255,230); font-size: 12px; font-weight: 600; }
QLabel#folderSection { color: #a7a8ad; font-size: 12px; font-weight: 400; }
QFrame#folderHeaderPill { background: transparent; border: 0; border-radius: 5px; }
QFrame#folderHeaderPill[hovered="true"] { background: #27282c; }
QLabel#folderSection[hovered="true"] { color: #ffffff; }
QLabel#folderHeaderChevron { color: #dedee2; font-size: 9px; }
QLabel#filename { color: #ffffff; font-family: "Segoe UI", "Microsoft YaHei UI"; font-size: 13px; font-weight: 600; }
QLabel#imageZoomPercent { color: #f7f7f8; font-size: 12px; font-weight: 600; }
QFrame#folderModalSurface { background: #18191c; border: 1px solid #414246; border-radius: 8px; }
QLabel#folderModalTitle { color: #f7f8f8; font-size: 16px; font-weight: 700; }
QLabel#folderMoveTitle { color: #f7f8f8; font-size: 14px; font-weight: 600; }
QLabel#folderModalBody { color: #bdbec0; font-size: 13px; }
QLabel#folderModalHint { color: #929397; font-size: 12px; }
QLabel#fileDeleteCount { color: #f7f8f8; font-size: 13px; font-weight: 600; }
QLabel#fileDeleteHint { color: #929397; font-size: 11px; }
QPushButton#folderModalCancel { background: #242528; border: 1px solid #343538; border-radius: 6px; color: #f7f8f8; padding: 5px 12px; font-size: 13px; }
QPushButton#folderModalCancel:hover { background: #303135; }
QPushButton#folderModalPrimary { background: #2f8fe8; border: 1px solid #479ef0; border-radius: 6px; color: #ffffff; font-size: 13px; font-weight: 600; }
QPushButton#folderModalPrimary:hover { background: #3b9bf4; }
QToolButton#folderModalClose { background: transparent; border: 0; border-radius: 5px; }
QToolButton#folderModalClose:hover { background: #303135; }
QFrame#folderModalSeparator { background: #303134; border: 0; }
QLineEdit#folderDestinationSearch { background: #121316; color: #ffffff; border: 1px solid #343538; border-radius: 6px; padding: 0 6px; font-size: 13px; }
QLineEdit#folderDestinationSearch:focus { border-color: #2f8fe8; }
QLabel#inspectorName { background: transparent; border: 0; padding: 0; color: #f2f2f4; font-family: 'Segoe UI', 'Microsoft YaHei UI'; font-size: 13px; font-weight: 600; }
QLabel#hint { color: rgba(255,255,255,185); }
QLabel#detailKey { color: #c2c3c8; font-size: 12px; }
QLabel#detailValue { color: #ffffff; font-size: 12px; }
QWidget#multiInspector QLabel#detailKey { color: #e7e7eb; font-size: 11px; font-weight: 400; }
QWidget#multiInspector QLabel#detailValue { color: #e4e4e8; font-family: 'JetBrains Mono', 'Consolas'; font-size: 11px; font-weight: 600; }
QWidget#inspectorContent QLabel#detailKey { color: #e7e7eb; font-size: 11px; font-weight: 400; }
QWidget#inspectorContent QLabel#detailValue, QWidget#inspectorContent QLabel#pathFolder, QWidget#inspectorContent QLabel#pathFile { color: #e4e4e8; font-family: 'JetBrains Mono', 'Consolas'; font-size: 11px; font-weight: 400; }
QWidget#folderPathLink { background: transparent; }
QLabel#pathFolder, QLabel#pathFile { color: #ffffff; font-size: 12px; }
QWidget#inspectorSectionBody { background: transparent; }
QPushButton#inspectorFlag { background: transparent; border: 0; border-radius: 3px; padding: 2px 3px; color: #797980; font-size: 10px; }
QPushButton#inspectorFlag:checked { color: #ffffff; }
QPushButton#inspectorFlag:hover { background: transparent; color: white; }
QFrame#filterBar { background: transparent; border: 0; }
QWidget#filterContent { background: transparent; border: 0; }
QPushButton { background: #252529; border: 1px solid #3b3b40; border-radius: 6px; padding: 6px 10px; color: #ffffff; }
QPushButton:hover { background: #2c2d31; border-color: #4b4c52; }
QPushButton:pressed { background: #1a1a1d; }
QPushButton#primary { background: #313136; border-color: #62626a; color: white; font-weight: 600; }
QPushButton#source { background: #202024; border: 0; border-radius: 9px; padding: 0; color: #a6a7ad; font-size: 9px; font-weight: 600; }
QPushButton#source:checked { background: #35353b; color: white; }
QPushButton#source:disabled { color: rgba(255,255,255,100); border-color: rgba(240,250,255,50); }
QToolButton#previewExpand { background: transparent; border: 0; border-radius: 5px; padding: 0; }
QToolButton#previewExpand:hover { background: rgba(255,255,255,12); }
QToolButton#viewMode { background: transparent; border: 0; border-radius: 6px; padding: 0; }
QToolButton#viewMode::menu-indicator { image: none; width: 0; }
QLineEdit#folderFilterEdit { background: #191a1c; border: 1px solid #303134; border-radius: 6px; color: #ffffff; padding: 0; font-size: 12px; }
QLineEdit#folderFilterEdit:hover { border-color: #414246; }
QLineEdit#folderFilterEdit:focus, QLineEdit#folderFilterEdit[filtering="true"] { border-color: #2ea8f4; }
QToolButton#folderFilterClear { background: transparent; border: 0; padding: 0; }
QToolButton#menuButton, QToolButton#sidebarToggle, QToolButton#projectAdd, QToolButton#folderNavigate, QToolButton#zoomAdjust, QToolButton#searchToggle, QToolButton#filterButton, QToolButton#imageBack, QToolButton#imageFit, QToolButton#imagePrevious, QToolButton#imageNext, QToolButton#filterClear { background: transparent; border: 0; border-radius: 5px; color: white; padding: 0; }
QToolButton#imageFit:checked { background: #333439; }
QToolButton#reviewAutoAdvance { background: transparent; border: 1px solid transparent; border-radius: 5px; padding: 0; }
QToolButton#reviewAutoAdvance:checked { background: #333439; border-color: #53565e; }
QToolButton#projectAdd:hover { background: #27282c; border-radius: 5px; }
QToolButton#folderNavigate:disabled, QToolButton#zoomAdjust:disabled { color: #65666b; }
QToolButton#zoomAdjust { color: #a5a6ac; font-size: 15px; }
QToolButton#menuButton::menu-indicator { image: none; width: 0; }
QToolButton#searchToggle::menu-indicator { image: none; width: 0; }
QToolButton#filterButton:checked, QToolButton#filterButton[filtered="true"] { background: #2f2f33; }
QLabel#filterBadge { background: #3297ff; color: white; border-radius: 6px; font-family: 'Segoe UI'; font-size: 10px; font-weight: 700; }
QLineEdit#photoSearch, QLineEdit#compactPhotoSearch, QComboBox#sortPicker { background: #202024; border: 1px solid #45454c; border-radius: 6px; color: white; padding: 4px 9px; }
QLineEdit#photoSearch, QLineEdit#compactPhotoSearch { background: #131416; border: 1px solid #2b2c2f; border-radius: 6px; color: #ffffff; padding: 0; font-size: 13px; }
QLineEdit#photoSearch:hover, QLineEdit#compactPhotoSearch:hover { border-color: #48494d; background: #191a1d; }
QLineEdit#photoSearch:focus, QLineEdit#compactPhotoSearch:focus { border-color: #2ea8f4; }
QLineEdit#projectNameEditor:focus, QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus { border-color: #2ea8f4; }
QMenu#folderContextMenu { background: #18191c; border: 1px solid #414246; border-radius: 8px; padding: 4px; }
QMenu#folderContextMenu::item { color: #f7f8f8; font-family: "Segoe UI", "Microsoft YaHei UI"; font-size: 13px; padding: 5px 12px 5px 8px; border-radius: 6px; }
QMenu#folderContextMenu::item:selected { background: #292a2d; }
QMenu#folderContextMenu::item:disabled { color: #68696d; }
QMenu#folderContextMenu::separator { height: 1px; background: #303134; margin: 3px 0; }
QMenu#folderContextMenu::icon { padding: 0 5px 0 2px; }
QWidget#folderIconPicker { background: #18191c; }
QToolButton#folderIconOption { background: transparent; border: 0; border-radius: 6px; padding: 0; }
QToolButton#folderIconOption:hover, QToolButton#folderIconOption:checked { background: #323336; }
QPushButton#folderIconReset { background: transparent; border: 0; border-radius: 5px; color: #bdbec0; font-size: 12px; text-align: left; padding-left: 6px; }
QPushButton#folderIconReset:hover { background: #292a2d; color: #ffffff; }
QMenu#toolbarSearchPopup { background: #18191c; border: 1px solid #37383c; border-radius: 8px; padding: 5px; }
QMenu#toolbarSearchScopeMenu, QMenu#toolbarArrangementMenu { background: #18191c; border: 1px solid #37383c; border-radius: 7px; padding: 0; }
QMenu#mainMenu { background: #202124; border: 1px solid #414246; border-radius: 8px; padding: 5px 0; }
QMenu#mainMenu::item { color: #f0f0f2; background: transparent; font-family: "Segoe UI", "Microsoft YaHei UI"; font-size: 12px; padding: 4px 16px 4px 20px; min-height: 16px; }
QMenu#mainMenu::item:selected { background: #303136; color: #ffffff; }
QMenu#mainMenu::separator { height: 1px; background: #3c3d41; margin: 3px 0; }
QWidget#searchScopePanel, QWidget#arrangementPanel { background: #18191c; }
QLabel#searchScopeHeading { color: #85868b; font-size: 11px; padding-left: 4px; }
QLabel#folderContentHeading { color: #b6b7bb; font-size: 12px; padding: 14px 16px 6px 16px; }
QMenu#ratingFilterMenu, QMenu#statusFilterMenu { background: #18191c; border: 1px solid #414246; border-radius: 6px; padding: 4px; }
QMenu#formatFilterMenu { background: #18191c; border: 1px solid #414246; border-radius: 6px; padding: 0; }
QMenu#colorFilterMenu { background: #18191c; border: 1px solid #414246; border-radius: 6px; padding: 0; }
QLineEdit#colorHexInput { background: #121316; border: 1px solid #303134; border-radius: 6px; color: #bdbec0; padding: 0; font-size: 12px; }
QLineEdit#colorHexInput:focus { border-color: #3297ff; color: #f7f8f8; }
QComboBox::drop-down { border: 0; width: 18px; }
QPushButton#windowControl, QPushButton#closeControl { background: transparent; border: 0; border-radius: 0; padding: 0; }
QListWidget, QTreeWidget#projectList, QListWidget#photoGrid { background: transparent; border: 0; outline: 0; }
QTreeWidget#projectList { selection-background-color: transparent; }
QTreeWidget#projectList::item { margin: 0; padding: 0; border: 0; }
QTreeWidget#projectList::item:selected { background: transparent; color: white; }
QTreeWidget#projectList::branch:selected { background: transparent; }
QLineEdit#projectNameEditor { background: #292a2f; border: 1px solid #62646d; border-radius: 3px; color: white; padding: 0 3px; font-size: 12px; }
QListWidget#photoGrid::item { margin: 2px; padding: 3px; border: 0; border-radius: 6px; }
QLineEdit#photoNameEditor { background: #191a1c; color: #ffffff; border: 1px solid #3297ff; border-radius: 4px; padding: 0 3px; font-size: 13px; font-weight: 500; }
QSplitter::handle { background: transparent; width: 1px; }
QScrollArea { background: transparent; border: 0; }
QScrollBar:vertical { width: 4px; background: transparent; border: 0; }
QScrollBar::handle:vertical { background: #45454b; border-radius: 2px; min-height: 32px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { height: 4px; background: transparent; border: 0; }
QScrollBar::handle:horizontal { background: #45454b; border-radius: 2px; min-width: 32px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QScrollBar::handle:hover { background: #626269; }
QSlider::groove:horizontal { height: 3px; background: rgba(255,255,255,135); border-radius: 1px; }
QSlider::handle:horizontal { width: 11px; margin: -5px 0; border-radius: 6px; background: white; }
QMenu { background: #202024; border: 1px solid #45454b; color: white; }
QMenu::item { padding: 7px 22px 7px 10px; }
QMenu::item:selected { background: #292a2e; }

"""
