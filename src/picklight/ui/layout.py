"""Assemble the desktop workspace from focused region builders."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QSplitter, QVBoxLayout, QWidget

from picklight.chrome import WindowSurface
from picklight.ui.notifications import UndoToast
from picklight.ui.import_progress import ImportProgress
from picklight.ui.builders.filter_bar import build_filter_bar
from picklight.ui.builders.inspector import build_inspector
from picklight.ui.builders.pages import build_pages
from picklight.ui.builders.sidebar import build_sidebar
from picklight.ui.builders.titlebar import build_titlebar
from picklight.ui.builders.toolbar import build_toolbar


class WindowLayoutMixin:
    """Assemble regions in dependency order; behavior stays in workspace controllers."""

    def _make_ui(self):
        root = WindowSurface()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        build_titlebar(self, outer)
        body = QWidget()
        body.setObjectName("workspaceBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        outer.addWidget(body, 1)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setObjectName("workspaceSplitter")
        root.workspace_splitter = self.splitter
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(1)
        build_sidebar(self)
        viewer = QFrame(objectName="viewer")
        self.viewer = viewer
        viewer_layout = QVBoxLayout(viewer)
        viewer_layout.setContentsMargins(7, 0, 7, 10)
        viewer_layout.setSpacing(0)
        build_toolbar(self)
        build_filter_bar(self, viewer_layout)
        build_pages(self, viewer_layout)
        self.import_progress = ImportProgress()
        self.import_progress.cancelRequested.connect(self.import_loader.cancel)
        self.import_loader.progress.connect(self.import_progress.set_progress)
        viewer_layout.addWidget(self.import_progress)
        self._show_grid()
        self.splitter.addWidget(viewer)
        self.splitter.splitterMoved.connect(self._workspace_splitter_moved)
        build_inspector(self)
        for index, stretch in enumerate((0, 1, 0)):
            self.splitter.setStretchFactor(index, stretch)
        middle_width = max(1, self.width() - self._expanded_sidebar_width - self._inspector_width
                           - 2 * self.splitter.handleWidth())
        self.splitter.setSizes([self._expanded_sidebar_width, middle_width, self._inspector_width])
        if self._sidebar_collapsed:
            self.browser_panel.hide()
        self._position_sidebar_toggle()
        self._adapt_viewer_toolbar()
        body_layout.addWidget(self.splitter, 1)
        self.folder_delete_toast = UndoToast(self)
        self.statusBar().hide()
        self.preview_canvas.set_gpu_enabled(self.preferences.gpu)
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._refresh_preference_effects)
