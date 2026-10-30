"""External source edits update the library without writing to the source files."""

import os
import tempfile
import time
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from picklight.metadata import write_jpg_rating
from picklight.source_monitor import SourceMonitor, scan_sources
from picklight.theme import STYLE
from picklight.window import MainWindow


class SourceSyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.style = cls.app.styleSheet()
        cls.app.setStyleSheet(STYLE)

    @classmethod
    def tearDownClass(cls):
        cls.app.setStyleSheet(cls.style)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.photos = self.root / "photos"
        self.photos.mkdir()
        environment = patch.dict(os.environ, {"PICKLIGHT_SETTINGS": str(self.root / "settings.json")})
        environment.start()
        self.addCleanup(environment.stop)
        errors = []
        hook = patch("sys.excepthook", lambda *error: errors.append(error))
        hook.start()
        self.addCleanup(hook.stop)
        self.addCleanup(lambda: self.assertFalse(errors, errors))

    def image(self, name="one.JPG", color="#ff0000", size=(60, 40)):
        path = self.photos / name
        path.parent.mkdir(parents=True, exist_ok=True)
        image = QImage(*size, QImage.Format.Format_RGB32)
        image.fill(color)
        self.assertTrue(image.save(str(path), "JPEG"))
        return path

    def wait_for(self, condition):
        deadline = time.monotonic() + 7
        while not condition() and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertTrue(condition())

    def window(self):
        window = MainWindow(restore_project=False)
        self.addCleanup(window.close)
        window.source_monitor.debounce.setInterval(40)
        window.source_monitor.poll.setInterval(150)
        window.show()
        window.open_project(self.photos)
        self.wait_for(lambda: bool(window.source_monitor.files) and window.current_image is not None)
        return window

    def test_snapshot_detects_rename_and_xmp_changes(self):
        photo = self.image()
        first = scan_sources((str(self.photos),), {}, set(), Event())
        renamed = photo.with_name("renamed.JPG")
        photo.rename(renamed)
        sidecar = self.photos / "renamed.xmp"
        sidecar.write_text("<xmp />")
        second = scan_sources((str(self.photos),), first.files, set(), Event())
        self.assertEqual(second.renamed[str(photo)], str(renamed))
        self.assertIn(str(sidecar), second.changed)
        self.assertEqual(second.pairs[str(self.photos)][0].display_path, renamed)

    def test_grid_sync_preserves_photo_inspector_instead_of_switching_to_folder(self):
        self.image()
        window = self.window()
        window.inspector_stack.setCurrentWidget(window.inspector_scroll)
        self.image(size=(90, 130), color="#00ff00")
        self.wait_for(lambda: window.dimensions_label.text() == "90 × 130"
                      and window.current_image is not None
                      and window.current_image.pixelColor(10, 10).green() > 240)
        self.assertIs(window.inspector_stack.currentWidget(), window.inspector_scroll)

    def test_native_watch_rearms_after_atomic_save_and_watches_new_subfolders(self):
        photo = self.image()
        monitor = SourceMonitor()
        self.addCleanup(monitor.shutdown)
        monitor.debounce.setInterval(40)
        monitor.set_sources([self.photos])
        self.wait_for(lambda: str(photo) in monitor.files)
        monitor.poll.stop()
        monitor.watch_current([photo])
        updates = []
        monitor.updated.connect(updates.append)
        temporary = self.image("temporary.JPG", "#00ff00")
        temporary.replace(photo)
        self.wait_for(lambda: bool(updates))
        self.wait_for(lambda: str(photo) in monitor.watcher.files())
        updates.clear()
        self.image("one.JPG", "#0000ff")
        self.wait_for(lambda: bool(updates))
        nested = self.image("new/nested.JPG")
        self.wait_for(lambda: str(nested) in monitor.files)
        self.assertIn(str(nested.parent), monitor.watcher.directories())

    def test_overwrite_and_external_rating_refresh_caches_and_preserve_selection(self):
        photo = self.image()
        self.image("two.JPG", "#0000ff")
        window = self.window()
        window.keep_flag_button.click()
        window.filters.path_contains = "one"
        window._apply_filter()
        window._show_loupe()
        self.image("one.JPG", "#00ff00", (80, 120))
        self.wait_for(lambda: window.dimensions_label.text() == "80 × 120"
                      and window.current_image is not None
                      and window.current_image.pixelColor(10, 10).green() > 240)
        self.assertEqual(window._current_preview_path(), photo)
        self.assertEqual(window.filters.path_contains, "one")
        self.assertIn(window.current_key, window.kept)
        self.assertEqual(window.center_stack.currentIndex(), 1)
        self.assertEqual(window.preview_canvas.source_size.width(), 80)
        self.assertEqual(window.preview_canvas.source_size.height(), 120)
        write_jpg_rating(photo, 3)
        self.wait_for(lambda: window.ratings.get(window.current_key) == 3)
        self.assertEqual(window.inspector_stars.rating, 3)

    def test_collection_add_remove_and_rename_keep_decisions_and_logical_folders(self):
        photo = self.image()
        window = self.window()
        window._open_sidebar_view("all")
        window.keep_flag_button.click()
        original_projects = [project["id"] for project in window.store.projects()]
        renamed = photo.with_name("renamed.JPG")
        photo.rename(renamed)
        self.wait_for(lambda: window._current_preview_path() == renamed)
        self.assertIn(window.current_key, window.kept)
        added = self.image("nested/two.JPG", "#0000ff")
        contents = added.read_bytes()
        self.wait_for(lambda: len(window.pairs) == 2)
        renamed.unlink()
        self.wait_for(lambda: len(window.pairs) == 1)
        self.assertEqual(window.pairs[0].display_path, added)
        self.assertEqual([project["id"] for project in window.store.projects()], original_projects)
        self.assertEqual(added.read_bytes(), contents)

    def test_sync_waits_for_description_edit_without_overwriting_it(self):
        self.image()
        window = self.window()
        project = window.store.project_by_id(window.project_id)
        window._show_folder_overview(project)
        window.activateWindow()
        window.folder_inspector_description.setFocus()
        window.folder_inspector_description.setPlainText("Unsaved user text")
        self.image("two.JPG")
        self.wait_for(lambda: window._pending_source_update is not None)
        self.assertEqual(window.folder_inspector_description.text(), "Unsaved user text")
        window.folder_inspector_description.clearFocus()
        self.wait_for(lambda: len(window.pairs) == 2)
        self.assertEqual(project["description"], "Unsaved user text")

    def test_missing_source_can_return_without_removing_its_library_record(self):
        photo = self.image()
        window = self.window()
        identity = window.project_id
        outside = self.root / "disconnected"
        self.photos.rename(outside)
        self.wait_for(lambda: not window.pairs)
        self.assertIsNotNone(window.store.project_by_id(identity))
        outside.rename(self.photos)
        self.wait_for(lambda: len(window.pairs) == 1)
        self.assertEqual(window.pairs[0].display_path, photo)
