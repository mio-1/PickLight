"""Successful imports reveal their sidebar path without expanding other folders."""

from copy import deepcopy
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from picklight.window import MainWindow


class ImportVisibilityTests(unittest.TestCase):
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

    def wait_import(self):
        deadline = time.monotonic() + 5
        while self.window.import_loader.busy and time.monotonic() < deadline:
            QTest.qWait(5)
        self.assertFalse(self.window.import_loader.busy)
        self.app.processEvents()

    def test_picker_remembers_last_successful_import_across_sidebar_changes_and_restart(self):
        source = self.root / "导入目录"
        source.mkdir()
        with patch("picklight.projects.QFileDialog.getExistingDirectory", return_value=str(source)):
            self.window.choose_project()
            self.wait_import()
        self.assertEqual(self.window.store.data["last_import_directory"], str(source.resolve()))
        other = self.window.store.add_folder("未关联")
        self.window._open_unbound_folder(other)
        with patch("picklight.projects.QFileDialog.getExistingDirectory", return_value="") as dialog:
            self.window.choose_project(bind_to_id=other["id"])
            self.assertEqual(dialog.call_args.args[2], str(source.resolve()))
        self.window.close()
        reopened = MainWindow(restore_project=False)
        self.addCleanup(reopened.close)
        with patch("picklight.projects.QFileDialog.getExistingDirectory", return_value="") as dialog:
            reopened.choose_project()
            self.assertEqual(dialog.call_args.args[2], str(source.resolve()))

    def test_import_reveals_collapsed_filtered_ancestor_path_and_preserves_other_branches(self):
        w = self.window
        top = w.store.add_folder("拍摄")
        parent = w.store.add_folder("广州", top["id"])
        other = w.store.add_folder("其他")
        w.store.add_folder("保持折叠", other["id"])
        w._refresh_project_list()
        for project in (top, parent, other):
            w._project_items[project["id"]].setExpanded(False)
        w.folder_filter_edit.setText("不会匹配新导入的目录")
        w._toggle_folder_section()
        w._set_sidebar_collapsed(True)
        source = self.root / "新照片"
        source.mkdir()
        image = QImage(64, 48, QImage.Format.Format_RGB32)
        image.fill("#526e7d")
        self.assertTrue(image.save(str(source / "photo.jpg")))
        with patch("picklight.projects.QFileDialog.getExistingDirectory", return_value=str(source)):
            w.choose_project(parent_id=parent["id"])
            self.wait_import()
        self.app.processEvents()
        item = w._project_items[w.project_id]
        self.assertTrue(w.browser_panel.isVisible())
        self.assertTrue(w.project_list.isVisible())
        self.assertEqual(w.folder_filter_edit.text(), "")
        self.assertIs(w.project_list.currentItem(), item)
        self.assertFalse(item.isHidden())
        self.assertTrue(item.isExpanded())
        self.assertTrue(w._project_items[top["id"]].isExpanded())
        self.assertTrue(w._project_items[parent["id"]].isExpanded())
        self.assertFalse(w._project_items[other["id"]].isExpanded())
        self.assertIn(other["id"], w.store.data["collapsed_folder_ids"])
        self.assertNotIn(top["id"], w.store.data["collapsed_folder_ids"])
        self.assertFalse(w.store.data["folder_section_collapsed"])
        self.assertFalse(w.store.data["sidebar_collapsed"])
        self.assertTrue(w.project_list.viewport().rect().intersects(w.project_list.visualItemRect(item)))

    def test_reimport_of_an_existing_folder_shows_warning_without_starting_progress(self):
        w = self.window
        source = self.root / "empty"
        source.mkdir()
        project = w.store.add_project(source)
        w.store.add_folder("子文件夹", project["id"])
        w._refresh_project_list()
        w._project_items[project["id"]].setExpanded(False)
        w._toggle_folder_section()
        before = deepcopy(w.store.data)
        with patch("picklight.projects.QFileDialog.getExistingDirectory", return_value=str(source)), \
                patch("picklight.projects.QMessageBox.warning") as warning, \
                patch.object(w.import_loader, "load") as load:
            w.choose_project()
        warning.assert_called_once()
        self.assertIn(project["name"], warning.call_args.args[2])
        load.assert_not_called()
        self.assertTrue(w.import_progress.isHidden())
        self.assertEqual(w.store.data, before)

    def test_cancel_or_failed_import_keeps_sidebar_state_and_filter(self):
        w = self.window
        w.folder_filter_edit.setText("保留筛选")
        w._toggle_folder_section()
        w._set_sidebar_collapsed(True)
        before = deepcopy(w.store.data)
        for chosen in ("", str(self.root)):
            with self.subTest(chosen=chosen), patch("picklight.projects.QFileDialog.getExistingDirectory", return_value=chosen), \
                    patch.object(w, "open_project", return_value=False):
                w.choose_project()
                self.wait_import()
                self.app.processEvents()
                self.assertTrue(w._sidebar_collapsed)
                self.assertTrue(w._folder_section_collapsed)
                self.assertEqual(w.folder_filter_edit.text(), "保留筛选")
                self.assertEqual(w.store.data, before)
