"""Folder deletion undo changes only library records and never source photos."""

import os
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QEvent
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QDialog

from picklight.folder_dialogs import DeleteFolderDialog
from picklight.session import SessionStore
from picklight.theme import STYLE
from picklight.window import MainWindow


class FolderUndoTests(unittest.TestCase):
    def test_deep_folder_branch_keeps_project_order_without_recursion(self):
        store = object.__new__(SessionStore)
        store.data = {"projects": [{"id": str(index), "parent_id": str(index - 1)}
                                  for index in range(1500)]}
        store.data["projects"].append({"id": "other", "parent_id": None})
        self.assertEqual([project["id"] for project in store.folder_branch("0")],
                         [str(index) for index in range(1500)])
        self.assertEqual(store.folder_branch("missing"), [])

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.style = cls.app.styleSheet()
        cls.app.setStyleSheet(STYLE)

    @classmethod
    def tearDownClass(cls):
        cls.app.setStyleSheet(cls.style)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        environment = patch.dict(os.environ, {"PICKLIGHT_SETTINGS": str(self.root / "settings.json")})
        environment.start()
        self.addCleanup(environment.stop)
        errors = []
        hook = patch("sys.excepthook", lambda *error: errors.append(error))
        hook.start()
        self.addCleanup(hook.stop)
        self.addCleanup(lambda: self.assertFalse(errors, errors))

    def window(self):
        window = MainWindow(restore_project=False)
        window.show()
        self.addCleanup(window.close)
        self.app.processEvents()
        return window

    def test_branch_order_metadata_and_unrelated_edits_survive_undo(self):
        store = SessionStore()
        before = store.add_folder("Before")
        parent = store.add_folder("Parent")
        child = store.add_folder("Child", parent["id"])
        after = store.add_folder("After")
        store.set_folder_description(child["id"], "Original description")
        store.set_folder_appearance(parent["id"], icon="camera", color="#ffaabb")
        store.data["collapsed_folder_ids"] = [parent["id"]]
        original = deepcopy(store.projects())
        deletion = store.delete_folder_undoable(parent["id"])
        store.rename_project(after["id"], "Renamed after deletion")
        new = store.add_folder("New")
        store.data["sidebar_width"] = 298
        store.undo_folder_deletion(deletion)
        self.assertEqual([p["id"] for p in store.projects()],
                         [p["id"] for p in original] + [new["id"]])
        self.assertEqual(store.project_by_id(child["id"]), original[2])
        self.assertEqual(store.project_by_id(parent["id"]), original[1])
        self.assertEqual(store.project_by_id(after["id"])["name"], "Renamed after deletion")
        self.assertEqual(store.data["sidebar_width"], 298)
        self.assertIn(parent["id"], store.data["collapsed_folder_ids"])
        self.assertIsNotNone(store.project_by_id(before["id"]))
        self.assertEqual(SessionStore().projects(), store.projects())

    def test_undo_preserves_unrelated_and_legacy_settings(self):
        store = SessionStore()
        folder = store.add_folder("Deleted")
        legacy = [{"id": "old-record", "jpg": str(self.root / "prior.JPG")}]
        store.data["trash"] = deepcopy(legacy)
        deletion = store.delete_folder_undoable(folder["id"])
        store.data["photo_decisions"] = {"unrelated": "keep"}
        store.undo_folder_deletion(deletion)
        self.assertEqual(store.data["trash"], legacy)
        self.assertEqual(store.data["photo_decisions"], {"unrelated": "keep"})
        self.assertEqual(len(store.projects()), 1)

    def test_delete_dialog_has_a_short_photo_safety_hint_without_recycle_options(self):
        window = self.window()
        dialog = DeleteFolderDialog("Photos", window)
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(dialog.message.text(), '这个操作无法复原，确认删除“Photos”文件夹吗？')
        self.assertEqual(dialog.photo_hint.text(), "原始照片将保留在源目录中")
        self.assertEqual(dialog.photo_hint.objectName(), "folderModalHint")
        self.assertFalse(dialog.findChildren(QCheckBox))
        self.assertTrue(dialog.cancel_button.isDefault())

    def test_old_records_are_preserved_without_hiding_source_photos(self):
        window = self.window()
        source = self.root / "legacy-source"
        source.mkdir()
        photo = source / "old.JPG"
        image = QImage(40, 30, QImage.Format.Format_RGB32)
        image.fill("#526e7d")
        image.save(str(photo), "JPEG")
        original = photo.read_bytes()
        legacy = [{"id": "legacy", "jpg": str(photo)}]
        window.store.data["trash"] = deepcopy(legacy)
        window.store.save()
        window.open_project(source)
        self.assertEqual([p.display_path for p in window.visible], [photo])
        self.assertEqual(window.store.data["trash"], legacy)
        self.assertEqual(set(window.sidebar_nav), {"all", "rated", "marked"})
        shortcuts = {action.shortcut().toString() for action in window.actions()}
        self.assertNotIn("Shift+Del", shortcuts)
        self.assertEqual(photo.read_bytes(), original)

    def test_rebound_source_does_not_produce_duplicate_folders(self):
        store = SessionStore()
        source = store.add_project(self.root)
        deletion = store.delete_folder_undoable(source["id"])
        replacement = store.add_project(self.root)
        with self.assertRaises(ValueError):
            store.undo_folder_deletion(deletion)
        self.assertEqual([p["id"] for p in store.projects()], [replacement["id"]])

    def test_empty_folder_toast_undo_close_and_latest_deletion(self):
        window = self.window()
        first = window.store.add_folder("First")
        second = window.store.add_folder("Second")
        window._refresh_project_list()
        window._remove_project_item(window._project_items[first["id"]])
        toast = window.folder_delete_toast
        self.assertTrue(toast.isVisible())
        self.assertIn("First", toast.message.text())
        window._remove_project_item(window._project_items[second["id"]])
        toast.undo_button.click()
        self.assertIsNone(window.store.project_by_id(first["id"]))
        self.assertIsNotNone(window.store.project_by_id(second["id"]))
        self.assertFalse(toast.isVisible())
        self.assertNotIn("trash", window.store.data)
        window._remove_project_item(window._project_items[second["id"]])
        toast.close_button.click()
        self.assertIsNone(window.store.project_by_id(second["id"]))
        self.assertFalse(toast.isVisible())

    def test_undo_restores_source_branch_without_changing_photos(self):
        window = self.window()
        source = self.root / "photos"
        source.mkdir()
        photo = source / "image.JPG"
        image = QImage(40, 30, QImage.Format.Format_RGB32)
        image.fill("#526e7d")
        image.save(str(photo), "JPEG")
        original = photo.read_bytes()
        window.open_project(source)
        project_id = window.project_id
        child = window.store.add_folder("Child", project_id)
        window._refresh_project_list()
        window._project_items[project_id].setExpanded(False)
        with patch.object(DeleteFolderDialog, "exec", return_value=QDialog.DialogCode.Accepted):
            window._remove_project_item(window._project_items[project_id])
        self.assertIsNone(window.store.project_by_id(child["id"]))
        self.assertEqual(photo.read_bytes(), original)
        window.folder_delete_toast.undo_button.click()
        self.assertIsNotNone(window.store.project_by_id(child["id"]))
        self.assertEqual(window.project_id, project_id)
        self.assertFalse(window._project_items[project_id].isExpanded())
        self.assertEqual(len(window.pairs), 1)
        self.assertEqual(photo.read_bytes(), original)
        self.assertNotIn("trash", window.sidebar_nav)

    def test_collection_refreshes_after_folder_removal_without_deleting_photos(self):
        window = self.window()
        source = self.root / "collection-source"
        source.mkdir()
        photo = source / "photo.JPG"
        image = QImage(40, 30, QImage.Format.Format_RGB32)
        image.fill("#526e7d")
        image.save(str(photo), "JPEG")
        window.open_project(source)
        project_id = window.project_id
        window._open_sidebar_view("all")

        with patch.object(DeleteFolderDialog, "exec", return_value=QDialog.DialogCode.Accepted):
            window._remove_project_item(window._project_items[project_id])
        self.assertEqual(window.visible, [])
        self.assertNotIn("trash", window.store.data)
        self.assertTrue(photo.is_file())
        window.folder_delete_toast.undo_button.click()
        self.assertEqual(len(window.pairs), 1)
        self.assertEqual(window.project_id, project_id)


    def test_toast_timeout_pauses_on_hover_and_does_not_undo(self):
        window = self.window()
        window.resize(1500, 900)
        folder = window.store.add_folder("Expires" + "很长的文件夹名称" * 30)
        window._refresh_project_list()
        window._remove_project_item(window._project_items[folder["id"]])
        toast = window.folder_delete_toast
        window.resize(960, 700)
        self.app.processEvents()
        self.assertLess(toast.geometry().right(), window.centralWidget().width())
        toast.timer.setInterval(30)
        QApplication.sendEvent(toast, QEvent(QEvent.Type.Enter))
        QTest.qWait(60)
        self.assertTrue(toast.isVisible())
        QApplication.sendEvent(toast, QEvent(QEvent.Type.Leave))
        QTest.qWait(100)
        self.assertFalse(toast.isVisible())
        toast.undo_button.click()
        self.assertIsNone(window.store.project_by_id(folder["id"]))
