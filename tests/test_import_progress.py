"""Import preparation is asynchronous and cancellation never publishes a source."""

import os
from pathlib import Path
from threading import Event, get_ident
import tempfile
import time
import unittest
from unittest.mock import patch

from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFrame

from picklight.projects import prepare_project
from picklight.window import MainWindow


class ImportProgressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        override = patch.dict(os.environ, {"PICKLIGHT_SETTINGS": str(self.root / "settings.json")})
        override.start()
        self.addCleanup(override.stop)
        self.window = MainWindow(restore_project=False)
        self.window.show()
        self.addCleanup(self.window.close)
        self.app.processEvents()
        self.source = self.root / "photos"
        self.source.mkdir()
        image = QImage(64, 48, QImage.Format.Format_RGB32)
        image.fill("#526e7d")
        image.save(str(self.source / "photo.jpg"))

    def wait_for(self, predicate):
        deadline = time.monotonic() + 5
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(5)
        self.assertTrue(predicate())

    def test_prepare_reports_actual_physical_file_counts(self):
        (self.source / "photo.ARW").write_bytes(b"raw metadata fixture")
        values = []
        prepared = prepare_project(self.source, progress=lambda *args: values.append(args))
        self.assertEqual(len(prepared.pairs), 1)
        self.assertEqual(values[0][:2], (0, 2))
        self.assertEqual(values[-1][:2], (2, 2))

    def test_progress_has_real_divider_and_ten_pixel_close_icon(self):
        progress = self.window.import_progress
        divider = progress.findChild(QFrame, "importProgressDivider")
        self.assertIsNotNone(divider)
        self.assertEqual(divider.height(), 1)
        self.assertEqual(progress.cancel_button.iconSize().width(), 10)
        self.assertEqual((progress.cancel_button.width(), progress.cancel_button.height()), (28, 28))
        self.assertEqual(progress.status.objectName(), "importProgressStatus")

    def test_import_prepares_on_worker_then_commits_and_hides_progress(self):
        started, release = Event(), Event()
        threads = []

        def slow(folder, **kwargs):
            threads.append(get_ident())
            started.set()
            release.wait(3)
            return prepare_project(folder, **kwargs)

        try:
            with patch("picklight.importing.prepare_project", side_effect=slow), \
                    patch("picklight.projects.QFileDialog.getExistingDirectory", return_value=str(self.source)):
                self.window.choose_project()
                self.wait_for(started.is_set)
                self.assertNotEqual(threads[0], get_ident())
                self.assertTrue(self.window.import_progress.isVisible())
                self.assertTrue(self.window.import_progress.timer.isActive())
                self.assertEqual(self.window.store.projects(), [])
                release.set()
                self.wait_for(lambda: not self.window.import_loader.busy)
                self.assertEqual(self.window.project_folder, self.source.resolve())
                self.assertFalse(self.window.import_progress.isVisible())
                self.assertFalse(self.window.import_progress.timer.isActive())
        finally:
            release.set()

    def test_cancelled_completion_does_not_add_or_select_folder(self):
        started, release = Event(), Event()

        def slow(folder, **kwargs):
            started.set()
            release.wait(3)
            return prepare_project(folder, **kwargs)

        try:
            with patch("picklight.importing.prepare_project", side_effect=slow), \
                    patch("picklight.projects.QFileDialog.getExistingDirectory", return_value=str(self.source)):
                self.window.choose_project()
                self.wait_for(started.is_set)
                future = self.window.import_loader.future
                self.window.import_progress.cancel_button.click()
                self.assertFalse(self.window.import_progress.isVisible())
                self.assertFalse(self.window.import_loader.busy)
                release.set()
                self.wait_for(future.done)
                self.app.processEvents()
                self.assertEqual(self.window.store.projects(), [])
                self.assertIsNone(self.window.project_id)
        finally:
            release.set()

    def test_failed_import_hides_progress_without_creating_project(self):
        with patch("picklight.importing.prepare_project", side_effect=OSError("unavailable")), \
                patch("picklight.projects.QFileDialog.getExistingDirectory", return_value=str(self.source)), \
                patch("picklight.projects.QMessageBox.warning") as warning:
            self.window.choose_project()
            self.wait_for(lambda: not self.window.import_loader.busy)
            warning.assert_called_once()
            self.assertFalse(self.window.import_progress.isVisible())
            self.assertEqual(self.window.store.projects(), [])
