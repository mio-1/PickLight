"""Exercise the visible culling flow without opening native windows."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt, QPoint, QPointF, QEvent
from PySide6.QtGui import QImage, QMouseEvent, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QMenu

from picklight.window import MainWindow
from picklight.ui.toolbar import GalleryZoomSlider, SearchScopeButton, ToolbarSearchEdit
from picklight.ui.inspector import InspectorSectionButton, PhotoCanvas, StarRatingControl
from picklight.ui.graphics import oriented_jpeg_size
from picklight.metadata import _run_exiftool, read_pair_rating
from picklight.theme import STYLE


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.previous_stylesheet = cls.app.styleSheet()
        cls.app.setStyleSheet(STYLE)

    @classmethod
    def tearDownClass(cls):
        cls.app.setStyleSheet(cls.previous_stylesheet)

    def setUp(self):
        self._previous_windows = {id(widget) for widget in self.app.topLevelWidgets()}
        self.addCleanup(self._close_test_windows)

    def _close_test_windows(self):
        for widget in self.app.topLevelWidgets():
            if (isinstance(widget, MainWindow) and id(widget) not in self._previous_windows
                    and not widget.loader.closed):
                widget.close()

    def test_main_menu_shows_color_management_about_and_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            previous = os.environ.get("PICKLIGHT_SETTINGS")
            os.environ["PICKLIGHT_SETTINGS"] = str(Path(directory) / "settings.json")
            try:
                window = MainWindow(restore_project=False)
                window.show()
                self.app.processEvents()
                self.assertEqual(
                    [action.text() for action in window.main_menu.actions()
                     if not action.isSeparator() and action.isVisible()],
                    ["色彩管理", "偏好设置…", "关于 PickLight", "退出"])
                self.assertFalse(window.check_update_action.isVisible())
                self.assertEqual(window.main_menu.width(), 190)
                window.menu_button.click()
                self.app.processEvents()
                self.assertTrue(window.main_menu.isVisible())
                self.assertEqual(window.main_menu.pos(), window.menu_button.mapToGlobal(
                    QPoint(window.menu_button.width() - 2, 10)))
                window.main_menu.hide()
                with patch("picklight.update_dialog.UpdateDialog.exec") as updates:
                    window.check_update_action.trigger()
                    updates.assert_called_once()
                with patch("picklight.about_dialog.AboutDialog.exec") as about:
                    window.about_action.trigger()
                    about.assert_called_once()
                window.close()
            finally:
                if previous is None:
                    os.environ.pop("PICKLIGHT_SETTINGS", None)
                else:
                    os.environ["PICKLIGHT_SETTINGS"] = previous

    def test_search_scope_magnifier_highlights_on_hover(self):
        button = SearchScopeButton()
        button.show()
        self.app.processEvents()
        QApplication.sendEvent(button, QEvent(QEvent.Type.Leave))
        self.app.processEvents()
        normal = button.grab().toImage()
        QApplication.sendEvent(button, QEvent(QEvent.Type.Enter))
        self.app.processEvents()
        hovered = button.grab().toImage()
        self.assertTrue(button._hover)
        self.assertEqual(normal.pixel(1, 14), hovered.pixel(1, 14))
        self.assertNotEqual(normal.pixel(5, 14), hovered.pixel(5, 14))
        clicked = []
        button.clicked.connect(lambda: clicked.append(True))
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        self.assertEqual(clicked, [True])
        QApplication.sendEvent(button, QEvent(QEvent.Type.Leave))
        self.assertFalse(button._hover)
        button.close()

    def test_search_scope_button_clears_text_focus(self):
        edit = ToolbarSearchEdit()
        edit.scope_menu = QMenu(edit)
        edit.scope_menu.addAction("名称")
        edit.show()
        edit.activateWindow()
        edit.setFocus()
        self.app.processEvents()
        self.assertTrue(edit.hasFocus())
        edit.scope_button.click()
        self.assertFalse(edit.hasFocus())
        self.assertEqual(edit.scope_menu.pos(), edit.scope_button.mapToGlobal(
            QPoint(edit.scope_button.width() - 8,
                   edit.scope_button.height() - 3)))
        edit.scope_menu.close()
        self.app.processEvents()
        self.assertFalse(edit.hasFocus())
        edit.close()

    def test_inspector_arrow_appears_on_hover_or_when_collapsed(self):
        button = InspectorSectionButton("基本信息")
        button.resize(240, 30)
        button.show()
        self.app.processEvents()

        def arrow_pixels():
            image = button.grab().toImage()
            return tuple(image.pixel(x, y) for x in range(218, 240) for y in range(30))

        button._hovered = False
        button.update()
        self.app.processEvents()
        expanded = arrow_pixels()
        button._hovered = True
        button.update()
        self.app.processEvents()
        hovered = arrow_pixels()
        button._hovered = False
        button.setChecked(False)
        button.update()
        self.app.processEvents()
        collapsed = arrow_pixels()
        self.assertNotEqual(expanded, hovered)
        self.assertNotEqual(expanded, collapsed)
        button.close()

    def test_window_shape_clips_native_backdrop_to_the_rounded_outline(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
                "PICKLIGHT_SETTINGS": str(Path(directory) / "settings.json")}):
            window = MainWindow(restore_project=False)
            try:
                window.show()
                self.app.processEvents()
                for width in (1360, 1200):
                    window.resize(width, 800)
                    self.app.processEvents()
                    surface = window.centralWidget()
                    self.assertEqual(window.mask(), surface.mask())
                    for point in (QPoint(0, 0), QPoint(width - 1, 0),
                                  QPoint(0, 799), QPoint(width - 1, 799)):
                        self.assertFalse(window.mask().contains(point))
                    self.assertTrue(window.mask().contains(QPoint(width // 2, 1)))
                    self.assertTrue(window.mask().contains(QPoint(1, 400)))
                window.showMaximized()
                self.app.processEvents()
                self.assertTrue(window.mask().isEmpty())
                window.showNormal()
                self.app.processEvents()
                self.assertFalse(window.mask().isEmpty())
            finally:
                window.close()

    def test_window_border_drag_resizes_and_respects_minimum(self):
        with tempfile.TemporaryDirectory() as directory:
            previous = os.environ.get("PICKLIGHT_SETTINGS")
            os.environ["PICKLIGHT_SETTINGS"] = str(Path(directory) / "settings.json")
            try:
                window = MainWindow()
                window.resize(1200, 800)
                window.move(100, 100)
                window.show()
                self.app.processEvents()
                surface = window.centralWidget()
                self.assertIs(surface.childAt(QPoint(2, 400)), surface.resize_handles["left"])
                self.assertEqual(surface.resize_handles["left"].cursor().shape(),
                                 Qt.CursorShape.SizeHorCursor)
                self.assertIs(surface.childAt(QPoint(600, 2)), surface.resize_handles["top"])
                self.assertEqual(surface.resize_handles["top"].cursor().shape(),
                                 Qt.CursorShape.SizeVerCursor)
                self.assertEqual(surface.resize_handles["bottom_right"].cursor().shape(),
                                 Qt.CursorShape.SizeFDiagCursor)

                def mouse(kind, global_point, buttons):
                    local = window.mapFromGlobal(global_point)
                    return QMouseEvent(kind, QPointF(local), QPointF(global_point),
                                       Qt.MouseButton.LeftButton, buttons,
                                       Qt.KeyboardModifier.NoModifier)

                start = window.mapToGlobal(QPoint(window.width() - 3, window.height() - 3))
                self.assertTrue(window.eventFilter(window, mouse(
                    QEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton)))
                self.assertTrue(window.eventFilter(window, mouse(
                    QEvent.Type.MouseMove, start + QPoint(80, 60), Qt.MouseButton.LeftButton)))
                self.assertEqual(window.size().width(), 1280)
                self.assertEqual(window.size().height(), 860)
                window.eventFilter(window, mouse(
                    QEvent.Type.MouseButtonRelease, start + QPoint(80, 60), Qt.MouseButton.NoButton))
                start = window.mapToGlobal(QPoint(2, 300))
                window.eventFilter(window, mouse(
                    QEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton))
                window.eventFilter(window, mouse(
                    QEvent.Type.MouseMove, start + QPoint(1000, 0), Qt.MouseButton.LeftButton))
                self.assertEqual(window.width(), window.minimumWidth())
                window.eventFilter(window, mouse(
                    QEvent.Type.MouseButtonRelease, start + QPoint(1000, 0), Qt.MouseButton.NoButton))
                window.close()
            finally:
                self._close_test_windows()
                if previous is None:
                    os.environ.pop("PICKLIGHT_SETTINGS", None)
                else:
                    os.environ["PICKLIGHT_SETTINGS"] = previous

    def test_clicking_current_star_rating_clears_it(self):
        stars = StarRatingControl()
        selected = []
        stars.ratingSelected.connect(selected.append)
        stars.set_rating(3)
        QTest.mouseClick(stars, Qt.MouseButton.LeftButton, pos=QPoint(60, 14))
        self.assertEqual(selected, [0])
        QTest.mouseClick(stars, Qt.MouseButton.LeftButton, pos=QPoint(84, 14))
        self.assertEqual(selected, [0, 4])

    def test_zoom_slider_clicks_at_any_position(self):
        slider = GalleryZoomSlider(Qt.Orientation.Horizontal)
        slider.setRange(160, 460)
        slider.setValue(160)
        slider.resize(112, 24)
        slider.show()
        QTest.mouseClick(slider, Qt.MouseButton.LeftButton, pos=QPoint(83, 12))
        self.assertGreater(slider.value(), 360)
        QTest.mouseClick(slider, Qt.MouseButton.LeftButton, pos=QPoint(42, 12))
        self.assertLess(slider.value(), 300)
        slider.close()

    def test_arrangement_menu_switches_between_waterfall_and_grid(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            photos = root / "photos"
            photos.mkdir()
            for index in range(6):
                image = QImage(60 if index % 2 == 0 else 90,
                               90 if index % 2 == 0 else 60,
                               QImage.Format.Format_RGB32)
                image.fill("#526e7d")
                self.assertTrue(image.save(str(photos / f"{index:02}.JPG"), "JPEG"))
            previous = os.environ.get("PICKLIGHT_SETTINGS")
            os.environ["PICKLIGHT_SETTINGS"] = str(root / "settings.json")
            try:
                window = MainWindow()
                window.resize(1020, 620)
                window.open_project(photos)
                window.show()
                self.app.processEvents()
                window.grid_button.click()
                self.app.processEvents()
                self.assertEqual(window.arrangement_menu.y(), window.grid_button.mapToGlobal(
                    QPoint(window.grid_button.width() - 1,
                           window.grid_button.height() - 1)).y())
                window.arrangement_menu.hide()
                self.assertEqual(window.search_edit.clear_button.iconSize().width(), 12)
                first_photo = window.filmstrip.item(0)
                copy_drag = window.filmstrip._create_copy_drag(first_photo)
                self.assertIsNotNone(copy_drag)
                self.assertEqual(Path(copy_drag.mimeData().urls()[0].toLocalFile()),
                                 photos / "00.JPG")
                self.assertEqual(len(list(photos.iterdir())), 6)
                copy_drag.deleteLater()
                self.app.processEvents()
                window.filmstrip.setCurrentRow(4)
                self.assertEqual(window.gallery_layout, "waterfall")
                waterfall_heights = [window.filmstrip.item(row).data(
                    Qt.ItemDataRole.UserRole + 4).height() for row in (0, 1)]
                self.assertNotEqual(*waterfall_heights)
                window.arrangement_actions["grid"].trigger()
                self.app.processEvents()
                self.assertEqual(window.gallery_layout, "grid")
                self.assertEqual(window.arrangement_menu.actions()[0].defaultWidget()
                                 .findChild(QLabel, "searchScopeHeading").text(), "布局模式:")
                self.assertTrue(window.arrangement_rows["grid"].isChecked())
                self.assertFalse(window.arrangement_rows["waterfall"].isChecked())
                self.assertEqual(window.filmstrip.currentRow(), 4)
                self.assertGreaterEqual(window.filmstrip.visualItemRect(
                    window.filmstrip.item(3)).top(), window.filmstrip.visualItemRect(
                        window.filmstrip.item(2)).top())
                self.assertEqual(window.filmstrip.item(0).data(Qt.ItemDataRole.UserRole + 4),
                                 window.filmstrip.item(1).data(Qt.ItemDataRole.UserRole + 4))
                self.assertEqual(window.store.data["gallery_layout"], "grid")
                window.arrangement_rows["waterfall"].click()
                self.app.processEvents()
                self.assertEqual(window.gallery_layout, "waterfall")
                self.assertTrue(window.arrangement_rows["waterfall"].isChecked())
                self.assertEqual(window.filmstrip.currentRow(), 4)
                # With the narrower sidebar, keep this viewport below the
                # two-column 460px threshold so the last zoom crosses a column.
                window.resize(1400, 900)
                self.app.processEvents()
                window.zoom_slider.setValue(340)
                first_width = window.filmstrip.item(0).data(
                    Qt.ItemDataRole.UserRole + 4).width()
                first_position = window.filmstrip.visualItemRect(window.filmstrip.item(0)).topLeft()
                window.zoom_slider.setValue(350)
                second_width = window.filmstrip.item(0).data(
                    Qt.ItemDataRole.UserRole + 4).width()
                self.assertEqual(second_width, first_width)
                self.assertEqual(window.filmstrip.visualItemRect(
                    window.filmstrip.item(0)).topLeft(), first_position)
                window.zoom_slider.setValue(460)
                self.assertGreater(window.filmstrip.item(0).data(
                    Qt.ItemDataRole.UserRole + 4).width(), second_width)
                window.close()
            finally:
                self._close_test_windows()
                if previous is None:
                    os.environ.pop("PICKLIGHT_SETTINGS", None)
                else:
                    os.environ["PICKLIGHT_SETTINGS"] = previous

    def test_right_preview_keeps_photo_corner_pixels(self):
        canvas = PhotoCanvas(inspector=True)
        canvas.resize(244, 298)
        image = QImage(244, 298, QImage.Format.Format_RGB32)
        image.fill("#2040ff")
        for x in range(image.width() - 7, image.width()):
            for y in range(image.height()):
                image.setPixelColor(x, y, "#ff2020")
        canvas.set_image(image)
        canvas.show()
        self.app.processEvents()
        target = canvas.image_rect()
        rendered = canvas.grab().toImage()
        for y in (target.top() + 1.5, target.center().y(), target.bottom() - 1.5):
            pixel = rendered.pixelColor(
                round((target.right() - 1.5) * canvas.devicePixelRatioF()),
                round(y * canvas.devicePixelRatioF()))
            self.assertGreater(pixel.red(), 220)
            self.assertLess(pixel.blue(), 80)
        canvas.close()

    def test_oriented_jpg_keeps_its_visible_portrait_shape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "portrait.JPG"
            image = QImage(120, 80, QImage.Format.Format_RGB32)
            image.fill("#526e7d")
            self.assertTrue(image.save(str(path), "JPEG"))
            _run_exiftool(["-overwrite_original", "-EXIF:Orientation#=6", str(path)])
            self.assertEqual((oriented_jpeg_size(path).width(), oriented_jpeg_size(path).height()),
                             (80, 120))
            previous = os.environ.get("PICKLIGHT_SETTINGS")
            os.environ["PICKLIGHT_SETTINGS"] = str(root / "settings.json")
            try:
                window = MainWindow()
                window.open_project(root)
                window.show()
                self.app.processEvents()
                card = window.filmstrip.item(0).data(Qt.ItemDataRole.UserRole + 4)
                self.assertGreater(card.height(), card.width())
                self.assertEqual(window.inspector_preview.height(), 220)
                self.assertEqual(window.inspector_preview.image_rect().height(),
                                 window.inspector_preview.height())
                initial_name_y = window.info_name.y()
                window.raw_source_button.show()
                self.app.processEvents()
                control_positions = (window.jpg_source_button.pos(),
                                     window.raw_source_button.pos(),
                                     window.preview_expand_button.pos())
                self.assertIs(window.jpg_source_button.parent(), window.preview_controls)
                self.assertIs(window.raw_source_button.parent(), window.preview_controls)
                self.assertGreater(window.inspector_preview.y(),
                                   window.preview_controls.y() + window.preview_controls.height())
                for width, height in ((120, 80), (80, 120), (200, 30)):
                    preview = QImage(width, height, QImage.Format.Format_RGB32)
                    preview.fill("#526e7d")
                    window.inspector_preview.set_image(preview)
                    self.app.processEvents()
                    photo_rect = window.inspector_preview.image_rect()
                    self.assertEqual(window.inspector_preview.height(), 220)
                    self.assertEqual(window.info_name.y(), initial_name_y)
                    self.assertGreaterEqual(photo_rect.left(), 0)
                    self.assertLessEqual(photo_rect.right(), window.inspector_preview.width())
                    self.assertGreaterEqual(photo_rect.top(), 0)
                    self.assertLessEqual(photo_rect.bottom(), 220)
                    if height >= width:
                        self.assertEqual(photo_rect.height(), 220)
                    self.assertEqual((window.jpg_source_button.pos(),
                                      window.raw_source_button.pos(),
                                      window.preview_expand_button.pos()), control_positions)
                self.assertEqual(window.dimensions_label.text(), "80 × 120")
                window.edited_label.setText("Adobe Photoshop Lightroom Classic 15.4.1 (Windows)")
                landscape = QImage(120, 80, QImage.Format.Format_RGB32)
                landscape.fill("#526e7d")
                window.inspector_preview.set_image(landscape)
                self.app.processEvents()
                self.assertEqual(window.inspector_scroll.widget().width(),
                                 window.inspector_scroll.viewport().width())
                self.assertEqual(window.inspector_preview.image_rect().width(),
                                 window.inspector_preview.width())
                window.preview_expand_button.click()
                self.assertFalse(window.preview_expand_button.isEnabled())
                self.assertFalse(window.image_fit_button.isEnabled())
                self.assertEqual(window.center_stack.currentIndex(), 0)
                window.close()
            finally:
                self._close_test_windows()
                if previous is None:
                    os.environ.pop("PICKLIGHT_SETTINGS", None)
                else:
                    os.environ["PICKLIGHT_SETTINGS"] = previous

    def test_sidebar_collapses_and_restores_across_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = QImage(64, 48, QImage.Format.Format_RGB32)
            image.fill("#526e7d")
            self.assertTrue(image.save(str(root / "photo.JPG"), "JPEG"))
            previous = os.environ.get("PICKLIGHT_SETTINGS")
            os.environ["PICKLIGHT_SETTINGS"] = str(root / "settings.json")
            try:
                window = MainWindow()
                window.open_project(root)
                window.show()
                self.app.processEvents()
                self.assertTrue(window.sidebar_toggle.isVisible())
                expanded_width = window.browser_panel.width()
                viewer_width = window.viewer.width()
                inspector_width = window.inspector.width()
                window.sidebar_toggle.click()
                self.app.processEvents()
                self.assertFalse(window.browser_panel.isVisible())
                self.assertTrue(window.sidebar_toggle.isVisible())
                self.assertGreater(window.viewer.width(), viewer_width)
                self.assertAlmostEqual(window.inspector.width(), inspector_width, delta=2)
                window.close()

                reopened = MainWindow()
                reopened.open_project(root)
                reopened.show()
                self.app.processEvents()
                self.assertFalse(reopened.browser_panel.isVisible())
                self.assertTrue(reopened.sidebar_toggle.isVisible())
                self.assertAlmostEqual(reopened.inspector.width(), inspector_width, delta=2)
                reopened.sidebar_toggle.click()
                self.app.processEvents()
                self.assertTrue(reopened.browser_panel.isVisible())
                self.assertAlmostEqual(reopened.browser_panel.width(), expanded_width, delta=2)
                self.assertAlmostEqual(reopened.inspector.width(), inspector_width, delta=2)
                reopened.close()
            finally:
                self._close_test_windows()
                if previous is None:
                    os.environ.pop("PICKLIGHT_SETTINGS", None)
                else:
                    os.environ["PICKLIGHT_SETTINGS"] = previous

    def test_rating_filter_mark_and_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for number in range(3):
                name = f"DSC_{number:04}"
                image = QImage(64, 48, QImage.Format.Format_RGB32)
                image.fill("#526e7d")
                self.assertTrue(image.save(str(root / f"{name}.JPG"), "JPEG"))
                (root / f"{name}.ARW").write_bytes(b"raw placeholder")
            previous = os.environ.get("PICKLIGHT_SETTINGS")
            os.environ["PICKLIGHT_SETTINGS"] = str(root / "settings.json")
            try:
                window = MainWindow()
                window.open_project(root)
                window.show()
                self.app.processEvents()
                window.filter_button.click()
                self.app.processEvents()
                self.assertTrue(window.filter_bar.isVisible())
                QTest.mouseClick(window.unrated_button, Qt.MouseButton.LeftButton)
                self.app.processEvents()
                self.assertTrue(window.filter_bar.isVisible())
                self.assertEqual(window.filters.rating_values, {0})
                self.assertEqual(window.filter_badge.text(), "1")
                self.assertTrue(window.filter_badge.isVisible())
                self.assertEqual(window.filter_badge.width(), 13)
                window.filter_clear_button.click()
                self.assertFalse(window.filter_badge.isVisible())
                window.filter_button.click()
                self.assertFalse(window.filter_bar.isVisible())
                self.assertTrue(window.windowFlags() & Qt.WindowType.FramelessWindowHint)
                self.assertEqual(window.title_bar.height(), 44)
                self.assertEqual(window.menu_button.iconSize().width(), 16)
                self.assertEqual(window.minimize_button.size().width(), 40)
                self.assertLess(window.menu_button.x(), window.minimize_button.x())
                QTest.mouseDClick(window.title_bar, Qt.MouseButton.LeftButton, pos=QPoint(300, 20))
                self.assertTrue(window.isMaximized())
                QTest.mouseDClick(window.title_bar, Qt.MouseButton.LeftButton, pos=QPoint(300, 20))
                self.assertFalse(window.isMaximized())
                self.assertTrue(window.browser_panel.isVisible())
                window.resize(960, 620)
                self.app.processEvents()
                self.assertTrue(window.browser_panel.isVisible())
                self.assertEqual(window.viewer_toolbar.height(), 44)
                self.assertFalse(window.zoom_controls.isVisible())
                self.assertEqual(window.zoom_slider.width(), 64)
                self.assertFalse(hasattr(window, "loupe_button"))
                window.file_label.setText("非常长的文件夹名称" * 12)
                self.app.processEvents()
                self.assertLess(window.file_label.geometry().right(),
                                window.grid_button.mapTo(
                                    window.viewer_toolbar, QPoint(0, 0)).x())
                window._update_toolbar_folder_title()
                self.assertTrue(window.search_toggle.isVisible())
                window.search_popup.popup(window.search_toggle.mapToGlobal(QPoint(0, 30)))
                self.app.processEvents()
                window.compact_search_edit.setText("DSC_0001")
                self.assertEqual(window.filters.path_contains, "DSC_0001")
                self.assertEqual(window.search_edit.text(), "DSC_0001")
                self.assertEqual(len(window.visible), 1)
                window.search_scope_rows["name"].click()
                self.assertEqual(len(window.visible), 0)
                window.search_scope_rows["name"].click()
                self.assertEqual(len(window.visible), 1)
                window.search_popup.hide()
                window.compact_search_edit.clear()
                self.assertEqual(len(window.visible), 3)
                window.filmstrip.setCurrentRow(0)
                self.assertEqual(window.info_name.text(), "DSC_0000.JPG")
                self.assertTrue(window.jpg_source_button.isVisible())
                self.assertTrue(window.raw_source_button.isVisible())
                self.assertEqual(window.dimensions_label.text(), "64 × 48")
                self.assertEqual(window.type_label.text(), "JPG")
                self.assertEqual(list(window.inspector_sections),
                                 ["属性", "源文件", "相机", "曝光", "日期"])
                window.inspector_sections["源文件"].click()
                self.assertFalse(window.source_path_link.isVisible())
                window.inspector_sections["源文件"].click()
                self.assertTrue(window.source_path_link.isVisible())
                self.assertEqual(window.source_path_link.path.name, "DSC_0000.JPG")
                self.assertTrue(window.source_path_link.file_label.text().endswith(".JPG"))
                with patch("picklight.photos.QDesktopServices.openUrl") as open_folder:
                    QTest.mouseClick(window.source_path_link, Qt.MouseButton.LeftButton)
                    open_folder.assert_called_once()
                    self.assertEqual(Path(open_folder.call_args.args[0].toLocalFile()),
                                     window._current_preview_path().parent)
                window.reject_flag_button.click()
                self.assertIn(window.current_key, window.marked)
                self.assertTrue(window.reject_flag_button.isChecked())
                window.keep_flag_button.click()
                self.assertNotIn(window.current_key, window.marked)
                self.assertTrue(window.keep_flag_button.isChecked())
                window.resize(1450, 900)
                self.app.processEvents()
                self.assertTrue(window.browser_panel.isVisible())
                self.assertEqual(window.zoom_slider.width(), 88)
                self.assertTrue(window.search_edit.isVisible())
                window.file_label.setText("非常长的文件夹名称" * 12)
                self.app.processEvents()
                self.assertLess(window.file_label.geometry().right(),
                                window.zoom_controls.geometry().left())
                window._update_toolbar_folder_title()
                self.assertEqual(len(window.visible), 3)
                self.assertEqual(window.center_stack.currentIndex(), 0)
                window._show_loupe()
                self.assertEqual(window.center_stack.currentIndex(), 1)
                window._show_grid()
                self.assertEqual(window.center_stack.currentIndex(), 0)
                first_item = window.filmstrip.item(0)
                self.assertEqual(first_item.text(), "DSC_0000.JPG")
                self.assertEqual(first_item.sizeHint().height() - first_item.data(
                    Qt.ItemDataRole.UserRole + 4).height(), 48)
                QTest.mouseClick(window.inspector_stars, Qt.MouseButton.LeftButton, pos=QPoint(63, 12))
                self.assertEqual(read_pair_rating(window.visible[0]), 4)
                self.assertIs(window.filmstrip.item(0), first_item)
                self.assertEqual(first_item.data(Qt.ItemDataRole.UserRole + 1), 4)
                self.assertEqual(window.inspector_stars.rating, 4)
                window.raw_source_button.click()
                self.assertEqual(window.preview_source, "raw")
                self.assertEqual(window.info_name.text(), "DSC_0000.ARW")
                self.assertEqual(window.type_label.text(), "ARW")
                window._show_loupe()
                self.assertEqual(window._current_preview_path().suffix.upper(), ".ARW")
                self.assertEqual(window.file_label.text(), "1 / 3")
                window._show_grid()
                window.toggle_mark()
                self.assertEqual(len(window.marked), 1)
                window.move_selection(1)
                self.assertEqual(window.preview_source, "jpg")
                last_key = window.current_key
                window.close()

                reopened = MainWindow()
                reopened.open_project(root)
                self.assertEqual(reopened.current_key, last_key)
                self.assertEqual(len(reopened.marked), 1)
                self.assertFalse(reopened.browser_panel.isAncestorOf(reopened.filter_button))
                reopened.rating_buttons[4].click()
                self.assertEqual(len(reopened.visible), 1)
                self.assertEqual(reopened.rating_buttons[4].property("lit"), "true")
                self.assertEqual(reopened.file_label.text(), f"{root.name} / 搜索结果 (1)")
                self.assertEqual(reopened.file_label.toolTip(), "4 星")
                self.assertFalse(reopened.quick_facet_buttons["rating"].isHidden())
                reopened.filter_clear_button.click()
                self.assertEqual(len(reopened.visible), 3)
                self.assertFalse(reopened.quick_facet_buttons["rating"].isHidden())
                reopened.sidebar_nav["marked"].click()
                self.assertEqual(len(reopened.visible), 1)
                reopened.filter_clear_button.click()
                reopened.rating_buttons[4].click()
                self.assertEqual(len(reopened.visible), 1)
                reopened.filter_clear_button.click()
                reopened.rating_buttons[4].click()
                self.assertEqual(len(reopened.visible), 1)
                reopened.set_rating(3)
                self.assertEqual(len(reopened.visible), 0)
                reopened.close()
            finally:
                self._close_test_windows()
                if previous is None:
                    os.environ.pop("PICKLIGHT_SETTINGS", None)
                else:
                    os.environ["PICKLIGHT_SETTINGS"] = previous

    def test_project_list_switches_tasks_without_renaming_folders(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, second = root / "first", root / "second"
            first.mkdir()
            second.mkdir()
            for folder in (first, second):
                image = QImage(64, 48, QImage.Format.Format_RGB32)
                image.fill("#526e7d")
                self.assertTrue(image.save(str(folder / "photo.JPG"), "JPEG"))
            previous = os.environ.get("PICKLIGHT_SETTINGS")
            os.environ["PICKLIGHT_SETTINGS"] = str(root / "settings.json")
            try:
                window = MainWindow()
                window.open_project(first)
                first_id = window.project_id
                window.toggle_mark()
                window.open_project(second)
                self.assertEqual(window.file_label.text(), "second")
                self.assertTrue(window.folder_back_button.isEnabled())
                self.assertFalse(window.folder_forward_button.isEnabled())
                window.folder_back_button.click()
                self.assertEqual(window.project_folder, first.resolve())
                self.assertEqual(len(window.marked), 1)
                self.assertTrue(window.folder_forward_button.isEnabled())
                window.folder_forward_button.click()
                self.assertEqual(window.project_folder, second.resolve())
                self.assertEqual(window.project_list.topLevelItemCount(), 2)
                first_item = next(window.project_list.topLevelItem(row)
                                  for row in range(window.project_list.topLevelItemCount())
                                  if window.project_list.topLevelItem(row).data(0, Qt.ItemDataRole.UserRole) == first_id)
                window.project_list.setCurrentItem(first_item)
                self.app.processEvents()
                self.assertEqual(window.project_folder, first.resolve())
                self.assertEqual(len(window.marked), 1)
                selected = window.project_list.currentItem()
                with patch("picklight.folders.QInputDialog.getText", return_value=("春季拍摄", True)):
                    window._rename_project_item(selected)
                self.assertEqual(window.project_list.currentItem().text(0), "春季拍摄")
                self.assertTrue(first.is_dir())
                self.assertTrue((first / "photo.JPG").is_file())
                with patch("picklight.folders.DeleteFolderDialog.exec", return_value=1):
                    window._remove_project_item(window.project_list.currentItem())
                self.assertEqual(window.project_list.topLevelItemCount(), 1)
                self.assertEqual(window.project_folder, second.resolve())
                self.assertTrue((first / "photo.JPG").is_file())
                empty = root / "empty"
                empty.mkdir()
                window.open_project(empty)
                self.assertIs(window.center_stack.currentWidget(), window.empty_page)
                self.assertFalse(window.empty_folder_art.isHidden())
                window.arrangement_rows["grid"].click()
                self.app.processEvents()
                self.assertIs(window.center_stack.currentWidget(), window.empty_page)
                self.assertFalse(window.empty_folder_art.isHidden())
                self.assertEqual(window.gallery_layout, "grid")
                self.assertEqual(window.project_list.topLevelItemCount(), 2)
                window.close()
            finally:
                self._close_test_windows()
                if previous is None:
                    os.environ.pop("PICKLIGHT_SETTINGS", None)
                else:
                    os.environ["PICKLIGHT_SETTINGS"] = previous

    def test_folder_history_visits_virtual_folders_and_discards_forward_branch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, second = root / "first", root / "second"
            first.mkdir()
            second.mkdir()
            image = QImage(64, 48, QImage.Format.Format_RGB32)
            image.fill("#526e7d")
            for folder in (first, second):
                self.assertTrue(image.save(str(folder / "photo.JPG"), "JPEG"))
            previous = os.environ.get("PICKLIGHT_SETTINGS")
            os.environ["PICKLIGHT_SETTINGS"] = str(root / "settings.json")
            try:
                window = MainWindow()
                window.open_project(first)
                first_id = window.project_id
                virtual = window.store.add_folder("精选")
                window._refresh_project_list()
                window.project_list.setCurrentItem(window._project_items[virtual["id"]])
                self.assertEqual(window.project_id, virtual["id"])
                self.assertTrue(window.folder_back_button.isEnabled())
                window.folder_back_button.click()
                self.assertEqual(window.project_id, first_id)
                self.assertTrue(window.folder_forward_button.isEnabled())
                window.folder_forward_button.click()
                self.assertEqual(window.project_id, virtual["id"])
                self.assertIs(window.project_list.currentItem(),
                              window._project_items[virtual["id"]])
                window.folder_back_button.click()
                window.open_project(second)
                self.assertFalse(window.folder_forward_button.isEnabled())
                window.close()
            finally:
                self._close_test_windows()
                if previous is None:
                    os.environ.pop("PICKLIGHT_SETTINGS", None)
                else:
                    os.environ["PICKLIGHT_SETTINGS"] = previous

    def test_software_folder_can_bind_photo_directory_without_losing_its_name(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "camera"
            source.mkdir()
            image = QImage(64, 48, QImage.Format.Format_RGB32)
            image.fill("#526e7d")
            self.assertTrue(image.save(str(source / "photo.JPG"), "JPEG"))
            previous = os.environ.get("PICKLIGHT_SETTINGS")
            os.environ["PICKLIGHT_SETTINGS"] = str(root / "settings.json")
            try:
                window = MainWindow()
                folder = window.store.add_folder("婚礼精选")
                window._refresh_project_list()
                window.project_list.setCurrentItem(window._project_items[folder["id"]])
                self.assertEqual(window.project_id, folder["id"])
                self.assertIsNone(window.project_folder)
                window.close()

                reopened = MainWindow()
                self.assertEqual(reopened.project_id, folder["id"])
                self.assertIsNone(reopened.project_folder)
                self.assertTrue(reopened.open_project(source, bind_to_id=folder["id"]))
                self.assertEqual(reopened.project_id, folder["id"])
                self.assertEqual(reopened.store.project_by_id(folder["id"])["name"], "婚礼精选")
                self.assertEqual(reopened.store.project_by_id(folder["id"])["folder"],
                                 str(source.resolve()))
                self.assertEqual(len(reopened.visible), 1)
                self.assertTrue((source / "photo.JPG").is_file())
                reopened.close()
            finally:
                self._close_test_windows()
                if previous is None:
                    os.environ.pop("PICKLIGHT_SETTINGS", None)
                else:
                    os.environ["PICKLIGHT_SETTINGS"] = previous

    def test_virtual_folder_tree_restores_nested_layout_and_expansion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "camera_card"
            source.mkdir()
            image = QImage(64, 48, QImage.Format.Format_RGB32)
            image.fill("#526e7d")
            self.assertTrue(image.save(str(source / "photo.JPG"), "JPEG"))
            previous = os.environ.get("PICKLIGHT_SETTINGS")
            os.environ["PICKLIGHT_SETTINGS"] = str(root / "settings.json")
            try:
                window = MainWindow()
                window.open_project(source)
                imported_id = window.project_id
                archive = window.store.add_folder("归档")
                window.store.add_folder("去年", archive["id"])
                shoots = window.store.add_folder("拍摄任务")
                window.store.move_project(imported_id, shoots["id"])
                window._refresh_project_list()
                self.assertEqual(window._project_items[imported_id].parent().text(0), "拍摄任务")
                window._project_items[archive["id"]].setExpanded(False)
                self.assertFalse(window._project_items[archive["id"]].isExpanded())
                window.project_list.setCurrentItem(window._project_items[archive["id"]])
                self.assertEqual(window.project_id, archive["id"])
                self.assertIsNone(window.project_folder)
                self.assertEqual(window.file_label.text(), "归档")
                self.assertIs(window.inspector_stack.currentWidget(), window.folder_inspector)
                self.assertTrue((source / "photo.JPG").is_file())
                window.project_list.setCurrentItem(window._project_items[imported_id])
                window.close()

                reopened = MainWindow()
                reopened.open_project(source)
                self.assertEqual(reopened._project_items[imported_id].parent().text(0), "拍摄任务")
                self.assertFalse(reopened._project_items[archive["id"]].isExpanded())
                self.assertTrue(reopened._project_items[shoots["id"]].isExpanded())
                reopened.close()
            finally:
                self._close_test_windows()
                if previous is None:
                    os.environ.pop("PICKLIGHT_SETTINGS", None)
                else:
                    os.environ["PICKLIGHT_SETTINGS"] = previous

    def test_import_reads_nested_jpg_raw_without_creating_child_folder_nodes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "shoot"
            jpg_folder = source / "JPG"
            raw_folder = source / "RAW"
            jpg_folder.mkdir(parents=True)
            raw_folder.mkdir(parents=True)
            image = QImage(64, 48, QImage.Format.Format_RGB32)
            image.fill("#526e7d")
            self.assertTrue(image.save(str(jpg_folder / "A.JPG"), "JPEG"))
            (raw_folder / "A.ARW").write_bytes(b"raw placeholder")
            previous = os.environ.get("PICKLIGHT_SETTINGS")
            os.environ["PICKLIGHT_SETTINGS"] = str(root / "settings.json")
            try:
                window = MainWindow()
                self.assertTrue(window.open_project(source))
                self.assertEqual(len(window.pairs), 1)
                self.assertTrue(window.pairs[0].jpg and window.pairs[0].raw)
                self.assertEqual(window.project_list.topLevelItemCount(), 1)
                self.assertEqual(window.project_list.topLevelItem(0).childCount(), 0)
                self.assertEqual(window.project_header_label.text(), "文件夹 (1)")
                self.assertEqual({path.name for path in source.iterdir()}, {"JPG", "RAW"})
                window.close()
            finally:
                self._close_test_windows()
                if previous is None:
                    os.environ.pop("PICKLIGHT_SETTINGS", None)
                else:
                    os.environ["PICKLIGHT_SETTINGS"] = previous

    def test_folder_overview_shows_children_and_persists_details(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "JPG"
            source.mkdir()
            image = QImage(64, 48, QImage.Format.Format_RGB32)
            image.fill("#526e7d")
            self.assertTrue(image.save(str(source / "photo.JPG"), "JPEG"))
            previous = os.environ.get("PICKLIGHT_SETTINGS")
            os.environ["PICKLIGHT_SETTINGS"] = str(root / "settings.json")
            try:
                window = MainWindow()
                parent = window.store.add_folder("拍摄任务")
                child = window.store.add_project(source, parent["id"])
                window._refresh_project_list()
                window.show()
                window.project_list.setCurrentItem(window._project_items[parent["id"]])
                self.app.processEvents()
                self.assertIs(window.center_stack.currentWidget(), window.folder_page)
                self.assertLess(window.folder_children_heading.mapTo(
                    window.folder_page, QPoint(0, 0)).y(), 24)
                self.assertTrue(window.folder_children_heading.isChecked())
                self.assertTrue(window.folder_cards_container.isVisible())
                self.assertIs(window.inspector_stack.currentWidget(), window.folder_inspector)
                self.assertEqual(window.folder_children_heading.text(), "子文件夹 (1)")
                self.assertEqual(window.folder_inspector_count.text(), "0")
                description = "1234567890" * 12
                window.folder_inspector_description.setText(description)
                self.app.processEvents()
                self.assertGreater(window.folder_inspector_description.height(), 32)
                window.folder_inspector_description.setFocus()
                self.app.processEvents()
                window.folder_inspector_name.setFocus()
                self.app.processEvents()
                self.assertEqual(window.store.project_by_id(parent["id"])["description"], description)
                window.folder_inspector_name.setText("周末选图")
                window._save_folder_name()
                window.folder_inspector_description.setText("首轮筛选")
                window._save_folder_description()
                self.assertEqual(window.store.project_by_id(parent["id"])["name"], "周末选图")
                self.assertEqual(window.store.project_by_id(parent["id"])["description"], "首轮筛选")
                window._open_folder_card(child["id"])
                self.assertEqual(window.project_id, child["id"])
                self.assertIs(window.inspector_stack.currentWidget(), window.folder_inspector)
                self.assertEqual(window.folder_inspector_count.text(), "1")
                self.assertFalse(hasattr(window, "folder_inspector_binding"))
                self.assertTrue((source / "photo.JPG").is_file())
                window.close()
            finally:
                self._close_test_windows()
                if previous is None:
                    os.environ.pop("PICKLIGHT_SETTINGS", None)
                else:
                    os.environ["PICKLIGHT_SETTINGS"] = previous

    def test_mixed_folder_starts_collapsed_and_shows_linked_source_photos(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            child = source / "child"
            child.mkdir(parents=True)
            external = root / "external"
            external.mkdir()
            image = QImage(64, 48, QImage.Format.Format_RGB32)
            image.fill("#526e7d")
            self.assertTrue(image.save(str(source / "direct.jpg"), "JPEG"))
            self.assertTrue(image.save(str(child / "nested.jpg"), "JPEG"))
            self.assertTrue(image.save(str(external / "other.jpg"), "JPEG"))
            previous = os.environ.get("PICKLIGHT_SETTINGS")
            os.environ["PICKLIGHT_SETTINGS"] = str(root / "settings.json")
            try:
                window = MainWindow()
                window.show()
                self.assertTrue(window.open_project(source))
                window.store.add_project(child, window.project_id)
                window.store.add_project(external, window.project_id)
                window._show_folder_overview(window.store.project_by_id(window.project_id))
                self.assertFalse(window.folder_children_heading.isChecked())
                self.assertFalse(window.folder_cards_container.isVisible())
                self.assertTrue(window.folder_section.isVisible())
                self.assertTrue(window.filmstrip.isVisible())
                self.assertEqual(window.filmstrip.count(), 2)
                self.assertEqual(window.folder_inspector_count.text(), "2")
                self.assertEqual(window.folder_content_heading.text(), "内容 (2)")
                self.assertFalse(window.folder_content_heading.isVisible())
                window.folder_children_heading.setChecked(True)
                self.assertTrue(window.folder_cards_container.isVisible())
                self.assertTrue(window.folder_content_heading.isVisible())
                self.app.processEvents()
                for expanded in (False, True) * 4:
                    window.folder_children_heading.setChecked(expanded)
                    header_height = window.gallery_header.height()
                    first_top = window.filmstrip.visualItemRect(window.filmstrip.item(0)).top()
                    self.assertEqual(first_top + window.filmstrip.verticalScrollBar().value(),
                                     header_height)
                    self.app.processEvents()
                    self.assertEqual(window.gallery_header.height(), header_height)
                self.assertFalse(hasattr(window, "folder_include_children"))
                self.assertTrue(window.open_project(source))
                self.assertTrue(window.folder_section.isVisible())
                self.assertFalse(window.folder_children_heading.isChecked())
                self.assertFalse(window.folder_cards_container.isVisible())
                self.assertTrue(window.filmstrip.isVisible())
                self.assertEqual(window.filmstrip.count(), 2)
                self.assertFalse(window.folder_content_heading.isVisible())
                window.resize(1100, 650)
                window.zoom_slider.setValue(520)
                self.app.processEvents()
                window._resize_grid()
                bar = window.filmstrip.verticalScrollBar()
                before = window.filmstrip.visualItemRect(window.filmstrip.item(0)).y()
                distance = window.gallery_header.height() + 20
                self.assertGreater(bar.maximum(), distance)
                bar.setValue(distance)
                self.app.processEvents()
                self.assertEqual(window.gallery_header.y(), -bar.value())
                self.assertLess(window.gallery_header.geometry().bottom(), 0)
                self.assertLess(window.filmstrip.visualItemRect(
                    window.filmstrip.item(0)).y(), before)
                window.close()
            finally:
                self._close_test_windows()
                if previous is None:
                    os.environ.pop("PICKLIGHT_SETTINGS", None)
                else:
                    os.environ["PICKLIGHT_SETTINGS"] = previous

    def test_photo_only_folder_displays_grid_after_folder_only_view(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folders = root / "folders"
            child = folders / "child"
            child.mkdir(parents=True)
            photos = root / "photos"
            photos.mkdir()
            image = QImage(64, 48, QImage.Format.Format_RGB32)
            image.fill("#526e7d")
            self.assertTrue(image.save(str(photos / "direct.jpg"), "JPEG"))
            previous = os.environ.get("PICKLIGHT_SETTINGS")
            os.environ["PICKLIGHT_SETTINGS"] = str(root / "settings.json")
            try:
                window = MainWindow()
                window.show()
                self.assertTrue(window.open_project(folders))
                window.store.add_project(child, window.project_id)
                window._show_folder_overview(window.store.project_by_id(window.project_id))
                self.assertTrue(window.folder_section.isVisible())
                self.assertEqual(window.filmstrip.count(), 0)
                self.assertTrue(window.open_project(photos))
                self.assertFalse(window.folder_section.isVisible())
                self.assertFalse(window.folder_content_heading.isVisible())
                self.assertTrue(window.filmstrip.isVisible())
                self.assertEqual(window.filmstrip.count(), 1)
                window.close()
            finally:
                self._close_test_windows()
                if previous is None:
                    os.environ.pop("PICKLIGHT_SETTINGS", None)
                else:
                    os.environ["PICKLIGHT_SETTINGS"] = previous

    def test_folder_cards_scroll_without_photos(self):
        with tempfile.TemporaryDirectory() as directory:
            previous = os.environ.get("PICKLIGHT_SETTINGS")
            os.environ["PICKLIGHT_SETTINGS"] = str(Path(directory) / "settings.json")
            try:
                window = MainWindow(restore_project=False)
                parent = window.store.add_folder("分类")
                for index in range(18):
                    window.store.add_folder(f"子文件夹 {index}", parent["id"])
                window.resize(1100, 650)
                window.show()
                window._open_unbound_folder(parent)
                self.app.processEvents()
                window._resize_grid()
                self.assertEqual(window.filmstrip.count(), 0)
                self.assertTrue(window.folder_children_heading.isChecked())
                widths = []
                for zoom in (160, 180, 200, 220, 260, 320, 400, 460):
                    window.zoom_slider.setValue(zoom)
                    self.app.processEvents()
                    window._resize_grid()
                    widths.append(window._folder_cards[0].width())
                    rectangles = [card.geometry() for card in window._folder_cards]
                    self.assertFalse(any(first.intersects(second)
                                         for index, first in enumerate(rectangles)
                                         for second in rectangles[index + 1:]))
                self.assertEqual(len(set(widths)), 8)
                bar = window.filmstrip.verticalScrollBar()
                self.assertGreater(bar.maximum(), 180)
                for target in (window.folder_children_heading, window._folder_cards[0]):
                    bar.setValue(0)
                    wheel = QWheelEvent(QPointF(10, 10), QPointF(target.mapToGlobal(QPoint(10, 10))),
                                        QPoint(), QPoint(0, -120), Qt.MouseButton.NoButton,
                                        Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
                    QApplication.sendEvent(target, wheel)
                    QTest.qWait(50)
                    # A cold first paint can consume qWait's whole deadline;
                    # dispatch its overdue animation tick before inspecting it.
                    self.app.processEvents()
                    self.assertGreater(bar.value(), 0)
                    QTest.qWait(150)
                    self.assertLessEqual(bar.value(), 128)
                bar.setValue(180)
                self.app.processEvents()
                self.assertEqual(window.gallery_header.y(), -180)
                pixels = QWheelEvent(QPointF(10, 10), QPointF(target.mapToGlobal(QPoint(10, 10))),
                                     QPoint(0, -24), QPoint(), Qt.MouseButton.NoButton,
                                     Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.ScrollUpdate, False)
                QApplication.sendEvent(target, pixels)
                self.assertEqual(bar.value(), 204)
                self.assertEqual(window.gallery_header.y(), -204)
                window.close()
            finally:
                self._close_test_windows()
                if previous is None:
                    os.environ.pop("PICKLIGHT_SETTINGS", None)
                else:
                    os.environ["PICKLIGHT_SETTINGS"] = previous

    def test_folder_plus_creates_virtual_sibling_and_inline_rename(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "shoot"
            source.mkdir()
            previous = os.environ.get("PICKLIGHT_SETTINGS")
            os.environ["PICKLIGHT_SETTINGS"] = str(root / "settings.json")
            try:
                window = MainWindow()
                self.assertTrue(window.open_project(source))
                source_id = window.project_id
                window.project_add_button.click()
                sibling = window.project_list.currentItem()
                sibling_id = sibling.data(0, Qt.ItemDataRole.UserRole)
                self.assertEqual(sibling.text(0), "未命名文件夹")
                self.assertIsNone(window.store.project_by_id(sibling_id)["parent_id"])
                self.assertIsNone(sibling.parent())
                sibling.setText(0, "精选四星")
                self.assertEqual(window.store.project_by_id(sibling_id)["name"], "精选四星")
                self.assertEqual(window.folder_inspector_name.text(), "精选四星")
                group = window.store.add_folder("拍摄组")
                window.store.move_project(source_id, group["id"])
                window._refresh_project_list()
                window.project_list.setCurrentItem(window._project_items[source_id])
                window.project_add_button.click()
                nested_sibling = window.project_list.currentItem()
                nested_id = nested_sibling.data(0, Qt.ItemDataRole.UserRole)
                self.assertEqual(window.store.project_by_id(nested_id)["parent_id"], group["id"])
                self.assertIs(nested_sibling.parent(), window._project_items[group["id"]])
                self.assertEqual(list(source.iterdir()), [])
                window.close()
            finally:
                self._close_test_windows()
                if previous is None:
                    os.environ.pop("PICKLIGHT_SETTINGS", None)
                else:
                    os.environ["PICKLIGHT_SETTINGS"] = previous

    def test_sidebar_rated_view_and_folder_filter_are_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "shoot"
            source.mkdir()
            image = QImage(64, 48, QImage.Format.Format_RGB32)
            image.fill("#526e7d")
            for name in ("A.JPG", "B.JPG"):
                self.assertTrue(image.save(str(source / name), "JPEG"))
            previous = os.environ.get("PICKLIGHT_SETTINGS")
            os.environ["PICKLIGHT_SETTINGS"] = str(root / "settings.json")
            try:
                window = MainWindow()
                self.assertTrue(window.open_project(source))
                source_id = window.project_id
                window.show()
                self.app.processEvents()
                self.assertEqual(set(window.sidebar_nav), {"all", "rated", "marked"})
                self.assertEqual(window.sidebar_nav["all"].title, "全部")
                window.ratings[window.pairs[0].key] = 3
                window._update_count()
                self.assertEqual(window.sidebar_nav["rated"].count, 1)
                self.assertEqual(window._sidebar_selection, "folder")
                self.assertIsNotNone(window.project_list.currentItem())
                self.assertFalse(window.sidebar_nav["all"].active)
                window.sidebar_nav["rated"].click()
                self.assertEqual([pair.key for pair in window.visible], [window.pairs[0].key])
                self.assertEqual(window._sidebar_selection, "collection")
                self.assertIsNone(window.project_list.currentItem())
                self.assertTrue(window.sidebar_nav["rated"].active)
                window.sidebar_nav["all"].click()
                self.assertEqual(len(window.visible), 2)
                self.assertTrue(window.sidebar_nav["all"].active)
                self.assertIsNone(window.project_list.currentItem())

                source_item = window._project_items[source_id]
                window.project_list.setCurrentItem(source_item)
                self.assertEqual(window._sidebar_selection, "folder")
                self.assertFalse(window.sidebar_nav["all"].active)
                self.assertFalse(window.sidebar_nav["rated"].active)
                window.sidebar_nav["rated"].click()
                window._refresh_project_list()
                self.assertIsNone(window.project_list.currentItem())
                window.project_list.setCurrentItem(window._project_items[source_id])
                self.assertEqual(len(window.visible), 2)
                self.assertFalse(window.sidebar_nav["rated"].active)

                group = window.store.add_folder("旅行")
                match = window.store.add_folder("冬季", group["id"])
                other = window.store.add_folder("工作")
                window._refresh_project_list()
                window._project_items[group["id"]].setExpanded(False)
                self.assertTrue(window.folder_filter_edit.isVisible())
                self.assertFalse(window.filter_button.isChecked())
                window.folder_filter_edit.setText("冬季")
                self.assertFalse(window._project_items[group["id"]].isHidden())
                self.assertTrue(window._project_items[group["id"]].isExpanded())
                self.assertFalse(window._project_items[match["id"]].isHidden())
                self.assertTrue(window._project_items[other["id"]].isHidden())
                window.folder_filter_edit.clear()
                self.assertFalse(window._project_items[other["id"]].isHidden())
                self.assertFalse(window._project_items[group["id"]].isExpanded())
                window.close()
            finally:
                self._close_test_windows()
                if previous is None:
                    os.environ.pop("PICKLIGHT_SETTINGS", None)
                else:
                    os.environ["PICKLIGHT_SETTINGS"] = previous

    def test_sidebar_collection_loads_all_sources_from_empty_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, {"PICKLIGHT_SETTINGS": str(root / "settings.json")}):
                image = QImage(64, 48, QImage.Format.Format_RGB32)
                image.fill("#526e7d")
                sources = [root / "first", root / "second"]
                for source in sources:
                    source.mkdir()
                    self.assertTrue(image.save(str(source / "same.JPG"), "JPEG"))
                window = MainWindow()
                window.open_project(sources[0])
                first_id = window.project_id
                window.open_project(sources[1])
                window.set_rating(4)
                empty = window.store.add_folder("空文件夹")
                window._open_unbound_folder(empty)
                window.sidebar_nav["all"].click()
                self.assertEqual({pair.display_path.parent for pair in window.visible}, set(sources))
                self.assertEqual(len(window.pairs_by_key), 2)  # Same filenames remain distinct.
                self.assertEqual(window.file_label.text(), "全部")
                self.assertIs(window.inspector_stack.currentWidget(), window.collection_inspector)
                self.assertEqual(window.collection_inspector_count.text(), "2")
                window.sidebar_nav["rated"].click()
                self.assertEqual(len(window.visible), 1)
                rated_pair = window.visible[0]
                self.assertEqual(rated_pair.display_path.parent, sources[1])
                self.assertEqual(window.ratings[rated_pair.key], 4)
                self.assertEqual(Path(window._photo_project(rated_pair)["folder"]), sources[1])
                window.toggle_mark()
                window._refresh_project_list()
                window.project_list.setCurrentItem(window._project_items[first_id])
                self.assertEqual([pair.display_path.parent for pair in window.visible], [sources[0]])
                window.sidebar_nav["all"].click()
                self.assertEqual(len(window.visible), 2)
                self.assertEqual(len(window.marked), 1)
                # Linking a nested source must not duplicate the ancestor's photos.
                window.store.add_project(root)
                window.sidebar_nav["all"].click()
                self.assertEqual(len(window.visible), 2)
                window.show()
                self.app.processEvents()
                top_y = window.menu_button.mapTo(window, QPoint()).y()
                self.assertEqual(top_y, window.sidebar_toggle.mapTo(window, QPoint()).y())
                self.assertLessEqual(abs(top_y - window.folder_back_button.mapTo(window, QPoint()).y()), 1)
                window.close()

    def test_filter_bar_has_color_rating_status_and_clear(self):
        with tempfile.TemporaryDirectory() as directory:
            previous = os.environ.get("PICKLIGHT_SETTINGS")
            os.environ["PICKLIGHT_SETTINGS"] = str(Path(directory) / "settings.json")
            try:
                image = QImage(64, 48, QImage.Format.Format_RGB32)
                image.fill("#526e7d")
                self.assertTrue(image.save(str(Path(directory) / "photo.JPG"), "JPEG"))
                window = MainWindow()
                window.open_project(Path(directory))
                window.show()
                window.filter_button.click()
                self.app.processEvents()
                layout = window.filter_content.layout()
                self.assertEqual([layout.itemAt(index).widget().text()
                          for index in range(layout.count())], ["颜色", "评分", "状态", "格式"])
                self.assertFalse(hasattr(window, "facet_chooser"))
                self.assertTrue(window.filter_clear_button.isHidden())
                window.rating_buttons[4].click()
                self.app.processEvents()
                self.assertFalse(window.filter_clear_button.isHidden())
                self.assertEqual(window.filter_clear_button.toolTip(), "清除筛选")
                self.assertGreater(window.filter_clear_button.mapTo(window.filter_bar, QPoint()).x(),
                                   window.filter_content.geometry().right())
                window.filter_clear_button.click()
                self.assertFalse(window.filters.active)
                self.assertTrue(window.filter_clear_button.isHidden())
                self.assertEqual(len(window.visible), 1)
                window.search_edit.setText("photo")
                window.filter_clear_button.click()
                self.assertEqual(window.search_edit.text(), "")
                self.assertTrue(window.search_edit.clear_button.isHidden())
                window.close()
            finally:
                self._close_test_windows()
                if previous is None:
                    os.environ.pop("PICKLIGHT_SETTINGS", None)
                else:
                    os.environ["PICKLIGHT_SETTINGS"] = previous


if __name__ == "__main__":
    unittest.main()
