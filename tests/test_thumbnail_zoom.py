"""First-run gallery size and user-chosen size across launches."""

import os
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QEvent, QPoint, QPointF, QSize, Qt
from PySide6.QtGui import QIcon, QImage, QMouseEvent, QPixmap, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QListWidget, QListWidgetItem

from picklight.ui.gallery import PhotoGrid
from picklight.window import MainWindow


class ThumbnailZoomTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_hover_preview_requires_enabled_magnifier(self):
        grid = PhotoGrid()
        try:
            grid.setViewMode(QListWidget.ViewMode.IconMode)
            grid.setMouseTracking(True)
            grid.setIconSize(QSize(120, 90))
            grid.resize(500, 350)
            source = QPixmap(120, 90)
            source.fill("#405e72")
            item = QListWidgetItem("image")
            item.setIcon(QIcon(source))
            item.setData(Qt.ItemDataRole.UserRole + 4, QSize(120, 90))
            grid.addItem(item)
            grid.show()
            self.app.processEvents()
            lens = grid._hover_lens_rect(item)
            self.assertTrue(lens.isValid())
            def move_to(point):
                event = QMouseEvent(QEvent.Type.MouseMove, QPointF(point),
                                    QPointF(grid.viewport().mapToGlobal(point)),
                                    Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                                    Qt.KeyboardModifier.NoModifier)
                grid.mouseMoveEvent(event)

            move_to(lens.center())
            self.assertFalse(grid._hover_preview.isVisible())
            grid.hover_zoom_enabled = True
            # Exercise the handler directly: the offscreen platform's global
            # cursor can generate unrelated leave events between test windows.
            move_to(lens.center() - QPoint(45, 40))
            move_to(lens.center())
            self.assertIs(grid._hover_item, item)
            self.assertTrue(grid._hover_timer.isActive())
            grid._show_hover_preview()
            self.assertTrue(grid._hover_preview.isVisible())
            self.assertTrue(grid._hover_scrim.isVisible())
            move_to(lens.center() - QPoint(45, 40))
            self.assertFalse(grid._hover_preview.isVisible())
        finally:
            grid.close()

    def test_hover_preview_uses_complete_cached_image_at_gallery_size(self):
        grid = PhotoGrid()
        try:
            grid.setViewMode(QListWidget.ViewMode.IconMode)
            grid.resize(800, 700)
            thumb = QPixmap(120, 90)
            thumb.fill("#000000")
            image = QImage(800, 600, QImage.Format.Format_RGB32)
            image.fill("#405e72")
            item = QListWidgetItem("image")
            item.setIcon(QIcon(thumb))
            item.setData(Qt.ItemDataRole.UserRole + 6, "complete.jpg")
            grid.addItem(item)
            loader = Mock()
            loader.cached.side_effect = lambda _path, width: image if width == 2200 else None
            grid._hover_loader = loader
            grid.hover_zoom_enabled = True
            grid.show()
            self.app.processEvents()
            grid._hover_item = item
            grid._show_hover_preview()
            preview = grid._hover_preview.pixmap()
            self.assertTrue(grid._hover_preview.isVisible())
            self.assertGreater(preview.width(), 700)
            self.assertEqual(preview.toImage().pixelColor(preview.width() - 5, preview.height() // 2).name(),
                             "#405e72")
            loader.request.assert_not_called()
        finally:
            grid.close()

    def test_hover_preview_does_not_change_size_when_high_resolution_arrives(self):
        grid = PhotoGrid()
        try:
            grid.setViewMode(QListWidget.ViewMode.IconMode)
            grid.resize(800, 700)
            icon = QPixmap(120, 90)
            icon.fill("#000000")
            item = QListWidgetItem("image")
            item.setIcon(QIcon(icon))
            item.setData(Qt.ItemDataRole.UserRole + 6, "preview.jpg")
            grid.addItem(item)
            low = QImage(420, 315, QImage.Format.Format_RGB32)
            low.fill("#405e72")
            high = QImage(800, 600, QImage.Format.Format_RGB32)
            high.fill("#405e72")
            loader = Mock()
            loader.cached.side_effect = lambda _path, width: low if width == 420 else None
            grid._hover_loader = loader
            grid.hover_zoom_enabled = True
            grid.show()
            self.app.processEvents()
            grid._hover_item = item
            grid._show_hover_preview()
            initial_size = grid._hover_preview.size()
            self.assertTrue(grid._hover_preview.isVisible())
            self.assertEqual(grid._hover_preview.pixmap().toImage().pixelColor(700, 300).name(), "#405e72")
            loader.request.assert_called_once_with(Path("preview.jpg"), 900)
            grid._hover_image_ready("preview.jpg", 900, high)
            self.assertEqual(grid._hover_preview.size(), initial_size)
        finally:
            grid.close()

    def test_right_drag_keeps_gallery_layout_positions(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
                "PICKLIGHT_SETTINGS": str(Path(directory) / "settings.json")}):
            source = Path(directory) / "photos"
            source.mkdir()
            image = QImage(90, 60, QImage.Format.Format_RGB32)
            image.fill("#405e72")
            for index in range(4):
                image.save(str(source / f"{index:02}.jpg"))
            window = MainWindow(restore_project=False)
            try:
                window.show()
                window.open_project(source)
                grid = window.filmstrip
                self.app.processEvents()
                positions = [grid.visualRect(grid.model().index(row, 0)).topLeft()
                             for row in range(grid.count())]
                start = grid.visualRect(grid.model().index(0, 0)).center()
                finish = start + QPoint(90, 80)
                for kind, point, button in ((QEvent.Type.MouseButtonPress, start, Qt.MouseButton.RightButton),
                                            (QEvent.Type.MouseMove, finish, Qt.MouseButton.NoButton),
                                            (QEvent.Type.MouseButtonRelease, finish, Qt.MouseButton.RightButton)):
                    event = QMouseEvent(kind, QPointF(point), QPointF(point), button,
                                        Qt.MouseButton.RightButton if kind != QEvent.Type.MouseButtonRelease
                                        else Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
                    QApplication.sendEvent(grid.viewport(), event)
                self.app.processEvents()
                self.assertEqual(positions, [grid.visualRect(grid.model().index(row, 0)).topLeft()
                                             for row in range(grid.count())])
            finally:
                window.close()

    def test_manual_gallery_scroll_range_remains_stable_after_item_updates(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
                "PICKLIGHT_SETTINGS": str(Path(directory) / "settings.json")}):
            source = Path(directory) / "photos"
            source.mkdir()
            image = QImage(90, 60, QImage.Format.Format_RGB32)
            image.fill("#405e72")
            for index in range(9):
                image.save(str(source / f"{index:02}.jpg"))
            window = MainWindow(restore_project=False)
            try:
                window.resize(1400, 800)
                window.show()
                window.open_project(source)
                grid = window.filmstrip
                bar = grid.verticalScrollBar()
                for mode in ("grid", "waterfall"):
                    window._set_gallery_layout(mode)
                    window.zoom_slider.setValue(320)
                    QTest.qWait(150)
                    expected = window._grid_content_height - grid.viewport().height()
                    self.assertGreater(expected, 0)
                    changes = []
                    def record_range(low, high):
                        changes.append((low, high))
                    bar.rangeChanged.connect(record_range)
                    bar.setValue(73)
                    for _ in range(3):
                        grid.doItemsLayout()
                        QTest.qWait(40)
                    bar.rangeChanged.disconnect(record_range)
                    self.assertEqual(changes, [], (mode, changes))
                    self.assertEqual(bar.maximum(), expected)
                    self.assertEqual(bar.value(), 73)
                    self.assertEqual(bar.pageStep(), grid.viewport().height())
                # Reducing the content must still remove the scrollbar.
                window.zoom_slider.setValue(160)
                QTest.qWait(80)
                self.assertEqual(bar.maximum(), 0)
                self.assertFalse(bar.isVisible())
            finally:
                window.close()

    def test_waterfall_can_show_more_columns_and_control_wheel_changes_size(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
                "PICKLIGHT_SETTINGS": str(Path(directory) / "settings.json")}):
            source = Path(directory) / "photos"
            source.mkdir()
            image = QImage(90, 60, QImage.Format.Format_RGB32)
            image.fill("#405e72")
            for index in range(12):
                image.save(str(source / f"{index:02}.jpg"))
            window = MainWindow(restore_project=False)
            try:
                window.show()
                window.open_project(source)
                window._set_gallery_layout("waterfall")
                window.zoom_slider.setValue(window.zoom_slider.minimum())
                self.app.processEvents()
                width = window.filmstrip.viewport().width()
                columns = min(24, (width - 11) // (window.zoom_slider.value() + 11))
                self.assertGreater(columns, 4)
                self.assertEqual(window.zoom_slider.minimum(), 96)
                window.zoom_slider.setValue(220)
                scroll = window.filmstrip.verticalScrollBar().value()
                def wheel(delta, modifiers):
                    event = QWheelEvent(QPointF(20, 20), QPointF(20, 20), QPoint(), QPoint(0, delta),
                                        Qt.MouseButton.NoButton, modifiers, Qt.ScrollPhase.NoScrollPhase, False)
                    window.filmstrip.wheelEvent(event)
                    self.assertTrue(event.isAccepted())
                wheel(120, Qt.KeyboardModifier.ControlModifier)
                self.assertEqual(window.zoom_slider.value(), 240)
                self.assertEqual(window.filmstrip.verticalScrollBar().value(), scroll)
                wheel(-120, Qt.KeyboardModifier.ControlModifier)
                self.assertEqual(window.zoom_slider.value(), 220)
                wheel(120, Qt.KeyboardModifier.NoModifier)
                self.assertEqual(window.zoom_slider.value(), 220)
            finally:
                window.close()

    def test_first_run_has_three_columns_and_next_run_keeps_user_zoom(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
                "PICKLIGHT_SETTINGS": str(Path(directory) / "settings.json")}):
            first = MainWindow(restore_project=False)
            try:
                first.show()
                first.center_stack.setCurrentWidget(first.gallery_page)
                self.app.processEvents()
                self.assertEqual(first.zoom_slider.value(), 220)
                self.assertEqual(first.width(), 1360)
                self.assertEqual(first.browser_panel.width(), 230)
                self.assertEqual(first.inspector.width(), 265)
                width = first.filmstrip.viewport().width()
                self.assertEqual(max(1, min(7, (width - 11) // (220 + 11))), 3)
                first.zoom_slider.setValue(320)
                self.assertEqual(first.store.data["thumbnail_width"], 320)
            finally:
                first.close()
            second = MainWindow(restore_project=False)
            try:
                self.assertEqual(second.zoom_slider.value(), 320)
            finally:
                second.close()

    def test_default_window_keeps_three_columns_with_the_widest_saved_sidebar(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / "settings.json"
            settings.write_text(json.dumps({"sidebar_width": 340, "sidebar_width_customized": True}),
                                encoding="utf-8")
            with patch.dict(os.environ, {"PICKLIGHT_SETTINGS": str(settings)}):
                window = MainWindow(restore_project=False)
                try:
                    window.show()
                    window.center_stack.setCurrentWidget(window.gallery_page)
                    self.app.processEvents()
                    width = window.filmstrip.viewport().width()
                    self.assertEqual((width - 11) // (window.zoom_slider.value() + 11), 3)
                    self.assertEqual(window.width(), 1360)
                finally:
                    window.close()

    def test_legacy_width_starts_at_default_and_user_drag_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / "settings.json"
            settings.write_text(json.dumps({"sidebar_width": 293}), encoding="utf-8")
            with patch.dict(os.environ, {"PICKLIGHT_SETTINGS": str(settings)}):
                first = MainWindow(restore_project=False)
                try:
                    first.show()
                    self.app.processEvents()
                    self.assertEqual(first.browser_panel.width(), 230)
                    first.resize(1500, 800)
                    self.app.processEvents()
                    self.assertEqual(first.browser_panel.width(), 230)
                    self.assertEqual(first.inspector.width(), 265)
                    first.splitter.moveSplitter(280, 1)
                    self.app.processEvents()
                    chosen = first.browser_panel.width()
                    self.assertEqual(chosen, 280)
                    self.assertTrue(first.store.data["sidebar_width_customized"])
                finally:
                    first.close()
                second = MainWindow(restore_project=False)
                try:
                    second.show()
                    self.app.processEvents()
                    self.assertEqual(second.browser_panel.width(), chosen)
                finally:
                    second.close()
