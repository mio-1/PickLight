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

    def test_descendants_are_rejected_before_import_or_binding(self):
        w = self.window
        old = w.store.add_project(self.source)
        target = w.store.add_folder("待关联")
        child = self.source / "子目录"
        nested = child / "更深一层"
        nested.mkdir(parents=True)
        before = deepcopy(w.store.data)
        for folder in (child, nested):
            for options in ({}, {"bind_to_id": target["id"]}):
                with self.subTest(folder=folder, options=options), \
                        patch("picklight.projects.QFileDialog.getExistingDirectory", return_value=str(folder)), \
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

    def test_ancestor_is_rejected_before_import_or_binding(self):
        w = self.window
        child = self.source / "子目录"
        child.mkdir()
        old = w.store.add_project(child)
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

    def test_similar_directory_names_do_not_block_unrelated_sources(self):
        w = self.window
        w.store.add_project(self.source)
        sibling = self.root / (self.source.name + "备份")
        sibling.mkdir()
        self.assertEqual(w._validate_import_target(sibling, None, None), sibling.resolve())

    def test_new_ancestor_binding_is_rechecked_before_commit(self):
        w = self.window
        child = self.source / "子目录"
        child.mkdir()
        prepared = prepare_project(child)
        target = w.store.add_folder("待关联")
        w._pending_import = (None, target["id"])
        w.import_progress.begin()
        w.store.add_project(self.source)
        with patch("picklight.projects.QMessageBox.warning") as warning:
            w._finish_import(prepared)
        warning.assert_called_once()
        self.assertIsNone(w.store.project_by_id(target["id"])["folder"])
        self.assertIsNone(w.store.project_for_folder(child))
        self.assertFalse(w.import_progress.isVisible())

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
