"""Global range/toggle/rubber-band selection and the shared inspector."""

import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QImage, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from picklight.window import MainWindow


class MultiSelectionTests(unittest.TestCase):
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
        source = self.root / "photos"
        source.mkdir()
        image = QImage(60, 40, QImage.Format.Format_RGB32)
        image.fill("#337766")
        for index in range(8):
            image.save(str(source / f"{index}.jpg"))
        self.window = MainWindow(restore_project=False)
        self.addCleanup(self.window.close)
        self.window.show()
        self.window.open_project(source)
        self.app.processEvents()
        self.window._resize_grid()

    def click(self, row, modifiers=Qt.KeyboardModifier.NoModifier):
        grid = self.window.filmstrip
        QTest.mouseClick(grid.viewport(), Qt.MouseButton.LeftButton, modifiers,
                         grid.visualItemRect(grid.item(row)).center())

    def test_shift_ctrl_and_single_selection_switch_right_inspector(self):
        w = self.window
        self.assertFalse(w.filters.active)
        self.click(0)
        self.click(3, Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(len(w.filmstrip.selectedItems()), 4)
        self.assertFalse(w.findChildren(QPushButton, "filterDeleteButton"))
        self.assertIs(w.inspector_stack.currentWidget(), w.multi_inspector)
        self.assertEqual(w.multi_selection_count.text(),
                         '已选 <span style="color: #3297ff">4</span> 组图片，'
                         '<span style="color: #3297ff">4</span> 个文件')
        self.click(6, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(len(w.filmstrip.selectedItems()), 5)
        self.click(2, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(len(w.filmstrip.selectedItems()), 4)
        self.click(1)
        self.assertEqual(len(w.filmstrip.selectedItems()), 1)
        self.assertIs(w.inspector_stack.currentWidget(), w.inspector_scroll)
        w.filmstrip.clearSelection()

    def test_blank_area_drag_selects_in_photo_viewport(self):
        grid = self.window.filmstrip
        viewport = grid.viewport()
        start = QPoint(viewport.width() - 2, 1)
        finish = QPoint(2, grid.visualItemRect(grid.item(5)).bottom() - 2)
        QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=start)
        event = QMouseEvent(QEvent.Type.MouseMove, QPointF(finish), QPointF(viewport.mapToGlobal(finish)),
                            Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(viewport, event)
        QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=finish)
        self.assertGreaterEqual(len(grid.selectedItems()), 3)
        self.assertIs(self.window.inspector_stack.currentWidget(), self.window.multi_inspector)

    def test_batch_rating_touches_only_selected_pairs_and_preserves_selection(self):
        w = self.window
        self.click(0)
        self.click(2, Qt.KeyboardModifier.ControlModifier)
        selected = {pair.key for pair in w._selected_photo_pairs()}
        with patch("picklight.multi_selection.write_pair_rating") as write:
            QTest.mouseClick(w.multi_selection_stars, Qt.MouseButton.LeftButton, pos=QPoint(65, 10))
            deadline = time.monotonic() + 4
            while w.batch_rating_loader.busy and time.monotonic() < deadline:
                QTest.qWait(5)
            self.assertFalse(w.batch_rating_loader.busy)
        self.assertEqual({call.args[0].key for call in write.call_args_list}, selected)
        self.assertEqual({pair.key for pair in w._selected_photo_pairs()}, selected)
        self.assertTrue(all(w.ratings[key] == 4 for key in selected))
        self.assertEqual(w.multi_selection_stars.rating, 4)

    def test_shared_rating_displays_only_when_every_selected_pair_agrees(self):
        w = self.window
        self.click(0)
        self.click(2, Qt.KeyboardModifier.ShiftModifier)
        pairs = w._selected_photo_pairs()
        for pair, stars in zip(pairs, (4, 4, 3)):
            w.ratings[pair.key] = stars
        w._on_photo_selection_changed()
        self.assertEqual(w.multi_selection_stars.rating, 0)
        for pair in pairs:
            w.ratings[pair.key] = 4
        w._on_photo_selection_changed()
        self.assertEqual(w.multi_selection_stars.rating, 4)
        w.multi_info_heading.click()
        self.assertTrue(w.multi_info_body.isHidden())
        w.multi_info_heading.click()
        self.assertFalse(w.multi_info_body.isHidden())

    def test_ctrl_additions_stack_in_click_order_and_finish_the_drop(self):
        w = self.window
        self.click(0)
        for row in (4, 2, 5, 1):
            self.click(row, Qt.KeyboardModifier.ControlModifier)
            path = w.filmstrip.item(row).data(Qt.ItemDataRole.UserRole + 6)
            self.assertEqual(w.multi_preview.paths[-1], path)
            self.assertEqual(w.multi_preview.incoming, path)
        self.assertEqual(len(w.multi_preview.paths), 5)
        QTest.qWait(320)
        self.app.processEvents()
        self.assertIsNone(w.multi_preview.incoming)
        self.assertEqual(w.multi_preview.drop_progress, 1.0)

    def test_changing_source_does_not_select_unrelated_same_named_photos(self):
        self.click(0)
        self.click(2, Qt.KeyboardModifier.ControlModifier)
        other = self.root / "another-source"
        other.mkdir()
        for path in (self.root / "photos").glob("*.jpg"):
            (other / path.name).write_bytes(path.read_bytes())
        self.window.open_project(other)
        self.assertLessEqual(len(self.window.filmstrip.selectedItems()), 1)
        self.assertIsNot(self.window.inspector_stack.currentWidget(), self.window.multi_inspector)

    def test_ctrl_a_selects_current_results_and_leaves_text_input_alone(self):
        w = self.window
        w.activateWindow()
        w.filmstrip.setFocus()
        self.app.processEvents()
        QTest.keyClick(w.filmstrip, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(len(w.filmstrip.selectedItems()), 8)
        self.assertEqual(len(w.multi_preview.paths), 8)
        self.assertIs(w.inspector_stack.currentWidget(), w.multi_inspector)
        w._search_photos("0.jpg")
        w.filmstrip.setFocus()
        QTest.keyClick(w.filmstrip, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual([item.text() for item in w.filmstrip.selectedItems()], ["0.jpg"])
        w.search_edit.setFocus()
        self.app.processEvents()
        QTest.keyClick(w.search_edit, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(w.search_edit.selectedText(), "0.jpg")
        self.assertEqual(len(w.filmstrip.selectedItems()), 1)
        w.filmstrip.clearSelection()
        w.zoom_slider.setFocus()
        QTest.keyClick(w.zoom_slider, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(len(w.filmstrip.selectedItems()), 1)
        w.store.data["shortcuts"] = {"photo.select_all": "Ctrl+L"}
        w._refresh_shortcuts()
        w.filmstrip.clearSelection()
        w.filmstrip.setFocus()
        QTest.keyClick(w.filmstrip, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        self.assertFalse(w.filmstrip.selectedItems())
        QTest.keyClick(w.filmstrip, Qt.Key.Key_L, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(len(w.filmstrip.selectedItems()), 1)
