"""Shortcut drafts, collisions, persistence, routing and contextual hints."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit

from picklight.preferences_dialog import PreferencesDialog
from picklight.shortcuts import DEFAULTS, read_shortcuts, validate
from picklight.window import MainWindow


class ShortcutPreferenceTests(unittest.TestCase):
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
        self.dialog = PreferencesDialog(self.window)
        self.dialog.show()
        self.app.processEvents()
        self.addCleanup(self.dialog.close)
        self.dialog.shortcuts_button.click()

    def test_page_navigation_search_and_no_preferences_binding(self):
        dialog = self.dialog
        self.assertEqual(dialog.heading.text(), "快捷键")
        self.assertTrue(dialog.shortcuts_button.property("selected"))
        page = dialog.shortcut_page
        self.app.processEvents()
        self.assertEqual(page.editors["folder.new"].findChild(QLineEdit).text(), "Ctrl + Shift + N")
        page.search.setText("RAW")
        self.assertFalse(page.rows["photo.source"].isHidden())
        self.assertTrue(page.rows["rating.1"].isHidden())
        page.search.setText("不存在")
        self.assertTrue(page.empty.isVisible())
        dialog.general_button.click()
        dialog.search.setText("标记保留")
        self.assertEqual(dialog.heading.text(), "快捷键")
        self.assertFalse(dialog.shortcuts_button.property("selected"))
        dialog.shortcuts_button.click()
        self.assertEqual(page.search.text(), "")
        self.assertTrue(self.window.preferences_action.shortcut().isEmpty())

    def test_conflict_only_warns_and_preserves_both_existing_bindings(self):
        page = self.dialog.shortcut_page
        page.search.setText("标记")
        editor = page.editors["photo.keep"]
        editor.setFocus()
        page.editors["photo.keep"].setKeySequence(QKeySequence("X"))
        self.assertEqual(page.conflict_hint.text(), "已被“标记待删除”使用")
        self.assertFalse(page.conflict_hint.isHidden())
        self.assertTrue(editor.findChild(QLineEdit).property("conflict"))
        self.assertEqual(self.dialog.status.text(), "")
        self.assertEqual(page.values()["photo.keep"], "P")
        self.assertEqual(page.values()["photo.reject"], "X")
        self.assertEqual(editor.findChild(QLineEdit).text(), "P")
        self.assertTrue(self.dialog.apply_button.isEnabled())
        self.assertEqual(self.window.shortcuts, DEFAULTS)
        page.restore_button.click()
        self.assertTrue(page.conflict_hint.isHidden())
        self.assertFalse(editor.findChild(QLineEdit).property("conflict"))
        self.assertTrue(self.dialog.apply_button.isEnabled())
        self.assertEqual(page.values(), DEFAULTS)
        self.assertNotIn("shortcuts", self.window.store.data)

    def test_backspace_clears_and_occupied_capture_preserves_empty_binding(self):
        page = self.dialog.shortcut_page
        page.search.setText("标记")
        editor = page.editors["photo.keep"]
        editor.setFocus()
        QTest.keyClick(editor, Qt.Key.Key_Backspace)
        self.app.processEvents()
        self.assertTrue(editor.keySequence().isEmpty())
        self.assertEqual(editor.findChild(QLineEdit).placeholderText(), "记录快捷键")
        self.assertEqual(editor.findChild(QLineEdit).text(), "")
        QTest.keyClick(editor, Qt.Key.Key_X)
        QTest.qWait(1100)
        self.assertTrue(editor.keySequence().isEmpty())
        self.assertEqual(page.values()["photo.reject"], "X")
        self.assertFalse(page.conflict_hint.isHidden())
        QTest.keyClick(editor, Qt.Key.Key_Backspace)
        self.app.processEvents()
        self.assertTrue(page.conflict_hint.isHidden())
        QTest.keyClick(editor, Qt.Key.Key_K)
        self.app.processEvents()
        self.assertEqual(editor.keySequence(), QKeySequence("K"))
        self.assertTrue(page.conflict_hint.isHidden())
        self.dialog.apply_button.click()
        self.assertEqual(self.window.shortcuts["photo.keep"], "K")

    def test_empty_editor_has_record_placeholder_and_never_shows_clear_button(self):
        page = self.dialog.shortcut_page
        page.search.setText("保留")
        editor = page.editors["photo.keep"]
        editor.clear()
        editor.setFocus()
        self.app.processEvents()
        line = editor.findChild(QLineEdit)
        self.assertEqual(line.placeholderText(), "记录快捷键")
        self.assertEqual(line.text(), "")
        self.assertFalse(editor.isClearButtonEnabled())
        QTest.mouseMove(editor, editor.rect().center())
        self.app.processEvents()
        self.assertFalse(editor.isClearButtonEnabled())
        editor.setKeySequence(QKeySequence("Ctrl+K"))
        self.app.processEvents()
        self.assertFalse(editor.isClearButtonEnabled())
        self.assertFalse(line.property("conflict"))
        self.assertTrue(page.conflict_hint.isHidden())

    def test_apply_updates_real_loupe_key_hud_and_persists_without_overwriting_future_data(self):
        window = self.window
        window.store.data["shortcuts"] = {"future.command": "Ctrl+9"}
        source = self.root / "photos"
        source.mkdir()
        image = QImage(64, 48, QImage.Format.Format_RGB32)
        image.fill("#526e7d")
        image.save(str(source / "photo.jpg"))
        window.open_project(source)
        self.dialog.shortcut_page.editors["photo.keep"].setKeySequence(QKeySequence("Ctrl+K"))
        self.dialog.apply_button.click()
        self.assertTrue(self.dialog.isVisible())
        self.assertEqual(window.shortcuts["photo.keep"], "Ctrl+K")
        self.dialog.reject()
        window._show_loupe()
        window.activateWindow()
        window.preview_canvas.setFocus()
        self.app.processEvents()
        QTest.keyClick(window.preview_canvas, Qt.Key.Key_P)
        self.assertFalse(window.kept)
        QTest.keyClick(window.preview_canvas, Qt.Key.Key_K, Qt.KeyboardModifier.ControlModifier)
        self.assertIn(window.current_key, window.kept)
        self.assertEqual(window.review_feedback.key_label, "Ctrl+K")
        stored = json.loads(window.store.path.read_text("utf-8"))
        self.assertEqual(stored["shortcuts"], {"photo.keep": "Ctrl+K", "future.command": "Ctrl+9"})
        self.assertEqual(read_shortcuts(stored["shortcuts"])["photo.keep"], "Ctrl+K")

    def test_cancel_discards_edits_and_failed_write_rolls_back_bindings(self):
        page = self.dialog.shortcut_page
        page.editors["photo.next"].setKeySequence(QKeySequence("Ctrl+Right"))
        with patch.object(self.window.store, "save", side_effect=OSError("disk full")):
            self.dialog.apply_button.click()
        self.assertEqual(self.window.shortcuts, DEFAULTS)
        self.assertNotIn("shortcuts", self.window.store.data)
        self.assertIn("无法保存", self.dialog.status.text())
        self.dialog.reject()
        self.assertEqual(self.window.shortcut_actions["photo.next"].shortcut(), QKeySequence("Right"))

    def test_folder_menu_uses_changed_and_cleared_bindings(self):
        page = self.dialog.shortcut_page
        page.editors["folder.rename"].setKeySequence(QKeySequence("Ctrl+E"))
        page.editors["folder.expand_all"].clear()
        self.dialog.apply_button.click()
        project = self.window.store.add_folder("folder")
        self.window._refresh_project_list()
        menu = self.window._build_folder_menu(project["id"])
        self.addCleanup(menu.close)
        rename = next(action for action in menu.actions() if action.text() == "重命名")
        expand = next(action for action in menu.actions() if action.text() == "展开/收起所有文件夹")
        self.assertEqual(rename.property("displayShortcut"), "Ctrl+E")
        self.assertFalse(expand.property("displayShortcut"))
        self.assertTrue(self.window.shortcut_actions["folder.expand_all"].shortcut().isEmpty())

    def test_capturing_a_key_and_remapped_navigation_from_loupe_toolbar(self):
        source = self.root / "navigation"
        source.mkdir()
        image = QImage(64, 48, QImage.Format.Format_RGB32)
        image.fill("#526e7d")
        for name in ("one.jpg", "two.jpg"):
            image.save(str(source / name))
        self.window.open_project(source)
        editor = self.dialog.shortcut_page.editors["photo.next"]
        editor.setFocus()
        QTest.keyClick(editor, Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(editor.keySequence(), QKeySequence("Ctrl+Right"))
        self.dialog.apply_button.click()
        self.dialog.reject()
        self.window._show_loupe()
        self.window.activateWindow()
        self.window.image_zoom_slider.setFocus()
        self.app.processEvents()
        first = self.window.current_key
        QTest.keyClick(self.window.image_zoom_slider, Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier)
        self.assertNotEqual(self.window.current_key, first)

    def test_invalid_data_and_cross_context_collisions(self):
        migrated = read_shortcuts({"photo.next": "Ctrl+A", "photo.keep": "Ctrl+K"})
        self.assertEqual(migrated["photo.next"], "Ctrl+A")
        self.assertEqual(migrated["photo.keep"], "Ctrl+K")
        self.assertEqual(migrated["photo.select_all"], "")
        self.assertEqual(read_shortcuts({"photo.keep": "unknown-key"}), DEFAULTS)
        with self.assertRaises(ValueError):
            validate({**DEFAULTS, "photo.keep": "1"})
        with self.assertRaises(ValueError):
            validate({**DEFAULTS, "photo.keep": "Alt+F4"})
        with self.assertRaises(ValueError):
            validate({**DEFAULTS, "photo.keep": "Backspace"})
        values = validate({**DEFAULTS, "photo.keep": "K", "folder.rename": "K"})
        self.assertEqual(values["photo.keep"], values["folder.rename"])
