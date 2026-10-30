"""Coordinate window resizing, sidebar geometry and shutdown."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QSize, QTimer, Qt
from PySide6.QtWidgets import QApplication, QToolButton, QWidget

from picklight.chrome import window_resize_edges


class WindowChromeMixin:
    def _workspace_splitter_moved(self, _position, index):
        if index == 1 and not self._sidebar_collapsed:
            self._expanded_sidebar_width = self.browser_panel.width()
            self.store.data["sidebar_width"] = self._expanded_sidebar_width
            self.store.data["sidebar_width_customized"] = True
            self.sidebar_save_timer.start()
        self._adapt_viewer_toolbar()
        self._position_sidebar_toggle()
        self.title_bar.update()
        self.centralWidget().update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not hasattr(self, "_chrome_resize_timer"):
            self._chrome_resize_timer = QTimer(self)
            self._chrome_resize_timer.setSingleShot(True)
            self._chrome_resize_timer.setInterval(0)
            self._chrome_resize_timer.timeout.connect(self._refresh_window_layout)
        if not self._chrome_resize_timer.isActive():
            self._chrome_resize_timer.start()

    def _refresh_window_layout(self):
        self._adapt_viewer_toolbar()
        self._position_sidebar_toggle()
        self.title_bar.update()
        if hasattr(self, "filmstrip") and self.center_stack.currentIndex() == 0:
            self._schedule_grid_resize()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._adapt_viewer_toolbar)
        QTimer.singleShot(0, self._position_sidebar_toggle)
        if self._sidebar_collapsed:
            QTimer.singleShot(0, self._size_collapsed_splitter)

    def _position_sidebar_toggle(self):
        if not hasattr(self, "title_left") or not hasattr(self, "browser_panel"):
            return
        medium = hasattr(self, "center_stack") and self.center_stack.currentIndex() == 1
        collapsed = self._sidebar_collapsed
        # Share one continuous toolbar when the sidebar is hidden, in either view.
        if collapsed:
            for index, button in enumerate((self.menu_button, self.sidebar_toggle)):
                if button.parentWidget() is not self.viewer_toolbar:
                    self.header_layout.insertWidget(index, button)
                    self.header_leading_spacer += 1
                    self.header_trailing_spacer += 1
            self.title_left.hide()
        else:
            for button in (self.menu_button, self.sidebar_toggle):
                if button.parentWidget() is not self.title_left:
                    if button is self.menu_button:
                        self.title_left.layout().insertWidget(0, button)
                    else:
                        self.title_left.layout().addWidget(button)
                    self.header_leading_spacer -= 1
                    self.header_trailing_spacer -= 1
            self.title_left.show()
        self.sidebar_toggle.show()
        self.menu_button.setVisible(not (medium and collapsed))
        self.header_layout.setContentsMargins(8 if collapsed else 14, 8, 14, 0)
        self.header_layout.setSpacing(0 if collapsed else 6)
        self.file_label.setContentsMargins((10 if medium else 6) if collapsed else 0, 0, 0, 0)
        for button in (self.menu_button, self.sidebar_toggle, self.loupe_back_button,
                       self.folder_back_button, self.folder_forward_button):
            button.setFixedSize(24, 26)
        self.menu_button.setIconSize(QSize(16, 16))
        self.sidebar_toggle.setIconSize(QSize(14, 14))
        self.title_left.setFixedWidth(90 if collapsed else self.browser_panel.width())
        self.title_right.setFixedWidth(self.inspector.width())
        self.title_bar.update()

    def _size_collapsed_splitter(self):
        if self._sidebar_collapsed and self.splitter.isVisible():
            middle = max(1, self.splitter.width() - self._inspector_width - self.splitter.handleWidth())
            self.splitter.setSizes([0, middle, self._inspector_width])

    def _set_sidebar_collapsed(self, collapsed: bool):
        if collapsed == self._sidebar_collapsed:
            return
        if collapsed:
            self._expanded_sidebar_width = max(210, min(340, self.browser_panel.width()))
            self._inspector_width = self.inspector.width()
            self.browser_panel.hide()
            self._sidebar_collapsed = True
            self._size_collapsed_splitter()
        else:
            self.browser_panel.show()
            middle = max(1, self.splitter.width() - self._expanded_sidebar_width - self._inspector_width
                         - 2 * self.splitter.handleWidth())
            self.splitter.setSizes([self._expanded_sidebar_width, middle, self._inspector_width])
        self._sidebar_collapsed = collapsed
        self.title_bar.update()
        self.sidebar_toggle.setChecked(collapsed)
        self.sidebar_toggle.setToolTip("左栏")
        self.sidebar_toggle.setAccessibleName(self.sidebar_toggle.toolTip())
        self.store.data["sidebar_collapsed"] = collapsed
        self.store.data["sidebar_width"] = self._expanded_sidebar_width
        self.store.save()
        self._position_sidebar_toggle()
        self._adapt_viewer_toolbar()
        QTimer.singleShot(0, self._resize_grid)

    def _adapt_viewer_toolbar(self):
        if hasattr(self, "zoom_controls") and hasattr(self, "search_edit"):
            width = self.viewer.width()
            grid = self.center_stack.currentIndex() == 0
            medium = self.center_stack.currentIndex() == 1
            large_toolbar = width >= 700
            listing = not medium
            show_zoom = listing and width >= 580
            self.folder_navigation.setVisible(not medium)
            self.loupe_back_button.setVisible(medium)
            self.zoom_slider.setFixedWidth(88 if large_toolbar else 64)
            self.zoom_controls.setVisible(show_zoom)
            self.loupe_zoom_controls.setVisible(medium)
            self.grid_right_tools.setVisible(listing)
            self.loupe_right_tools.setVisible(medium)
            search_width = 200 if width >= 1050 else 180
            self.search_edit.setFixedWidth(search_width if listing and large_toolbar else 0)
            self.search_toggle.setFixedWidth(26 if listing and not large_toolbar else 0)
            self.search_edit.setVisible(listing and large_toolbar)
            self.search_toggle.setVisible(listing and not large_toolbar)
            self.filter_container.setVisible(listing)
            reserved = (28 + 50 + 28 + (34 if listing else 0) +
                        (search_width if listing and large_toolbar else 26 if listing else 0) +
                        (self.zoom_controls.sizeHint().width() if show_zoom else 0) +
                        6 * 6 + 24)
            self.file_label.setMaximumWidth(90 if medium else max(40, min(420, width - reserved)))
            self.header_layout.setStretch(self.header_leading_spacer, 1)
            self.header_layout.setStretch(self.header_trailing_spacer, 1 if medium else 2 if large_toolbar else 1)
            if medium:
                self._update_loupe_navigation()

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress) and self._route_loupe_shortcut(watched, event):
            return True
        if (kind == QEvent.Type.WinIdChange and watched is self
                and hasattr(self, "preview_canvas")):
            # Adding the first OpenGL child can recreate the native window.
            QTimer.singleShot(0, self._refresh_preference_effects)
        if (kind == QEvent.Type.ToolTip and isinstance(watched, QToolButton)
                and self.isAncestorOf(watched) and watched.toolTip()):
            if not hasattr(self, "_icon_tooltip"):
                from picklight.ui.tooltips import IconTooltip
                self._icon_tooltip = IconTooltip(self)
            self._icon_tooltip.show_for(watched)
            return True
        if (kind in (QEvent.Type.Leave, QEvent.Type.MouseButtonPress, QEvent.Type.Hide)
                and hasattr(self, "_icon_tooltip") and watched is self._icon_tooltip.target):
            self._icon_tooltip.hide()
        if (kind == QEvent.Type.MouseButtonPress and isinstance(watched, QWidget)
                and watched.window() is self):
            focused = self.focusWidget()
            if (focused in (self.folder_inspector_name, self.folder_inspector_description)
                    and watched is not focused and not focused.isAncestorOf(watched)):
                focused.clearFocus()
        if kind == QEvent.Type.WindowDeactivate and self._resize_edges:
            self._resize_edges = Qt.Edge(0)
            self.releaseMouse()
        if kind == QEvent.Type.MouseButtonRelease and self._resize_edges:
            self._resize_edges = Qt.Edge(0)
            self.releaseMouse()
            return True
        if kind == QEvent.Type.MouseMove and self._resize_edges:
            delta = event.globalPosition().toPoint() - self._resize_start
            rect = self._resize_geometry.adjusted(
                delta.x() if self._resize_edges & Qt.Edge.LeftEdge else 0,
                delta.y() if self._resize_edges & Qt.Edge.TopEdge else 0,
                delta.x() if self._resize_edges & Qt.Edge.RightEdge else 0,
                delta.y() if self._resize_edges & Qt.Edge.BottomEdge else 0)
            if rect.width() < self.minimumWidth():
                if self._resize_edges & Qt.Edge.LeftEdge:
                    rect.setLeft(rect.right() - self.minimumWidth() + 1)
                else:
                    rect.setRight(rect.left() + self.minimumWidth() - 1)
            if rect.height() < self.minimumHeight():
                if self._resize_edges & Qt.Edge.TopEdge:
                    rect.setTop(rect.bottom() - self.minimumHeight() + 1)
                else:
                    rect.setBottom(rect.top() + self.minimumHeight() - 1)
            self.setGeometry(rect)
            return True
        if (kind == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
                and isinstance(watched, QWidget) and watched.window() is self
                and not self.isMaximized() and not self.isFullScreen()):
            edges = self._window_edges_at(event.globalPosition().toPoint())
            if edges:
                handle = self.windowHandle()
                if handle is not None and handle.startSystemResize(edges):
                    return True
                # Offscreen and unsupported window systems retain the constrained fallback.
                self._resize_edges = edges
                self._resize_start = event.globalPosition().toPoint()
                self._resize_geometry = self.geometry()
                self.grabMouse()
                return True
        return super().eventFilter(watched, event)

    def _window_edges_at(self, global_point: QPoint) -> Qt.Edge:
        if self.isMaximized() or self.isFullScreen():
            return Qt.Edge(0)
        return window_resize_edges(self.mapFromGlobal(global_point), self.size())

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            self.title_bar.show()
        else:
            self.title_bar.hide()
            self.showFullScreen()

    def toggle_maximize(self):
        if self.isMaximized():
            self.showNormal()
            self.maximize_button.set_kind("maximize")
        else:
            self.showMaximized()
            self.maximize_button.set_kind("restore")

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "maximize_button"):
            self.maximize_button.set_kind("restore" if self.isMaximized() else "maximize")
            self.centralWidget().update_window_shape()

    def closeEvent(self, event):
        if self.photo_file_loader.busy:
            event.ignore()
            return
        self.photo_file_loader.shutdown()
        self.batch_rating_loader.shutdown()
        if self.sidebar_save_timer.isActive():
            self.sidebar_save_timer.stop()
            self.store.save()
        if self.thumbnail_save_timer.isActive():
            self.thumbnail_save_timer.stop()
            self.store.save()
        self.import_loader.shutdown()
        self.save_timer.stop()
        self._source_apply_timer.stop()
        self.source_monitor.shutdown()
        self._save_folder_name()
        self._save_folder_description()
        self._save_session()
        self.loader.shutdown()
        self.details_loader.shutdown()
        self.palette_loader.shutdown()
        self.color_index_loader.shutdown()
        self.scroll_visibility.shutdown()
        QApplication.instance().removeEventFilter(self)
        super().closeEvent(event)
