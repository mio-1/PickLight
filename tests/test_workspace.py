"""Regression coverage for the newer folder and canvas workflows."""

import os
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from unittest.mock import patch

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QSize, QTimer, Qt
from PySide6.QtGui import QColor, QCursor, QIcon, QImage, QImageReader, QMouseEvent, QPainter, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QStyle, QStyleOptionViewItem, QWidgetAction

from picklight.folder_dialogs import DeleteFolderDialog, MoveFolderConfirmation, MoveFolderDialog
from picklight.folder_menu import FolderColorRow, FolderIconPicker
from picklight.library import PhotoPair
from picklight.metadata import read_pair_rating, write_pair_rating
from picklight.paths import asset_path
from picklight.preview import decode
from picklight.theme import STYLE
from picklight.ui.folders import ProjectListDelegate, ProjectTree
from picklight.ui.graphics import folder_tree_icon
from picklight.ui.cursors import cursor_pixmap
from picklight.viewer import LoupeCanvas
from picklight.window import MainWindow


class WorkspaceRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.previous_stylesheet = cls.app.styleSheet()
        cls.app.setStyleSheet(STYLE)

    @classmethod
    def tearDownClass(cls):
        cls.app.setStyleSheet(cls.previous_stylesheet)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.environment = patch.dict(os.environ, {"PICKLIGHT_SETTINGS": str(self.root / "settings.json")})
        self.environment.start()
        self.window = MainWindow()
        self.window.resize(1400, 900)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        try:
            self.window.close()
            self.app.processEvents()
        finally:
            self.environment.stop()
            self.directory.cleanup()

    def source(self):
        source = self.root / "Photos"
        source.mkdir()
        image = QImage(60, 90, QImage.Format.Format_RGB32)
        image.fill("#405e72")
        self.assertTrue(image.save(str(source / "photo.JPG"), "JPEG"))
        self.assertTrue(self.window.open_project(source))
        return source

    def test_folder_heading_collapses_and_restores_tree(self):
        parent = self.window.store.add_folder("Parent")
        self.window.store.add_folder("Child", parent["id"])
        self.window._refresh_project_list()
        self.window._open_unbound_folder(parent)
        self.app.processEvents()
        filter_y = self.window.folder_filter_edit.mapTo(
            self.window.browser_panel, self.window.folder_filter_edit.rect().topLeft()).y()
        label = self.window.project_header_label
        pill = self.window.project_header_pill
        position = label.mapTo(pill, label.rect().center())
        QTest.mouseClick(pill, Qt.MouseButton.LeftButton, pos=position)
        self.app.processEvents()
        self.assertTrue(self.window.project_list.isHidden())
        self.window._set_folder_header_pill_hover(False)
        self.assertFalse(self.window.project_header_arrow.isHidden())
        self.assertEqual(self.window.folder_filter_edit.mapTo(
            self.window.browser_panel, self.window.folder_filter_edit.rect().topLeft()).y(), filter_y)
        self.window.close()
        self.window = MainWindow()
        self.window.show()
        self.app.processEvents()
        self.assertTrue(self.window.project_list.isHidden())
        QTest.mouseClick(self.window.project_header_pill, Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertFalse(self.window.project_list.isHidden())
        self.assertEqual(self.window.project_list.topLevelItemCount(), 1)
        self.assertTrue(self.window._project_items[parent["id"]].isExpanded())
        self.window._set_folder_header_pill_hover(False)
        self.assertTrue(self.window.project_header_arrow.isHidden())

    def test_photo_palette_follows_selection_and_reuses_cached_colors(self):
        folder = self.root / "Palette"
        folder.mkdir()
        for name, main, accent in (("A", "#ff0000", "#0000ff"),
                                   ("B", "#00ff00", "#ffff00")):
            image = QImage(100, 80, QImage.Format.Format_RGB32)
            image.fill(QColor(main))
            painter = QPainter(image)
            painter.fillRect(75, 0, 25, 80, QColor(accent))
            painter.end()
            self.assertTrue(image.save(str(folder / f"{name}.JPG"), "JPEG"))
        original = {path: path.read_bytes() for path in folder.iterdir()}
        self.window.open_project(folder)

        # Establish the initial source snapshot before testing cache reuse;
        # first discovery legitimately invalidates the pre-snapshot previews.
        monitor = self.window.source_monitor
        monitor.debounce.stop()
        monitor.scan()
        deadline = time.monotonic() + 5
        while monitor._busy and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertFalse(monitor._busy)

        def wait_for_colors(channel):
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                self.app.processEvents()
                colors = self.window.palette_strip.colors
                if colors and colors[0].rgb[channel] > 230:
                    return colors
                QTest.qWait(10)
            self.fail("selected photo palette was not displayed")

        first = wait_for_colors(0)
        self.assertTrue(self.window.palette_strip.isVisible())
        self.window.filmstrip.setCurrentRow(1)
        second = wait_for_colors(1)
        self.assertNotEqual(first, second)
        self.window.filmstrip.setCurrentRow(0)
        self.assertEqual(self.window.palette_strip.colors, first)
        self.window._show_loupe()
        QTest.mouseClick(self.window.palette_strip, Qt.MouseButton.LeftButton, pos=QPoint(15, 14))
        self.assertEqual(self.window.filters.color_rgb, first[0].rgb)
        self.assertEqual(self.window.palette_strip.selected_color, first[0].rgb)
        self.assertTrue(self.window.filter_button.isChecked())
        self.assertTrue(self.window.filter_bar.isVisible())
        self.assertEqual(self.window.center_stack.currentIndex(), 0)
        deadline = time.monotonic() + 5
        while self.window.color_index_busy and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(10)
        self.assertEqual([pair.display_path.stem for pair in self.window.visible], ["A"])
        self.window.filter_clear_button.click()
        self.assertIsNone(self.window.palette_strip.selected_color)
        self.assertEqual(len(self.window.visible), 2)
        self.assertEqual({path: path.read_bytes() for path in folder.iterdir()}, original)

    def test_scrolled_grid_keeps_filter_gap_and_left_aligned_inspector(self):
        folder = self.root / "Scroll"
        folder.mkdir()
        image = QImage(40, 60, QImage.Format.Format_RGB32)
        image.fill("#357390")
        for index in range(12):
            self.assertTrue(image.save(str(folder / f"{index:02}.JPG"), "JPEG"))
        self.window.open_project(folder)
        self.window.filter_button.click()
        self.app.processEvents()
        grid = self.window.filmstrip
        rating = self.window.quick_facet_buttons["rating"]
        lower_edge = rating.mapTo(self.window, QPoint(0, rating.height())).y()
        viewport_top = grid.viewport().mapTo(self.window, QPoint()).y()
        self.assertGreaterEqual(viewport_top - lower_edge, 8)
        bar = grid.verticalScrollBar()
        self.assertGreater(bar.maximum(), 0)
        bar.setValue(bar.maximum() // 2)
        self.app.processEvents()
        self.assertGreater(bar.value(), 0)
        self.assertEqual(grid.viewport().mapTo(self.window, QPoint()).y(), viewport_top)
        values = (self.window.dimensions_label, self.window.camera_label, self.window.iso_label)
        self.assertTrue(all(value.alignment() & Qt.AlignmentFlag.AlignLeft for value in values))
        columns = {value.mapTo(self.window.inspector, QPoint()).x() for value in values}
        columns.add(self.window.inspector_stars.mapTo(self.window.inspector, QPoint()).x())
        self.assertEqual(len(columns), 1)
        self.assertTrue(self.window.source_path_link.folder_label.alignment() & Qt.AlignmentFlag.AlignLeft)

    def test_color_and_rating_filter_combination_updates_counts_and_empty_state(self):
        folder = self.root / "Colors"
        folder.mkdir()
        for name, color in (("A", "#ff0000"), ("B", "#0000ff"), ("C", "#00ff00")):
            image = QImage(80, 60, QImage.Format.Format_RGB32)
            image.fill(QColor(color))
            self.assertTrue(image.save(str(folder / f"{name}.JPG"), "JPEG"))
        original = {path: path.read_bytes() for path in folder.iterdir()}
        self.window.open_project(folder)
        self.window.ratings = {pair.key: {"A": 4, "B": 3, "C": 0}[pair.display_path.stem]
                               for pair in self.window.pairs}
        self.window._apply_filter()
        self.window.rating_buttons[4].click()
        self.window.rating_buttons[3].click()
        self.assertEqual(len(self.window.visible), 2)
        self.assertEqual(self.window.quick_facet_buttons["rating"].text(), "4,3")
        self.assertEqual(self.window.filter_badge.text(), "2")
        self.assertEqual(self.window.unrated_button.count, 1)
        self.window.color_filter_panel.presets["#FF2727"].click()
        deadline = time.monotonic() + 5
        while self.window.color_index_busy and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(10)
        self.assertFalse(self.window.color_index_busy)
        self.assertEqual([pair.display_path.stem for pair in self.window.visible], ["A"])
        self.assertEqual(self.window.filter_badge.text(), "3")
        self.assertEqual(self.window.rating_buttons[3].count, 0)
        self.window.color_filter_panel.choose("#00FF00")
        self.assertEqual(self.window.visible, [])
        self.assertEqual(self.window.empty_title.text(), "没有找到相关文件")
        self.assertFalse(self.window.empty_search_art.isHidden())
        self.assertIn("搜索结果 (0)", self.window.file_label.text())
        self.window.unrated_button.click()
        self.assertEqual([pair.display_path.stem for pair in self.window.visible], ["C"])
        token = self.window.color_index_token
        self.window.filter_clear_button.click()
        self.assertEqual(len(self.window.visible), 3)
        self.assertIsNone(self.window.color_filter_button.color)
        empty = self.window.store.add_folder("Empty")
        self.window._open_unbound_folder(empty)
        self.window._color_index_ready(token, {"old.JPG": []})
        self.assertEqual(self.window.color_palettes, {})
        self.assertEqual({path: path.read_bytes() for path in folder.iterdir()}, original)

    def test_folder_color_updates_tree_but_keeps_picker_neutral(self):
        project = self.window.store.add_folder("Color")
        self.window._refresh_project_list()
        self.window._open_unbound_folder(project)
        menu = self.window._build_folder_menu(project["id"])
        self.addCleanup(menu.deleteLater)
        colors = next(action.defaultWidget() for action in menu.actions()
                      if isinstance(action, QWidgetAction)
                      and isinstance(action.defaultWidget(), FolderColorRow))
        submenu = next(action.menu() for action in menu.actions() if action.menu())
        picker = next(action.defaultWidget() for action in submenu.actions()
                      if isinstance(action, QWidgetAction)
                      and isinstance(action.defaultWidget(), FolderIconPicker))

        def assert_icon_color(icon, color):
            image = icon.pixmap(20, 20).toImage()
            # Raster outlines can remain antialiased at every pixel; sample the
            # strongest coverage rather than requiring an opaque SVG interior.
            actual = max((image.pixelColor(x, y) for x in range(image.width())
                          for y in range(image.height())), key=lambda pixel: pixel.alpha())
            self.assertGreater(actual.alpha(), 100)
            expected = QColor(color)
            for channel in ("red", "green", "blue"):
                self.assertLessEqual(abs(getattr(actual, channel)() - getattr(expected, channel)()), 1)

        for color in ("#ff453a", "#30d159", ""):
            menu.popup(self.window.project_header.mapToGlobal(
                self.window.project_header.rect().bottomLeft()))
            self.app.processEvents()
            QTest.mouseClick(colors.buttons[color], Qt.MouseButton.LeftButton)
            self.app.processEvents()
            self.assertEqual(self.window.store.project_by_id(project["id"])["color"], color)
            self.assertEqual(sum(button.isChecked() for button in colors.buttons.values()), 1)
            item = self.window._project_items[project["id"]]
            self.assertEqual(item.data(0, Qt.ItemDataRole.UserRole + 5), color)
            from picklight.themes import theme_manager
            expected = color or theme_manager().active.manifest.get("style", {}).get(
                "icons", {}).get("folder", "#d2d3d5")
            assert_icon_color(folder_tree_icon(False, False, "", color), expected)
            assert_icon_color(picker.buttons["camera"].icon(), "#d2d3d5")
            assert_icon_color(picker.reset_button.icon(), "#d2d3d5")
        self.window._set_folder_appearance(project["id"], color="#ff453a")
        self.window._set_folder_appearance(project["id"], icon="camera")
        self.window.close()
        self.window = MainWindow()
        self.assertEqual(self.window.store.project_by_id(project["id"])["color"], "#ff453a")
        self.assertEqual(self.window._project_items[project["id"]].data(
            0, Qt.ItemDataRole.UserRole + 4), "camera")

    def test_hovering_folder_colors_dismisses_icon_submenu(self):
        project = self.window.store.add_folder("Appearance")
        self.window._refresh_project_list()
        menu = self.window._build_folder_menu(project["id"])
        self.addCleanup(menu.deleteLater)
        self.addCleanup(menu.close)
        icon_action = next(action for action in menu.actions() if action.menu())
        submenu = icon_action.menu()
        colors = next(action.defaultWidget() for action in menu.actions()
                      if isinstance(action, QWidgetAction)
                      and isinstance(action.defaultWidget(), FolderColorRow))
        menu.popup(self.window.mapToGlobal(QPoint(50, 100)))
        self.app.processEvents()
        def hover_menu(target, point):
            QTest.mouseMove(target, point)
            # Native Windows may withhold OS hover messages from a background test.
            # Deliver the same Qt input explicitly while keeping the real cursor aligned.
            self.app.sendEvent(target, QMouseEvent(
                QEvent.Type.MouseMove, QPointF(point), QPointF(target.mapToGlobal(point)),
                Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
        hover_menu(menu, menu.actionGeometry(icon_action).center())
        QTest.qWait(500)
        self.assertTrue(submenu.isVisible())
        picker = next(action.defaultWidget() for action in submenu.actions()
                      if isinstance(action, QWidgetAction))
        hover_menu(submenu, picker.buttons["camera"].mapTo(submenu, QPoint(12, 12)))
        self.app.processEvents()
        self.assertTrue(submenu.isVisible())
        color_button = colors.buttons["#00aaff"]
        hover_menu(menu, color_button.mapTo(menu, QPoint(8, 11)))
        QTest.qWait(500)
        self.assertFalse(submenu.isVisible())
        self.assertTrue(menu.isVisible())
        QTest.mouseClick(color_button, Qt.MouseButton.LeftButton, pos=QPoint(8, 11))
        self.assertEqual(self.window.store.project_by_id(project["id"])["color"], "#00aaff")

    def test_rating_write_waits_for_active_jpeg_decoder(self):
        source = self.source()
        photo = source / "photo.JPG"
        started, release = Event(), Event()

        class DelayedReader:
            def __init__(self, path):
                self.reader = QImageReader(path)

            def __getattr__(self, name):
                return getattr(self.reader, name)

            def read(self):
                image = self.reader.read()
                started.set()
                if not release.wait(5):
                    raise TimeoutError("decoder was not released")
                return image

        pair = PhotoPair("photo", photo, None)
        with ThreadPoolExecutor(max_workers=2) as pool, patch(
                "picklight.preview.QImageReader", DelayedReader):
            decoded = pool.submit(decode, photo, 100)
            try:
                self.assertTrue(started.wait(3))
                writing = pool.submit(write_pair_rating, pair, 4)
                self.assertFalse(writing.done())
            finally:
                release.set()
            self.assertFalse(decoded.result(timeout=5).isNull())
            writing.result(timeout=5)
        self.assertEqual(read_pair_rating(pair), 4)

    def test_folder_move_and_removal_preserve_source_files(self):
        empty = self.window.store.add_folder("Empty")
        self.window._refresh_project_list()
        with patch("picklight.folders.DeleteFolderDialog") as confirmation:
            self.window._remove_project_item(self.window._project_items[empty["id"]])
            confirmation.assert_not_called()
        source = self.source()
        original = (source / "photo.JPG").read_bytes()
        source_id = self.window.project_id
        child = self.window.store.add_folder("Child", source_id)
        destination = self.window.store.add_folder("Archive")
        self.window._refresh_project_list()
        tree = ProjectTree()
        tree.setItemDelegate(ProjectListDelegate(tree))
        picker = MoveFolderDialog(self.window.store.projects(), source_id, tree, self.window)
        self.addCleanup(picker.deleteLater)
        for key in (source_id, child["id"]):
            self.assertFalse(picker.items[key].flags() & Qt.ItemFlag.ItemIsEnabled)
        picker.search.setText("Archive")
        self.assertFalse(picker.items[destination["id"]].isHidden())
        self.assertTrue(picker.items[source_id].isHidden())

        def choose_target(dialog):
            dialog.selected_parent_id = destination["id"]
            return QDialog.DialogCode.Accepted

        with patch.object(MoveFolderDialog, "exec", choose_target):
            self.window._move_folder(source_id)
        self.assertEqual(self.window.store.project_by_id(source_id)["parent_id"], destination["id"])
        with patch.object(DeleteFolderDialog, "exec", return_value=QDialog.DialogCode.Rejected):
            self.window._remove_project_item(self.window._project_items[source_id])
        self.assertIsNotNone(self.window.store.project_by_id(source_id))
        with patch.object(DeleteFolderDialog, "exec", return_value=QDialog.DialogCode.Accepted):
            self.window._remove_project_item(self.window._project_items[source_id])
        self.assertIsNone(self.window.store.project_by_id(child["id"]))
        self.assertEqual((source / "photo.JPG").read_bytes(), original)
        self.window.folder_delete_toast.undo_button.click()
        self.assertIsNotNone(self.window.store.project_by_id(child["id"]))
        self.assertEqual(self.window.store.project_by_id(source_id)["parent_id"], destination["id"])

    def test_unsupported_folder_move_is_ignored_without_warning(self):
        source = self.window.store.add_folder("Source")
        child = self.window.store.add_folder("Child", source["id"])
        self.window._refresh_project_list()
        original = [(p["id"], p.get("parent_id")) for p in self.window.store.projects()]
        with patch("picklight.folders.QMessageBox.warning") as warning:
            self.window._project_tree_moved([(source["id"], child["id"]),
                                             (child["id"], source["id"])])
            def choose_unsupported_target(dialog):
                dialog.selected_parent_id = child["id"]
                return QDialog.DialogCode.Accepted
            with patch.object(MoveFolderDialog, "exec", choose_unsupported_target):
                self.window._move_folder(source["id"])
            warning.assert_not_called()
        self.assertEqual([(p["id"], p.get("parent_id")) for p in self.window.store.projects()], original)

    def test_folder_drag_preserves_expansion_and_offsets_compact_preview(self):
        source = self.window.store.add_folder("Source")
        child = self.window.store.add_folder("Child", source["id"])
        grandchild = self.window.store.add_folder("Grandchild", child["id"])
        target = self.window.store.add_folder("Target")
        sibling = self.window.store.add_folder("Existing", target["id"])
        self.window._refresh_project_list()
        self.window._open_unbound_folder(source)
        tree = self.window.project_list
        self.window._project_items[source["id"]].setExpanded(True)
        self.window._project_items[child["id"]].setExpanded(False)
        self.window._project_items[target["id"]].setExpanded(False)
        before = tree.folder_expansion_state()
        for accepted in (False, True):
            tree.startDrag(Qt.DropAction.MoveAction)
            self.assertTrue(tree._folder_drag_active)
            preview = tree._drag_preview
            self.assertIsNotNone(preview)
            self.assertEqual(preview.pos(), QCursor.pos() + QPoint(12, 14))
            self.assertEqual(preview.height(), 24)
            self.assertLessEqual(preview.width(), 180)
            self.window._project_items[source["id"]].setExpanded(False)
            self.window._project_items[child["id"]].setExpanded(True)
            self.window._project_items[target["id"]].setExpanded(True)
            rect = tree.visualItemRect(self.window._project_items[target["id"]])
            tree.finish_folder_drag(QPoint(rect.left() + 40, rect.center().y()), cancel=not accepted)
            self.assertIsNone(tree._drag_preview)
            self.assertEqual(tree.folder_expansion_state(), before)
            self.assertIn(child["id"], self.window.store.data["collapsed_folder_ids"])
            self.assertIn(target["id"], self.window.store.data["collapsed_folder_ids"])
        self.assertEqual(self.window.store.project_by_id(source["id"])["parent_id"], target["id"])
        self.assertEqual(self.window.inspector.minimumWidth(), 265)

    def test_folder_drag_keeps_event_loop_running_and_commits_on_release(self):
        source = self.window.store.add_folder("Source")
        child = self.window.store.add_folder("Child", source["id"])
        target = self.window.store.add_folder("Target")
        self.window._refresh_project_list()
        self.window._open_unbound_folder(source)
        tree = self.window.project_list
        self.app.processEvents()
        before = tree.folder_expansion_state()
        source_rect = tree.visualItemRect(self.window._project_items[source["id"]])
        target_rect = tree.visualItemRect(self.window._project_items[target["id"]])
        start = QPoint(source_rect.left() + 40, source_rect.center().y())
        destination = QPoint(target_rect.left() + 40, target_rect.center().y())
        QTest.mousePress(tree.viewport(), Qt.MouseButton.LeftButton, pos=start)
        move = QMouseEvent(QEvent.Type.MouseMove, QPointF(destination),
                           QPointF(tree.viewport().mapToGlobal(destination)),
                           Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(tree.viewport(), move)
        self.assertTrue(tree._folder_drag_active)
        self.assertEqual(self.window.project_id, source["id"])
        self.assertIsNone(self.window.store.project_by_id(source["id"])["parent_id"])
        delivered = []
        QTimer.singleShot(0, lambda: delivered.append(True))
        self.app.processEvents()
        self.assertEqual(delivered, [True])
        QTest.mouseRelease(tree.viewport(), Qt.MouseButton.LeftButton, pos=destination)
        self.assertEqual(self.window.store.project_by_id(source["id"])["parent_id"], target["id"])
        self.assertEqual(self.window.store.project_by_id(child["id"])["parent_id"], source["id"])
        self.assertEqual(tree.folder_expansion_state(), before)
        self.assertFalse(tree._folder_drag_active)
        self.assertIsNone(tree._drag_preview)

    def test_move_picker_selects_insertions_and_confirms_folder_targets(self):
        source = self.window.store.add_folder("Source")
        child = self.window.store.add_folder("Child", source["id"])
        parent = self.window.store.add_folder("Parent")
        first = self.window.store.add_folder("First", parent["id"])
        second = self.window.store.add_folder("Second", parent["id"])
        for relation in ("before", "after", "inside"):
            tree = ProjectTree()
            tree.setItemDelegate(ProjectListDelegate(tree))
            picker = MoveFolderDialog(self.window.store.projects(), source["id"], tree, self.window)
            picker.show()
            self.app.processEvents()
            self.assertEqual(tree.topLevelItemCount(), 2)
            target = picker.items[first["id"]]
            rect = tree.visualItemRect(target)
            point = QPoint(rect.left() + 45, rect.top() + 1 if relation == "before" else
                           rect.bottom() - 1 if relation == "after" else rect.center().y())
            self.assertEqual(tree.destination_at(point), (target, relation))
            move = QMouseEvent(QEvent.Type.MouseMove, QPointF(point),
                               QPointF(tree.viewport().mapToGlobal(point)),
                               Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                               Qt.KeyboardModifier.NoModifier)
            QApplication.sendEvent(tree.viewport(), move)
            if relation != "inside":
                self.assertTrue(tree._insertion_target.isValid())
            if relation == "before":
                with patch.object(MoveFolderConfirmation, "exec", return_value=QDialog.DialogCode.Rejected):
                    QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=point)
                self.assertTrue(picker.isVisible())
                self.assertIsNone(picker.selected_target_id)
            with patch.object(MoveFolderConfirmation, "exec", return_value=QDialog.DialogCode.Accepted):
                QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=point)
            self.assertEqual(picker.result(), QDialog.DialogCode.Accepted)
            self.assertEqual(picker.selected_relation, relation)
            self.assertEqual(picker.selected_parent_id, first["id"] if relation == "inside" else parent["id"])
            picker.deleteLater()
        self.window.store.move_project(source["id"], parent["id"], before_id=first["id"])
        self.assertEqual([p["id"] for p in self.window.store.projects()
                          if p.get("parent_id") == parent["id"]], [source["id"], first["id"], second["id"]])
        self.window.store.move_project(source["id"], parent["id"], after_id=second["id"])
        self.assertEqual([p["id"] for p in self.window.store.projects()
                          if p.get("parent_id") == parent["id"]], [first["id"], second["id"], source["id"]])
        self.window.store.move_project(source["id"], None, before_id=parent["id"])
        self.assertEqual(self.window.store.projects()[0]["id"], source["id"])
        self.assertEqual(self.window.store.project_by_id(child["id"])["parent_id"], source["id"])
        with self.assertRaises(ValueError):
            self.window.store.move_project(source["id"], child["id"])

    def test_internal_folder_drag_orders_siblings_and_ignores_invalid_destinations(self):
        source = self.window.store.add_folder("Source")
        child = self.window.store.add_folder("Child", source["id"])
        target = self.window.store.add_folder("Target")
        self.window._refresh_project_list()
        self.window._open_unbound_folder(source)
        self.app.processEvents()
        tree = self.window.project_list
        for relation in ("after", "before"):
            tree.startDrag(Qt.DropAction.MoveAction)
            rect = tree.visualItemRect(self.window._project_items[target["id"]])
            point = QPoint(rect.left() + 40, rect.bottom() - 1 if relation == "after" else rect.top() + 1)
            tree.finish_folder_drag(point)
            roots = [p["id"] for p in self.window.store.projects() if not p.get("parent_id")]
            self.assertEqual(roots, [target["id"], source["id"]] if relation == "after"
                             else [source["id"], target["id"]])
        original = [(p["id"], p.get("parent_id")) for p in self.window.store.projects()]
        for point in (tree.visualItemRect(self.window._project_items[child["id"]]).center(), QPoint(-5, -5)):
            tree.startDrag(Qt.DropAction.MoveAction)
            tree._update_folder_drag(point)
            self.assertIsNone(tree._drag_destination)
            self.assertEqual(tree.viewport().cursor().pixmap().deviceIndependentSize().width(), 20)
            tree.finish_folder_drag(point)
            self.assertEqual([(p["id"], p.get("parent_id")) for p in self.window.store.projects()], original)
        tree.startDrag(Qt.DropAction.MoveAction)
        QTest.keyClick(tree, Qt.Key.Key_Escape)
        self.assertFalse(tree._folder_drag_active)




    def test_canvas_zoom_anchor_rotation_and_limits(self):
        canvas = LoupeCanvas()
        self.addCleanup(canvas.close)
        canvas.resize(800, 600)
        image = QImage(400, 600, QImage.Format.Format_RGB32)
        image.fill("#405e72")
        canvas.begin_image("first", QSize(4000, 6000))
        canvas.set_image(image)
        QApplication.sendEvent(canvas, QMouseEvent(QEvent.Type.MouseMove, QPointF(400, 300),
                              QPointF(canvas.mapToGlobal(QPoint(400, 300))),
                              Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
        self.assertFalse(canvas.cursor().pixmap().isNull())
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(400, 300))
        self.assertTrue(canvas._dragging)
        self.assertFalse(canvas.cursor().pixmap().isNull())
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(400, 300))
        self.assertFalse(canvas._dragging)
        canvas.set_zoom(0.001)
        self.assertEqual(canvas.zoom, 0.05)
        canvas.set_zoom(20)
        self.assertEqual(canvas.zoom, 8)
        canvas.set_zoom(0.2)
        anchor = QPointF(230, 180)
        before = (anchor - canvas.image_rect().topLeft()) / canvas.zoom
        canvas.set_zoom(0.3, anchor)
        after = (anchor - canvas.image_rect().topLeft()) / canvas.zoom
        self.assertLess((before - after).manhattanLength(), 0.0001)
        rectangle = canvas.image_rect()
        canvas.rotate_clockwise()
        self.assertEqual(canvas.image_rect().width(), rectangle.height())
        self.assertEqual(canvas.image_rect().height(), rectangle.width())
        for _ in range(3):
            canvas.rotate_clockwise()
        self.assertEqual(canvas.rotation, 0)
        canvas.fit_to_canvas()
        canvas.rotate_clockwise()
        self.assertEqual(canvas.zoom, canvas.fit_zoom())
        canvas.begin_image("next")
        self.assertEqual(canvas.rotation, 0)

    def test_loupe_rating_shortcuts_and_photo_decisions_persist_across_views(self):
        source = self.source()
        pair = self.window.pairs[0]
        self.window._show_loupe()
        self.window.activateWindow()
        self.window.preview_canvas.setFocus()
        self.app.processEvents()
        for stars in range(1, 6):
            QTest.keyClick(self.window.preview_canvas, getattr(Qt.Key, f"Key_{stars}"))
            self.assertEqual(self.window.ratings[pair.key], stars)
            self.assertEqual(read_pair_rating(pair), stars)
            self.assertEqual(self.window.center_stack.currentIndex(), 1)
        self.window.keep_flag_button.click()
        self.assertIn(pair.key, self.window.kept)
        self.assertEqual(self.window.preview_canvas.decision_state, "keep")
        self.assertEqual(self.window.filmstrip.item(0).data(Qt.ItemDataRole.UserRole + 7), "keep")
        self.window.reject_flag_button.click()
        self.assertNotIn(pair.key, self.window.kept)
        self.assertIn(pair.key, self.window.marked)
        self.assertEqual(self.window.inspector_preview.decision_state, "reject")
        self.window._open_sidebar_view("marked")
        self.assertEqual(len(self.window.visible), 1)
        self.assertTrue(self.window.sidebar_nav["marked"].active)
        self.assertEqual(self.window.sidebar_nav["marked"].count, 1)
        collection_key = self.window.current_key
        self.window.keep_flag_button.click()
        self.assertEqual(self.window.visible, [])
        self.assertIn(collection_key, self.window.kept)
        self.assertEqual(self.window.sidebar_nav["marked"].count, 0)
        self.window.open_project(source)
        self.assertIn(pair.key, self.window.kept)
        self.assertNotIn(pair.key, self.window.marked)
        self.assertTrue(self.window.keep_flag_button.isChecked())
        self.window.keep_flag_button.click()
        self.assertNotIn(pair.key, self.window.kept)
        self.assertFalse(self.window.keep_flag_button.isChecked())

    def test_rejected_thumbnail_dims_and_recovers_on_hover_and_cursor_dpi(self):
        self.source()
        self.window.reject_flag_button.click()
        grid = self.window.filmstrip
        item = grid.item(0)
        photo = QPixmap(80, 100)
        photo.fill(QColor("#94a4b4"))
        item.setIcon(QIcon(photo))
        item.setData(Qt.ItemDataRole.UserRole + 4, QSize(200, 250))
        colors = []
        for hovered in (False, True):
            image = QImage(220, 310, QImage.Format.Format_RGB32)
            image.fill(QColor("#18191c"))
            option = QStyleOptionViewItem()
            option.rect = QRect(0, 0, 210, 300)
            option.state = QStyle.StateFlag.State_Enabled
            if hovered:
                option.state |= QStyle.StateFlag.State_MouseOver
            painter = QPainter(image)
            grid.itemDelegate().paint(painter, option, grid.model().index(0, 0))
            painter.end()
            colors.append(image.pixelColor(100, 100))
            self.assertTrue(any(image.pixelColor(x, y).red() > image.pixelColor(x, y).green() * 1.3
                                for x in range(12, 30) for y in range(230, 252)))
        self.assertGreater(colors[1].red(), colors[0].red() * 2)
        self.window._open_sidebar_view("marked")
        self.assertFalse(grid.dim_rejected)
        item = grid.item(0)
        item.setIcon(QIcon(photo))
        item.setData(Qt.ItemDataRole.UserRole + 4, QSize(200, 250))
        image = QImage(220, 310, QImage.Format.Format_RGB32)
        image.fill(QColor("#18191c"))
        option.state = QStyle.StateFlag.State_Enabled
        painter = QPainter(image)
        grid.itemDelegate().paint(painter, option, grid.model().index(0, 0))
        painter.end()
        self.assertEqual(image.pixelColor(100, 100), colors[1])
        for ratio in (1, 1.5, 2):
            for key, size in (("cursor.grab", 24), ("cursor.grabbing", 24),
                              ("cursor.drag.move", 20)):
                pixmap = cursor_pixmap(key, size, ratio)
                self.assertEqual(pixmap.size(), QSize(round(size * ratio), round(size * ratio)))
                self.assertEqual(pixmap.deviceIndependentSize().width(), size)

    def test_pending_filter_keeps_decisions_consistent_for_overlapping_sources(self):
        root = self.root / "library"
        source = root / "nested"
        source.mkdir(parents=True)
        image = QImage(64, 96, QImage.Format.Format_RGB32)
        image.fill("#405e72")
        image.save(str(source / "photo.JPG"), "JPEG")
        self.window.open_project(root)
        self.window.open_project(source)
        self.window.reject_flag_button.click()
        self.window._open_sidebar_view("marked")
        self.assertEqual(len(self.window.visible), 1)
        self.assertEqual(self.window.visible[0].display_path, source / "photo.JPG")
        self.window.keep_flag_button.click()
        self.window.open_project(root)
        self.assertEqual(len(self.window.kept), 1)
        self.assertEqual(self.window.marked, set())
        self.window.keep_flag_button.click()
        self.window.open_project(source)
        self.assertEqual(self.window.kept, set())
        self.assertEqual(self.window.marked, set())

    def test_status_filter_combines_choices_and_rating_then_clears(self):
        source = self.root / "Status photos"
        source.mkdir()
        image = QImage(64, 96, QImage.Format.Format_RGB32)
        image.fill("#405e72")
        for name in ("A", "B", "C"):
            image.save(str(source / f"{name}.JPG"), "JPEG")
        self.window.open_project(source)
        self.window.keep_flag_button.click()
        self.window.filmstrip.setCurrentRow(1)
        self.window.reject_flag_button.click()
        self.window.ratings = {pair.key: 3 if pair.display_path.stem == "C" else 4
                               for pair in self.window.pairs}
        self.window._apply_filter()
        self.assertFalse(hasattr(self.window, "batch_strip"))
        rows = self.window.status_facet.rows
        self.assertEqual({state: row.count for state, row in rows.items()},
                         {"keep": 1, "reject": 1, "none": 1})
        rows["keep"].click()
        self.assertEqual([p.display_path.stem for p in self.window.visible], ["A"])
        rows["reject"].click()
        self.assertEqual([p.display_path.stem for p in self.window.visible], ["A", "B"])
        self.window.rating_buttons[4].click()
        self.assertEqual(rows["none"].count, 0)
        rows["keep"].click()
        self.assertEqual([p.display_path.stem for p in self.window.visible], ["B"])
        rows["reject"].click()
        rows["none"].click()
        self.assertEqual(self.window.visible, [])
        self.assertFalse(self.window.filter_clear_button.isHidden())
        self.window.filter_clear_button.click()
        self.assertEqual(len(self.window.visible), 3)
        self.assertEqual(self.window.filters.states, set())
        rows["none"].click()
        self.assertEqual([p.display_path.stem for p in self.window.visible], ["C"])
        self.window.filter_clear_button.click()
        self.window.filmstrip.setCurrentRow(1)
        self.window.reject_flag_button.click()
        self.assertFalse(self.window.reject_flag_button.isChecked())
        self.assertEqual(self.window.marked, set())

    def test_photo_shortcuts_work_without_the_old_hidden_controls(self):
        self.source()
        self.window._show_loupe()
        self.window.activateWindow()
        self.window.preview_canvas.setFocus()
        QTest.qWait(20)
        QTest.keyClick(self.window.preview_canvas, Qt.Key.Key_4)
        self.assertEqual(read_pair_rating(self.window._current_pair()), 4)
        QTest.keyClick(self.window.preview_canvas, Qt.Key.Key_0)
        self.assertEqual(read_pair_rating(self.window._current_pair()), 0)
        QTest.keyClick(self.window.preview_canvas, Qt.Key.Key_Delete)
        self.assertIn(self.window.current_key, self.window.marked)
        QTest.keyClick(self.window.preview_canvas, Qt.Key.Key_Delete)
        self.assertNotIn(self.window.current_key, self.window.marked)
        QTest.keyClick(self.window.preview_canvas, Qt.Key.Key_F11)
        self.assertTrue(self.window.isFullScreen())
        QTest.keyClick(self.window.preview_canvas, Qt.Key.Key_F11)
        self.assertFalse(self.window.isFullScreen())

    def test_sidebar_rejected_view_shares_the_editable_status_filter(self):
        source = self.source()
        image = QImage(64, 96, QImage.Format.Format_RGB32)
        image.fill("#405e72")
        image.save(str(source / "other.JPG"), "JPEG")
        self.window.open_project(source)
        self.window.reject_flag_button.click()
        rejected_path = self.window._current_pair().display_path
        self.window.sidebar_nav["marked"].click()
        self.assertEqual(self.window.filters.states, {"reject"})
        self.assertEqual(self.window.filter_badge.text(), "1")
        self.assertEqual([pair.display_path for pair in self.window.visible], [rejected_path])
        self.assertTrue(self.window.status_facet.rows["reject"].isChecked())
        self.assertFalse(self.window.filter_bar.isHidden())
        self.assertEqual(self.window.quick_facet_buttons["status"].text(), "待删除")
        self.window.status_facet.rows["none"].click()
        self.assertEqual(len(self.window.visible), len(self.window.pairs))
        self.window.quick_facet_buttons["status"].clear_button.click()
        self.assertEqual(self.window.filters.states, set())
        self.assertEqual(len(self.window.visible), len(self.window.pairs))
        self.window.sidebar_nav["marked"].click()
        self.window.sidebar_nav["all"].click()
        self.assertFalse(self.window.status_facet.rows["reject"].isChecked())
        self.assertEqual(self.window.quick_facet_buttons["status"].text(), "状态")

    def test_facet_clear_buttons_only_clear_their_own_condition(self):
        self.source()
        filters = self.window.filters
        filters.rating_values = {3, 4}
        filters.states = {"keep"}
        filters.color_rgb = (40, 90, 150)
        self.window._update_visual_facets()
        rating_button = self.window.quick_facet_buttons["rating"]
        self.assertFalse(rating_button.clear_button.isHidden())
        rating_button.clear_button.click()
        self.assertEqual(filters.rating_values, set())
        self.assertEqual(filters.states, {"keep"})
        self.assertEqual(filters.color_rgb, (40, 90, 150))
        self.assertTrue(rating_button.clear_button.isHidden())
        self.assertFalse(rating_button.menu().isVisible())
        self.window.quick_facet_buttons["status"].clear_button.click()
        self.assertEqual(filters.states, set())
        self.assertEqual(filters.color_rgb, (40, 90, 150))
        self.window.color_filter_button.clear_button.click()
        self.assertIsNone(filters.color_rgb)
        self.assertFalse(filters.color_gray)
        self.assertFalse(self.window.color_filter_panel.delay.isActive())

    def test_source_and_frozen_resource_roots(self):
        self.assertTrue(Path(asset_path("picklight.ico")).is_file())
        self.assertTrue(Path(asset_path("folder.icons.index")).is_file())
        with patch("picklight.paths.sys._MEIPASS", str(self.root), create=True):
            self.assertEqual(Path(asset_path("example.svg")), self.root / "assets" / "example.svg")


if __name__ == "__main__":
    unittest.main()
