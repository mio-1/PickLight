"""Immersive review keeps the gallery, photo state and window lifecycle intact."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QIcon, QImage, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from picklight.theme import STYLE
from picklight.library import PhotoPair
from picklight.window import MainWindow
from picklight.ui.toolbar import ToolbarIconButton


class LargeScreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(STYLE)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        override = patch.dict(os.environ, {"PICKLIGHT_SETTINGS": str(self.root / "settings.json")})
        override.start()
        self.addCleanup(override.stop)
        self.source = self.root / "photos"
        self.source.mkdir()
        self.image = QImage(900, 600, QImage.Format.Format_RGB32)
        self.image.fill("#426d82")
        for row in range(16):
            self.image.save(str(self.source / f"photo{row:02}.jpg"))
        self.window = MainWindow(restore_project=False)
        self.window.show()
        self.addCleanup(self.window.close)
        self.window.open_project(self.source)
        for pair in self.window.visible:
            self.window.loader.remember(str(pair.jpg), 420, self.image)
            self.window.loader.remember(str(pair.jpg), 2200, self.image)
        self.window.filmstrip.setCurrentRow(0)
        self.window._load_current_preview()
        self.window.activateWindow()
        self.app.processEvents()

    def enter(self):
        self.window._enter_large_screen()
        self.app.processEvents()
        self.window.preview_canvas.setFocus()
        return self.window.large_screen_page

    def test_entry_points_and_escape_restore_gallery_and_panel_sizes(self):
        w = self.window
        sizes = w.splitter.sizes()
        geometry = w.geometry()
        key = w.current_key
        canvas = w.preview_canvas
        w.preview_expand_button.click()
        self.app.processEvents()
        self.assertFalse(w.isFullScreen())
        self.assertEqual(w.geometry(), geometry)
        self.assertTrue(w._large_screen_active())
        self.assertTrue(w.browser_panel.isHidden())
        self.assertTrue(w.inspector.isHidden())
        self.assertTrue(w.title_bar.isVisible())
        self.assertTrue(w.close_button.isVisible())
        self.assertTrue(w.minimize_button.isVisible())
        self.assertTrue(w.large_screen_back_button.isVisible())
        self.assertTrue(w.large_screen_title.isVisible())
        self.assertAlmostEqual(w.large_screen_title.geometry().center().x(),
                               w.title_bar.rect().center().x(), delta=1)
        self.assertIs(w.preview_canvas, canvas)
        self.assertIs(w.large_screen_page.strip.model(), w.filmstrip.model())
        QTest.keyClick(canvas, Qt.Key.Key_Escape)
        self.app.processEvents()
        self.assertFalse(w._large_screen_active())
        self.assertFalse(w.isFullScreen())
        self.assertEqual(w.center_stack.currentIndex(), 0)
        self.assertEqual(w.current_key, key)
        self.assertTrue(w.browser_panel.isVisible())
        self.assertTrue(w.inspector.isVisible())
        self.assertEqual(w.splitter.sizes(), sizes)
        self.assertEqual(w.geometry(), geometry)

    def test_loupe_entry_navigation_strip_rating_and_decisions_share_state(self):
        w = self.window
        w._show_loupe()
        w.image_fit_button.click()
        self.app.processEvents()
        page = w.large_screen_page
        page.next_button.click()
        self.assertEqual(w.filmstrip.currentRow(), 1)
        self.assertEqual(page.counter.text(), "2 / 16")
        self.assertTrue(page.jpg_button.isChecked())
        self.assertFalse(page.raw_button.isEnabled())
        index = page.strip.model().index(3, 0)
        QTest.mouseClick(page.strip.viewport(), Qt.MouseButton.LeftButton,
                         pos=page.strip.visualRect(index).center())
        self.assertEqual(w.filmstrip.currentRow(), 3)
        page.keep_button.click()
        self.assertIn(w.current_key, w.kept)
        self.assertTrue(page.keep_button.isChecked())
        self.assertTrue(page.footer.isHidden())
        page.reject_button.click()
        self.assertIn(w.current_key, w.marked)
        self.assertFalse(page.keep_button.isChecked())
        with patch("picklight.photos.write_pair_rating") as write:
            QTest.mouseClick(page.stars, Qt.MouseButton.LeftButton, pos=QPoint(62, 12))
        write.assert_called_once_with(w._current_pair(), 3)
        self.assertEqual(page.stars.rating, 3)
        self.assertEqual(w.inspector_stars.rating, 3)
        page.auto_action.trigger()
        self.assertTrue(w.review_auto_advance_button.isChecked())
        page.keep_button.click()
        self.assertEqual(w.filmstrip.currentRow(), 4)
        w.large_screen_back_button.click()
        self.assertFalse(w._large_screen_active())
        self.assertEqual(w.center_stack.currentIndex(), 1)

    def test_large_screen_hides_toolbar_and_keeps_strip(self):
        w = self.window
        page = self.enter()
        page.actual_action.trigger()
        self.assertEqual(w.preview_canvas.zoom, 1)
        page.rotate_action.trigger()
        self.assertEqual(w.preview_canvas.rotation, 270)
        page.fit_action.trigger()
        self.assertTrue(w.preview_canvas.fitted)
        page.strip_action.trigger()
        self.app.processEvents()
        self.assertTrue(page.strip.isHidden())
        page.strip_action.trigger()
        self.app.processEvents()
        self.assertTrue(page.strip.isVisible())
        QTest.mouseMove(w.preview_canvas, QPoint(w.preview_canvas.width() - 40, 150))
        self.assertTrue(page.navigation.isHidden())
        self.assertTrue(page.footer.isHidden())
        self.assertFalse(page.idle_timer.isActive())
        self.assertTrue(w._large_screen_active())

    def test_large_screen_defaults_to_fitting_inside_canvas_across_photos(self):
        page = self.enter()
        canvas = self.window.preview_canvas
        self.assertTrue(canvas.fill_canvas)
        self.assertTrue(canvas.fitted)
        self.assertLessEqual(canvas.image_rect().width(), canvas.width() + 1)
        self.assertLessEqual(canvas.image_rect().height(), canvas.height() + 1)
        page.next_button.click()
        self.app.processEvents()
        self.assertTrue(canvas.fill_canvas)
        self.assertLessEqual(canvas.image_rect().width(), canvas.width() + 1)
        self.assertLessEqual(canvas.image_rect().height(), canvas.height() + 1)
        self.window._exit_large_screen()
        self.assertFalse(canvas.fill_canvas)

    def test_large_screen_icons_match_existing_modes_in_every_state(self):
        w = self.window
        page = self.enter()
        for large, normal in (
            (page.previous_button, w.previous_button),
            (page.next_button, w.next_button),
            (w.large_screen_back_button, w.loupe_back_button),
        ):
            with self.subTest(control=large.accessibleName()):
                self.assertIsInstance(large, ToolbarIconButton)
                self.assertEqual(large.iconSize(), normal.iconSize())
                for mode in (QIcon.Mode.Normal, QIcon.Mode.Active, QIcon.Mode.Disabled):
                    self.assertEqual(large.icon().pixmap(large.iconSize(), mode).toImage(),
                                     normal.icon().pixmap(normal.iconSize(), mode).toImage())
        self.assertEqual(page.jpg_button.size(), w.jpg_source_button.size())
        self.assertEqual(page.raw_button.size(), w.raw_source_button.size())
        self.assertEqual(type(page.keep_button), type(w.keep_flag_button))
        self.assertEqual(page.keep_button.size(), w.keep_flag_button.size())
        self.assertEqual(page.reject_button.size(), w.reject_flag_button.size())

    def test_fullscreen_toggle_restores_maximized_and_collapsed_sidebar(self):
        w = self.window
        w._set_sidebar_collapsed(True)
        w.showMaximized()
        self.app.processEvents()
        w._show_loupe()
        self.enter()
        self.assertTrue(w.isMaximized())
        w.toggle_fullscreen()
        self.app.processEvents()
        self.assertTrue(w._large_screen_active())
        self.assertTrue(w.isFullScreen())
        w.toggle_fullscreen()
        self.app.processEvents()
        self.assertTrue(w.isMaximized())
        self.assertTrue(w.browser_panel.isHidden())
        self.assertTrue(w.title_bar.isVisible())
        self.assertTrue(w._large_screen_active())
        w._exit_large_screen()
        self.assertTrue(w.inspector.isVisible())

    def test_direct_fit_actual_size_and_zoom_limits_share_canvas_state(self):
        page = self.enter()
        page.zoom_label.click()
        self.assertEqual(page.canvas.zoom, 1)
        self.assertFalse(page.canvas.fitted)
        self.assertTrue(page.zoom_label.isChecked())
        self.assertFalse(page.fit_action.isChecked())
        page.zoom_label.click()
        self.assertTrue(page.canvas.fitted)
        self.assertTrue(page.fit_action.isChecked())
        self.assertFalse(page.zoom_label.isChecked())
        page.canvas.set_zoom(.05)
        self.assertFalse(page.zoom_out_action.isEnabled())
        page.canvas.set_zoom(8)
        self.assertFalse(page.zoom_in_action.isEnabled())

    def test_preview_wheel_actions_pan_navigate_and_zoom(self):
        canvas = self.enter().canvas
        canvas.set_image(self.image)
        event = lambda delta: QWheelEvent(
            QPointF(10, 10), QPointF(10, 10), QPoint(), QPoint(0, delta),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase, False)
        canvas.wheel_action = "pan"
        canvas.wheelEvent(event(120))
        self.assertGreater(canvas.pan.y(), 0)
        navigations = []
        canvas.wheelNavigateRequested.connect(navigations.append)
        canvas.wheel_action = "navigate"
        canvas.wheelEvent(event(-120))
        self.assertEqual(navigations, [1])
        canvas.set_image(self.image)
        canvas.wheel_action = "zoom"
        zoom = canvas.zoom
        canvas.wheelEvent(event(120))
        self.assertGreater(canvas.zoom, zoom)

    def test_fit_button_restores_photo_and_zoomed_canvas_shows_navigator(self):
        w = self.window
        w._show_loupe()
        canvas = w.preview_canvas
        canvas.set_image(self.image)
        canvas.fit_to_canvas()
        self.assertTrue(canvas.navigator.isHidden())
        canvas.set_zoom(2)
        self.app.processEvents()
        self.assertTrue(canvas.navigator.isVisible())
        self.assertGreater(canvas.navigator.width(), 100)
        self.assertGreater(canvas.navigator.x(), canvas.width() // 2)
        w.image_fit_canvas_button.click()
        self.app.processEvents()
        self.assertTrue(canvas.fitted)
        self.assertTrue(canvas.navigator.isHidden())
        self.assertEqual(w.image_fit_canvas_button.accessibleName(), "适应大小")

    def test_large_screen_photo_area_has_no_footer_toolbar(self):
        w = self.window
        page = self.enter()
        self.assertTrue(page.raw_button.isHidden())
        self.assertTrue(page.jpg_button.isHidden())
        w.shortcuts["photo.keep"] = "K"
        page.keep_button.click()
        with patch("picklight.photos.write_pair_rating"):
            w.set_rating(4)
        self.assertIn("K", page.keep_button.toolTip())
        self.assertTrue(page.footer.isHidden())
        self.assertTrue(page.navigation.isHidden())
        self.assertFalse(page.idle_timer.isActive())
        self.assertEqual(page.canvas.geometry().bottom(), page.strip.geometry().top() - 1)

    def test_minimum_window_keeps_large_canvas_without_toolbar(self):
        w = self.window
        original = w._current_pair()
        raw = original.jpg.with_suffix(".arw")
        raw.write_bytes(b"raw source fixture")
        pair = PhotoPair(original.key, original.jpg, raw)
        w.pairs[0] = w.visible[0] = pair
        w.pairs_by_key[pair.key] = pair
        page = self.enter()
        w.showNormal()
        w.resize(960, 620)
        self.app.processEvents()
        self.assertEqual(w.width(), 960)
        self.assertTrue(page.footer.isHidden())
        self.assertTrue(page.navigation.isHidden())
        self.assertGreater(page.canvas.height(), 400)

    def test_short_strip_centers_after_filter_and_many_photos_remain_scrollable(self):
        w = self.window
        page = self.enter()
        w._search_photos("photo00")
        self.app.processEvents()
        rect = page.strip.visualRect(page.strip.model().index(0, 0))
        center = page.strip.viewport().mapTo(page.strip, rect.center()).x()
        self.assertAlmostEqual(center, page.strip.rect().center().x(), delta=2)
        w._search_photos("")
        self.app.processEvents()
        self.assertGreater(page.strip.horizontalScrollBar().maximum(), 0)
        self.assertIs(page.strip.selectionModel(), w.filmstrip.selectionModel())

    def test_portrait_thumbnail_retains_top_and_bottom_of_photo(self):
        w = self.window
        portrait = QImage(40, 120, QImage.Format.Format_RGB32)
        portrait.fill("#00ff00")
        for y in range(20):
            for x in range(40):
                portrait.setPixelColor(x, y, Qt.GlobalColor.red)
                portrait.setPixelColor(x, 119 - y, Qt.GlobalColor.blue)
        w.loader.remember(str(w._current_preview_path()), 420, portrait)
        page = self.enter()
        image = page.strip.viewport().grab().toImage()
        rect = page.strip.visualRect(page.strip.currentIndex())
        top = image.pixelColor(rect.center().x(), rect.top() + 12)
        bottom = image.pixelColor(rect.center().x(), rect.bottom() - 14)
        self.assertGreater(top.red(), 240)
        self.assertGreater(bottom.blue(), 240)

    def test_f11_on_grid_only_toggles_fullscreen(self):
        w = self.window
        w.toggle_fullscreen()
        self.app.processEvents()
        self.assertTrue(w.isFullScreen())
        self.assertFalse(w._large_screen_active())
        self.assertEqual(w.center_stack.currentIndex(), 0)
        w._escape_view()
        self.assertFalse(w.isFullScreen())
        self.assertTrue(w.title_bar.isVisible())

    def test_escape_from_fullscreen_returns_to_windowed_large_view_first(self):
        w = self.window
        self.enter()
        w.toggle_fullscreen()
        w._escape_view()
        self.assertFalse(w.isFullScreen())
        self.assertTrue(w._large_screen_active())
        w._escape_view()
        self.assertFalse(w._large_screen_active())

    def test_window_can_be_maximized_during_large_view_and_stays_maximized_on_exit(self):
        w = self.window
        self.enter()
        w.toggle_maximize()
        self.app.processEvents()
        self.assertTrue(w.isMaximized())
        w._exit_large_screen()
        self.assertTrue(w.isMaximized())

    def test_empty_filter_leaves_immersive_view_and_clears_stale_state(self):
        w = self.window
        self.enter()
        w._search_photos("no-matching-photo")
        self.app.processEvents()
        self.assertFalse(w._large_screen_active())
        self.assertFalse(w.isFullScreen())
        self.assertIsNone(w.current_key)
        self.assertIs(w.center_stack.currentWidget(), w.empty_page)
        self.assertFalse(w.preview_expand_button.isEnabled())

    def test_search_returns_to_a_visible_search_control(self):
        w = self.window
        self.enter()
        QTest.keyClick(w.preview_canvas, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
        self.app.processEvents()
        self.assertFalse(w._large_screen_active())
        self.assertEqual(w.center_stack.currentIndex(), 0)
        self.assertTrue(w.search_edit.hasFocus() or w.search_popup.isVisible())

    def test_strip_requests_only_nearby_thumbnails_and_stops_when_hidden(self):
        w = self.window
        page = self.enter()
        with patch.object(w.loader, "cached", return_value=None), \
                patch.object(w.loader, "request") as request:
            page.strip.request_visible()
            self.assertGreater(request.call_count, 0)
            self.assertLessEqual(request.call_count, page.strip.viewport().width() // 100 + 6)
            self.assertTrue(all(call.args[1] == 420 for call in request.call_args_list))
            request.reset_mock()
            page.strip_action.trigger()
            page.strip.request_visible()
            request.assert_not_called()

    def test_source_switch_and_keyboard_review_preserve_canvas_state_on_exit(self):
        w = self.window
        original = w._current_pair()
        raw = original.jpg.with_suffix(".arw")
        raw.write_bytes(b"raw source fixture")
        pair = PhotoPair(original.key, original.jpg, raw)
        w.pairs[0] = pair
        w.visible[0] = pair
        w.pairs_by_key[pair.key] = pair
        w.loader.remember(str(raw), 420, self.image)
        w.loader.remember(str(raw), 2200, self.image)
        w._show_loupe()
        w.preview_canvas.set_zoom(1.75)
        w.preview_canvas.rotate_counterclockwise()
        page = self.enter()
        self.assertAlmostEqual(w.preview_canvas.zoom, w.preview_canvas.fit_zoom())
        self.assertEqual(w.preview_canvas.rotation, 270)
        QTest.keyClick(w.preview_canvas, Qt.Key.Key_R)
        self.assertEqual(w.preview_source, "raw")
        self.assertTrue(page.raw_button.isChecked())
        self.assertEqual(w.preview_canvas.image_key, str(raw))
        QTest.keyClick(w.preview_canvas, Qt.Key.Key_P)
        self.assertTrue(page.keep_button.isChecked())
        with patch("picklight.photos.write_pair_rating"):
            QTest.keyClick(w.preview_canvas, Qt.Key.Key_4)
        self.assertEqual(page.stars.rating, 4)
        QTest.keyClick(w.preview_canvas, Qt.Key.Key_Right)
        self.assertEqual(page.counter.text(), "2 / 16")
        self.assertFalse(page.keep_button.isChecked())
        w.preview_canvas.set_zoom(2)
        w.large_screen_back_button.click()
        self.assertEqual(w.preview_canvas.zoom, 2)
        self.assertEqual(w.preview_source, "jpg")

    def test_live_theme_switch_keeps_large_screen_and_original_return_view(self):
        w = self.window
        page = self.enter()
        page.pin_action.setChecked(True)
        page.strip_action.trigger()
        replacement = w._apply_icon_theme("github")
        self.assertIsNotNone(replacement)
        self.addCleanup(replacement.close)
        self.app.processEvents()
        self.assertTrue(replacement._large_screen_active())
        self.assertTrue(replacement.large_screen_page.pin_action.isChecked())
        self.assertTrue(replacement.large_screen_page.strip.isHidden())
        replacement._exit_large_screen()
        self.app.processEvents()
        self.assertFalse(replacement.isFullScreen())
        self.assertEqual(replacement.center_stack.currentIndex(), 0)
        self.assertTrue(replacement.inspector.isVisible())

    def test_theme_switch_preserves_independent_fullscreen_and_maximized_state(self):
        w = self.window
        w.showMaximized()
        self.enter()
        w.toggle_fullscreen()
        replacement = w._apply_icon_theme("github")
        self.addCleanup(replacement.close)
        self.app.processEvents()
        self.assertTrue(replacement.isFullScreen())
        self.assertTrue(replacement._large_screen_active())
        replacement.toggle_fullscreen()
        self.assertTrue(replacement.isMaximized())
        self.assertTrue(replacement._large_screen_active())
        replacement._exit_large_screen()
        self.assertTrue(replacement.isMaximized())
