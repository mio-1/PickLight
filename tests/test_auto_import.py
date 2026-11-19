"""Automatic folder discovery keeps local files in place."""

from pathlib import Path
from tempfile import TemporaryDirectory
from dataclasses import replace
from unittest.mock import patch
import os
import time
import unittest

from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from picklight.auto_import import AutoImportMonitor
from picklight.library import scan_pairs
from picklight.window import MainWindow


class AutoImportMonitorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_registered_folders_and_new_children_are_watched_and_disable(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first"
            first.mkdir()
            nested = first / "nested"
            nested.mkdir()
            monitor = AutoImportMonitor()
            self.addCleanup(monitor.deleteLater)
            batches = []
            monitor.discovered.connect(batches.append)
            monitor.configure(True, [root, first])
            self.assertEqual(batches, [[(nested, first)]])
            second = root / "second"
            second.mkdir()
            monitor.scan()
            self.assertEqual(batches[-1], [(second, root)])
            monitor.scan()
            self.assertEqual(len(batches), 2)
            monitor.configure(False, [root, first])
            self.assertFalse(monitor.timer.isActive())
            self.assertFalse(monitor.watcher.directories())

    def test_new_child_photos_remain_in_linked_folder_without_new_project(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            with patch.dict(os.environ, {"PICKLIGHT_SETTINGS": str(root / "settings.json")}):
                window = MainWindow(restore_project=False)
                self.addCleanup(window.close)
                window.store.add_project(source)
                window._apply_preferences(replace(window.preferences, auto_import_enabled=True))
                self.assertIsNotNone(window.store.project_for_folder(source))
                child = source / "child"
                child.mkdir()
                photo = child / "keep.jpg"
                photo.write_bytes(b"original")
                window.auto_import_monitor.scan()
                self.assertIsNone(window.store.project_for_folder(child))
                self.assertEqual(len(window.store.projects()), 1)
                self.assertIn(photo, [pair.display_path for pair in scan_pairs(source)])
                self.assertEqual(photo.read_bytes(), b"original")

    def test_switch_controls_new_files_in_linked_folder(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            image = QImage(16, 16, QImage.Format.Format_RGB32)
            image.fill("#577b9c")
            self.assertTrue(image.save(str(source / "original.jpg")))
            with patch.dict(os.environ, {"PICKLIGHT_SETTINGS": str(root / "settings.json")}):
                window = MainWindow(restore_project=False)
                self.addCleanup(window.close)
                window.source_monitor.debounce.setInterval(30)
                window.source_monitor.poll.setInterval(100)
                window.open_project(source)

                def wait_for(condition):
                    deadline = time.monotonic() + 5
                    while not condition() and time.monotonic() < deadline:
                        QTest.qWait(20)
                    self.assertTrue(condition())

                wait_for(lambda: str(source / "original.jpg") in window.source_monitor.files)
                nested = source / "new"
                nested.mkdir()
                added = nested / "added.jpg"
                self.assertTrue(image.save(str(added)))
                wait_for(lambda: str(added) in window.source_monitor.files)
                self.assertNotIn(added, [pair.display_path for pair in window.pairs])
                window._apply_preferences(replace(window.preferences, auto_import_enabled=True))
                wait_for(lambda: added in [pair.display_path for pair in window.pairs])
                self.assertIsNone(window.store.project_for_folder(nested))


if __name__ == "__main__":
    unittest.main()
