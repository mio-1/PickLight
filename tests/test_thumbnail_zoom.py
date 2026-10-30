"""First-run gallery size and user-chosen size across launches."""

import os
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from picklight.window import MainWindow


class ThumbnailZoomTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

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
