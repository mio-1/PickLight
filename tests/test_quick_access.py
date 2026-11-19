"""Quick access refers to catalog folders without duplicating their state."""

import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from picklight.session import SessionStore
from picklight.window import MainWindow


class QuickAccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.settings = Path(directory.name) / "settings.json"
        environment = patch.dict(os.environ, {"PICKLIGHT_SETTINGS": str(self.settings)})
        environment.start()
        self.addCleanup(environment.stop)

    def window(self):
        window = MainWindow(restore_project=False)
        window.show()
        self.addCleanup(window.close)
        self.app.processEvents()
        return window

    def test_pin_order_persistence_and_undo_branch(self):
        store = SessionStore()
        parent = store.add_folder("Parent")
        child = store.add_folder("Child", parent["id"])
        store.set_quick_access(child["id"], True)
        store.set_quick_access(parent["id"], True)
        store.set_quick_access(child["id"], True)
        self.assertEqual([f["id"] for f in SessionStore().quick_access_folders()],
                         [child["id"], parent["id"]])
        deletion = store.delete_folder_undoable(parent["id"])
        self.assertEqual(store.quick_access_folders(), [])
        store.undo_folder_deletion(deletion)
        self.assertEqual([f["id"] for f in store.quick_access_folders()],
                         [child["id"], parent["id"]])
        store.set_quick_access(child["id"], False)
        self.assertIsNotNone(store.project_by_id(child["id"]))
        self.assertEqual([f["id"] for f in SessionStore().quick_access_folders()], [parent["id"]])

    def test_menu_navigation_filter_and_shared_appearance(self):
        window = self.window()
        parent = window.store.add_folder("Parent")
        child = window.store.add_folder("旅行相册", parent["id"])
        window._refresh_project_list()
        window._folder_menu_command("quick_access", child["id"])
        tree = window.quick_access_list
        self.assertTrue(tree.isVisible())
        self.assertEqual(tree.topLevelItemCount(), 1)
        self.assertIn("从快速访问移除", [a.text() for a in window._build_folder_menu(child["id"]).actions()])
        tree.setCurrentItem(tree.topLevelItem(0))
        self.assertEqual(window.project_id, child["id"])
        self.assertEqual(window.project_list.currentItem(), window._project_items[child["id"]])
        self.assertFalse(window.project_list.selectedItems())
        self.assertEqual(len(tree.selectedItems()), 1)
        source_rect = window.project_list.visualItemRect(window._project_items[child["id"]])
        QTest.mouseClick(window.project_list.viewport(), Qt.MouseButton.LeftButton,
                         pos=source_rect.center())
        self.assertFalse(tree.selectedItems())
        self.assertEqual(len(window.project_list.selectedItems()), 1)
        window._open_sidebar_view("all")
        self.assertFalse(tree.selectedItems())
        window._set_folder_appearance(child["id"], color="#ffaabb")
        self.assertEqual(tree.topLevelItem(0).data(0, Qt.ItemDataRole.UserRole + 5), "#ffaabb")
        window._project_items[child["id"]].setText(0, "新的相册")
        self.assertEqual(tree.topLevelItem(0).text(0), "新的相册")
        window.folder_filter_edit.setText("不存在")
        self.assertFalse(tree.isVisible())
        window.folder_filter_edit.clear()
        self.assertTrue(tree.isVisible())
        window._toggle_quick_access_section()
        self.assertFalse(tree.isVisible())
        self.assertTrue(SessionStore().data["quick_access_collapsed"])
        window._toggle_quick_access_section()
        window._folder_menu_command("quick_access", child["id"])
        self.assertFalse(window.quick_access_header.isVisible())
        self.assertIsNotNone(window.store.project_by_id(child["id"]))

    def test_folder_switcher_layout_search_and_quick_access(self):
        window = self.window()
        first = window.store.add_folder("First")
        second = window.store.add_folder("Second")
        window.store.set_quick_access(second["id"], True)
        window._refresh_project_list()
        self.assertLess(window.folder_switch_button.x(), window.sidebar_toggle.x())
        self.assertEqual(window.title_left.layout().indexOf(window.folder_switch_button) + 1,
                         window.title_left.layout().indexOf(window.sidebar_toggle))
        window._show_folder_switcher()
        self.app.processEvents()
        panel = window.folder_switch_panel
        self.assertTrue(panel.isVisible())
        self.assertEqual(panel.all_tab.text(), "文件夹")
        self.assertEqual(panel.quick_tab.text(), "快速访问")
        QTest.keyClick(panel.search, Qt.Key.Key_Tab)
        self.assertTrue(panel.quick_tab.isChecked())
        QTest.keyClick(panel.search, Qt.Key.Key_Tab)
        self.assertTrue(panel.all_tab.isChecked())
        panel.quick_tab.click()
        self.assertEqual(sum(not panel.folders.item(i).isHidden()
                             for i in range(panel.folders.count())), 1)
        panel.all_tab.click()
        panel.search.setText("First")
        self.assertEqual(panel.folders.itemDelegate().query, "first")
        self.assertEqual(sum(not panel.folders.item(i).isHidden()
                             for i in range(panel.folders.count())), 1)
        panel.search.returnPressed.emit()
        self.app.processEvents()
        self.assertEqual(window.project_id, first["id"])
        self.assertFalse(panel.isVisible())
        window.sidebar_toggle.click()
        self.app.processEvents()
        self.assertIs(window.folder_switch_button.parentWidget(), window.viewer_toolbar)
        self.assertEqual(window.header_layout.indexOf(window.folder_switch_button) + 1,
                         window.header_layout.indexOf(window.sidebar_toggle))
        window.sidebar_toggle.click()
        self.app.processEvents()
        self.assertEqual(window.title_left.layout().indexOf(window.folder_switch_button) + 1,
                         window.title_left.layout().indexOf(window.sidebar_toggle))

    def test_folder_icon_double_click_expands_without_rename(self):
        window = self.window()
        parent = window.store.add_folder("Parent")
        window.store.add_folder("Child", parent["id"])
        window._refresh_project_list()
        item = window._project_items[parent["id"]]
        item.setExpanded(False)
        self.app.processEvents()
        rect = window.project_list.visualItemRect(item)
        QTest.mouseDClick(window.project_list.viewport(), Qt.MouseButton.LeftButton,
                         pos=rect.topLeft() + QPoint(5, 13))
        self.assertTrue(item.isExpanded())
        self.assertFalse(window.project_list.isPersistentEditorOpen(item))
        item.setExpanded(False)
        with patch.object(window, "_rename_project_item") as rename:
            window._project_item_double_clicked(item, 0)
            self.assertTrue(item.isExpanded())
            rename.assert_not_called()
            window.preferences = replace(window.preferences, sidebar_double_click_action="rename")
            window._project_item_double_clicked(item, 0)
            rename.assert_called_once_with(item)

    def test_collapsed_counts_include_descendants_without_changing_shortcut_count(self):
        window = self.window()
        parent = window.store.add_folder("Parent")
        child = window.store.add_folder("Child", parent["id"])
        child.update(folder=str(self.settings.parent), photo_count=1250)
        window.store.set_quick_access(child["id"], True)
        window._refresh_project_list()
        self.assertEqual(window._project_items[parent["id"]].data(
            0, Qt.ItemDataRole.UserRole + 6), 1250)
        self.assertEqual(window.quick_access_list.topLevelItem(0).data(
            0, Qt.ItemDataRole.UserRole + 2), 1250)

    def test_opening_shortcut_survives_source_count_refresh(self):
        window = self.window()
        image = QImage(24, 16, QImage.Format.Format_RGB32)
        image.fill("#527e9a")
        self.assertTrue(image.save(str(self.settings.parent / "photo.jpg")))
        folder = window.store.add_project(self.settings.parent)
        window.store.set_quick_access(folder["id"], True)
        window._refresh_project_list()
        errors = []
        with patch("sys.excepthook", lambda *error: errors.append(error)):
            window.quick_access_list.setCurrentItem(window.quick_access_list.topLevelItem(0))
            self.app.processEvents()
        self.assertFalse(errors, errors)
        self.assertEqual(window.project_id, folder["id"])
        self.assertEqual(window.quick_access_list.currentItem().data(
            0, Qt.ItemDataRole.UserRole + 2), 1)
        self.assertFalse(window.project_list.selectedItems())


if __name__ == "__main__":
    unittest.main()
