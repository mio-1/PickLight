"""Reject unavailable or duplicate sources before starting an import worker."""

from copy import deepcopy
import os
from pathlib import Path
from threading import Event
import tempfile
import time
import unittest
from unittest.mock import patch

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from picklight.projects import prepare_project
from picklight.window import MainWindow


class ImportPreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        environment = patch.dict(os.environ, {"PICKLIGHT_SETTINGS": str(self.root / "settings.json")})
        environment.start()
        self.addCleanup(environment.stop)
        self.window = MainWindow(restore_project=False)
        self.window.show()
        self.addCleanup(self.window.close)
        self.source = self.root / "照片目录"
        self.source.mkdir()
        self.app.processEvents()

    def wait_for(self, predicate):
        deadline = time.monotonic() + 5
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(5)
        self.assertTrue(predicate())

    def test_already_linked_directory_is_rejected_before_import_or_binding(self):
        w = self.window
        old = w.store.add_project(self.source)
        target = w.store.add_folder("待关联")
        before = deepcopy(w.store.data)
        for options in ({}, {"bind_to_id": target["id"]}):
            with self.subTest(options=options), \
                    patch("picklight.projects.QFileDialog.getExistingDirectory", return_value=str(self.source)), \
                    patch("picklight.projects.QMessageBox.warning") as warning, \
                    patch.object(w.import_loader, "load") as load, \
                    patch.object(w.import_progress, "begin") as begin:
                w.choose_project(**options)
                warning.assert_called_once()
                self.assertIn(old["name"], warning.call_args.args[2])
                load.assert_not_called()
                begin.assert_not_called()
                self.assertIsNone(w._pending_import)
                self.assertEqual(w.store.data, before)

    def test_missing_or_already_bound_target_never_starts_import(self):
        w = self.window
        target = w.store.add_project(self.source)
        other = self.root / "other"
        other.mkdir()
        for options in ({"bind_to_id": target["id"]}, {"parent_id": "missing"}):
            with self.subTest(options=options), \
                    patch("picklight.projects.QFileDialog.getExistingDirectory", return_value=str(other)), \
                    patch("picklight.projects.QMessageBox.warning"), \
                    patch.object(w.import_loader, "load") as load, \
                    patch.object(w.import_progress, "begin") as begin:
                w.choose_project(**options)
                load.assert_not_called()
                begin.assert_not_called()

    def test_concurrent_new_binding_is_rechecked_before_commit(self):
        w = self.window
        target = w.store.add_folder("待关联")
        started, release = Event(), Event()

        def blocked(folder, **kwargs):
            started.set()
            release.wait(4)
            return prepare_project(folder, **kwargs)

        try:
            with patch("picklight.importing.prepare_project", side_effect=blocked), \
                    patch("picklight.projects.QFileDialog.getExistingDirectory", return_value=str(self.source)), \
                    patch("picklight.projects.QMessageBox.warning") as warning:
                w.choose_project(bind_to_id=target["id"])
                self.wait_for(started.is_set)
                linked = w.store.add_project(self.source)
                release.set()
                self.wait_for(lambda: not w.import_loader.busy)
                self.assertEqual(w.store.project_by_id(target["id"])["folder"], None)
                self.assertEqual(w.store.project_for_folder(self.source)["id"], linked["id"])
                self.assertFalse(w.import_progress.isVisible())
                warning.assert_called_once()
        finally:
            release.set()
