"""Source operations use temporary photos, never the user's originals."""

import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit

from picklight.library import PhotoPair
from picklight.photo_files import capture_files, group_files, recycle_files, rename_files
from picklight.window import MainWindow


class PhotoFileTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.jpg, self.raw = self.root / "original.jpg", self.root / "original.ARW"
        self.xmp = self.raw.with_suffix(".xmp")
        for path in (self.jpg, self.raw, self.xmp):
            path.write_bytes(path.suffix.encode())
        self.pair = PhotoPair("original", self.jpg, self.raw)

    def test_pair_rename_keeps_extensions_and_sidecar_bytes(self):
        files = capture_files(group_files([self.pair], sidecars=True))
        before = {path: path.read_bytes() for path in files}
        moved = rename_files(files, "新的照片")
        self.assertEqual(len(moved), 3)
        for old, new in moved.items():
            self.assertEqual(new.stem, "新的照片")
            self.assertEqual(new.suffix, old.suffix)
            self.assertEqual(new.read_bytes(), before[old])
            self.assertFalse(old.exists())

    def test_collision_and_invalid_names_change_nothing(self):
        occupied = self.root / "used.ARW"
        occupied.write_bytes(b"do not overwrite")
        files = capture_files(group_files([self.pair], sidecars=True))
        for name in ("used", "../escape", "CON", "bad?name", "trailing.", ""):
            with self.subTest(name=name), self.assertRaises((OSError, ValueError)):
                rename_files(files, name)
        self.assertTrue(all(path.exists() for path in files))
        self.assertEqual(occupied.read_bytes(), b"do not overwrite")

    def test_partial_rename_failure_rolls_back(self):
        from picklight.photo_files import _rename_file
        calls = []

        def rename(file, destination):
            calls.append(destination)
            if len(calls) == 2:
                raise OSError("simulated rename failure")
            return _rename_file(file, destination)

        files = capture_files(group_files([self.pair], sidecars=True))
        with patch("picklight.photo_files._rename_file", rename), self.assertRaises(OSError):
            rename_files(files, "new")
        self.assertTrue(all(path.exists() for path in files))
        self.assertFalse((self.root / "new.jpg").exists())

    def test_stale_confirmation_refuses_all_mutation(self):
        files = capture_files(group_files([self.pair], sidecars=True))
        self.raw.write_bytes(b"changed after dialog")
        with patch("picklight.photo_files.QFile.moveToTrash") as trash:
            with self.assertRaises(ValueError):
                recycle_files(files)
            trash.assert_not_called()
        with self.assertRaises(ValueError):
            rename_files(files, "new")
        self.assertTrue(self.jpg.exists())

    def test_trash_failure_never_removes_originals(self):
        files = capture_files(group_files([self.pair], sidecars=True))
        # PySide resolves this overloaded API on the QFile instance; patching
        # only the class method can leave the real OS operation callable.
        with patch("picklight.photo_files.QFile", autospec=True) as file_class:
            file = file_class.return_value
            file.moveToTrash.return_value = False
            file.errorString.return_value = "simulated trash failure"
            self.assertEqual(len(recycle_files(files)), 3)
            self.assertEqual(file.moveToTrash.call_count, 3)
            file_class.remove.assert_not_called()
            file.remove.assert_not_called()
        self.assertTrue(all(path.exists() for path in files))


class PhotoMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        env = patch.dict(os.environ, {"PICKLIGHT_SETTINGS": str(self.root / "settings.json")})
        env.start()
        self.addCleanup(env.stop)
        source = self.root / "photos"
        source.mkdir()
        image = QImage(60, 40, QImage.Format.Format_RGB32)
        image.fill("#246677")
        for number in range(3):
            image.save(str(source / f"{number}.jpg"))
        self.window = MainWindow(restore_project=False)
        self.addCleanup(self.window.close)
        self.window.show()
        self.window.open_project(source)
        self.app.processEvents()
        self.window._resize_grid()

    def test_menu_labels_copy_paths_and_single_group_rename(self):
        pairs = tuple(self.window.visible[:2])
        menu = self.window._build_photo_menu(pairs)
        self.addCleanup(menu.deleteLater)
        actions = {action.data(): action for action in menu.actions() if not action.isSeparator()}
        self.assertEqual([action.text() for action in actions.values()],
                         ["在文件管理器打开", "打开文件所在位置", "重命名",
                          "设为文件夹封面", "黑白预览", "复制文件路径", "删除文件"])
        self.assertFalse(actions["rename"].isEnabled())
        for command, shortcut in (("rename", "photo.rename"),
                                  ("grayscale", "photo.grayscale")):
            self.assertEqual(actions[command].property("displayShortcut"),
                             self.window.shortcuts[shortcut])
        self.assertFalse(hasattr(self.window, "compare_button"))
        self.assertNotIn("view.compare", self.window.shortcut_actions)
        self.assertTrue(all(not action.icon().isNull() for action in actions.values()))
        actions["copy_path"].trigger()
        self.assertEqual(QApplication.clipboard().text().splitlines(), list(map(str, group_files(pairs))))
        with patch("picklight.photo_menu.subprocess.Popen") as launch:
            actions["explorer"].trigger()
            launch.assert_called_once_with(["explorer.exe", "/select,", str(pairs[0].display_path)])

    def test_folder_cover_persists_and_grayscale_is_preview_only(self):
        pair = self.window.visible[1]
        menu = self.window._build_photo_menu((pair,))
        self.addCleanup(menu.deleteLater)
        actions = {action.data(): action for action in menu.actions() if not action.isSeparator()}
        actions["cover"].trigger()
        project = self.window.store.project_for_folder(self.root / "photos")
        self.assertEqual(project["cover_path"], str(pair.display_path.resolve()))
        source = pair.display_path.read_bytes()
        from PySide6.QtGui import QImage
        color_image = QImage(32, 32, QImage.Format.Format_RGB32)
        color_image.fill("#d03020")
        row = self.window.visible.index(pair)
        self.window.loader.remember(str(pair.display_path), 420, color_image)
        self.window._paint_thumbnail(row, color_image)
        self.window.preview_canvas.set_image(color_image)
        actions["grayscale"].trigger()
        self.assertTrue(self.window.preview_canvas.grayscale)
        self.assertTrue(self.window.inspector_preview.grayscale)
        self.assertTrue(self.window.multi_preview.grayscale)
        self.assertTrue(self.window.large_screen_page.strip.grayscale)
        self.assertTrue(self.window.preferences.preview_grayscale)
        self.assertTrue(self.window.store.data["preferences"]["preview_grayscale"])
        checked_menu = self.window._build_photo_menu((pair,))
        self.addCleanup(checked_menu.deleteLater)
        checked_action = next(action for action in checked_menu.actions()
                              if action.data() == "grayscale")
        self.assertFalse(checked_action.isCheckable())
        self.assertIs(checked_action.property("trailingCheck"), True)
        center = self.window.preview_canvas.display_image().pixelColor(16, 16)
        self.assertEqual((center.red(), center.green(), center.blue()),
                         (center.red(), center.red(), center.red()))
        pixel = self.window.filmstrip.item(row).icon().pixmap(32, 32).toImage().pixelColor(16, 16)
        self.assertEqual(pixel.red(), pixel.green())
        self.assertEqual(pixel.green(), pixel.blue())
        self.assertEqual(pair.display_path.read_bytes(), source)

    def test_right_click_preserves_existing_multi_selection(self):
        grid = self.window.filmstrip
        grid.setCurrentRow(0)
        grid.item(1).setSelected(True)
        point = grid.visualItemRect(grid.item(1)).center()
        QTest.mousePress(grid.viewport(), Qt.MouseButton.RightButton, pos=point)
        self.assertEqual(len(grid.selectedItems()), 2)
        QTest.mousePress(grid.viewport(), Qt.MouseButton.RightButton,
                         pos=grid.visualItemRect(grid.item(2)).center())
        self.assertEqual(grid.selectedItems(), [grid.item(2)])

    def test_grayscale_save_failure_keeps_display_and_preference_in_sync(self):
        with patch("picklight.preferences.save_preferences", side_effect=OSError("disk full")), \
                patch("picklight.photo_menu.NoticeDialog.exec") as notice:
            self.window._set_grayscale_preview(True)
        notice.assert_called_once()
        self.assertFalse(self.window.grayscale_preview)
        self.assertFalse(self.window.preview_canvas.grayscale)
        self.assertFalse(self.window.preferences.preview_grayscale)

    def test_delete_confirmation_counts_and_cancellation(self):
        pairs = tuple(self.window.visible[:2])
        captured = []

        def cancel(dialog):
            captured.append((dialog.message.text(), dialog.counts, dialog.recovery_hint.text()))
            return QDialog.DialogCode.Rejected

        with patch("picklight.photo_menu.DeleteFilesDialog.exec", cancel), \
                patch.object(self.window.photo_file_loader, "load") as load:
            self.window._delete_photo_groups(pairs)
            load.assert_not_called()
        self.assertIn("2 组图片", captured[0][0])
        self.assertEqual(captured[0][1], {"JPG": 2, "RAW": 0})
        self.assertIn("Windows 回收站", captured[0][2])
        self.assertTrue(all(path.exists() for path in group_files(pairs)))

    def test_location_opens_owning_project_and_selects_photo(self):
        pair = self.window.visible[1]
        project = self.window._photo_locations((pair,))[0]
        self.window.filters.path_contains = "missing"
        self.window._apply_filter()
        self.assertFalse(self.window.visible)
        self.window._reveal_photo_project(project["id"], group_files([pair]))
        self.assertEqual(self.window.project_id, project["id"])
        self.assertEqual(self.window._current_pair().display_path, pair.display_path)
        self.assertFalse(self.window.filters.active)
        self.assertEqual(self.window._sidebar_selection, "folder")

    def test_async_rename_refreshes_source_and_keeps_mark(self):
        pair = self.window.visible[0]
        self.window.kept.add(pair.key)
        self.window._rename_photo_group((pair,))
        self.app.processEvents()
        editor = self.window.filmstrip.findChild(QLineEdit, "photoNameEditor")
        self.assertIsNotNone(editor)
        self.assertEqual(editor.selectedText(), pair.display_path.stem)
        self.assertEqual(editor.alignment(), Qt.AlignmentFlag.AlignCenter)
        editor.setText("renamed")
        QTest.keyClick(editor, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(editor.selectedText(), "renamed")
        self.assertEqual(len(self.window.filmstrip.selectedItems()), 1)
        QTest.keyClick(editor, Qt.Key.Key_Return)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            self.app.processEvents()
            if any(pair.display_path.stem == "renamed" for pair in self.window.pairs):
                break
            QTest.qWait(20)
        renamed = next(pair for pair in self.window.pairs if pair.display_path.stem == "renamed")
        self.assertIn(renamed.key, self.window.kept)
        self.assertEqual(self.window._current_pair().display_path, renamed.display_path)
        self.assertFalse(pair.display_path.exists())
        self.assertEqual(self.window.store.data["photo_decisions"][
            self.window.store.photo_path_key(pair.display_path)], "")

    def test_inline_rename_escape_does_not_change_files(self):
        pair = self.window.visible[0]
        self.window._rename_photo_group((pair,))
        self.app.processEvents()
        editor = self.window.filmstrip.findChild(QLineEdit, "photoNameEditor")
        editor.setText("cancelled")
        with patch.object(self.window.photo_file_loader, "load") as load:
            QTest.keyClick(editor, Qt.Key.Key_Escape)
            self.app.processEvents()
            load.assert_not_called()
        self.assertNotEqual(self.window.filmstrip.state(), self.window.filmstrip.State.EditingState)
        self.assertTrue(pair.display_path.exists())
        self.assertFalse(pair.display_path.with_name("cancelled.jpg").exists())
