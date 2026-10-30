"""Review keys act on the photo, respect editors, and acknowledge real results."""

import hashlib
from dataclasses import replace
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit

from picklight.metadata import MetadataError, read_pair_rating
from picklight.session import SessionStore
from picklight.theme import STYLE
from picklight.window import MainWindow


class ReviewShortcutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(STYLE)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        environment = patch.dict(os.environ, {"PICKLIGHT_SETTINGS": str(self.root / "settings.json")})
        environment.start()
        self.addCleanup(environment.stop)
        source = self.root / "photos"
        source.mkdir()
        for index in range(3):
            image = QImage(240, 160, QImage.Format.Format_RGB32)
            image.fill("#405e72" if index else "#6a7886")
            self.assertTrue(image.save(str(source / f"photo{index}.jpg")))
        self.window = MainWindow(restore_project=False)
        self.window.show()
        self.assertTrue(self.window.open_project(source))
        self.window.filmstrip.setCurrentRow(0)
        self.window._show_loupe()
        self.window.activateWindow()
        self.window.preview_canvas.setFocus()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def press(self, key, target=None, modifiers=Qt.KeyboardModifier.NoModifier):
        QTest.keyClick(target or self.window.preview_canvas, key, modifiers)

    def test_p_x_are_idempotent_u_clears_flags_and_preserves_rating_and_files(self):
        window = self.window
        pair = window._current_pair()
        window.set_rating(3)
        before = hashlib.sha256(pair.display_path.read_bytes()).digest()
        for key, state in ((Qt.Key.Key_P, "keep"), (Qt.Key.Key_P, "keep"),
                           (Qt.Key.Key_X, "reject"), (Qt.Key.Key_X, "reject"), (Qt.Key.Key_U, "none")):
            self.press(key)
            self.assertEqual(pair.key in window.kept, state == "keep")
            self.assertEqual(pair.key in window.marked, state == "reject")
            self.assertEqual(window.review_feedback.kind, state)
            self.assertTrue(window.review_feedback.isVisible())
            self.assertEqual(window.ratings[pair.key], 3)
        self.assertEqual(read_pair_rating(pair), 3)
        self.assertEqual(hashlib.sha256(pair.display_path.read_bytes()).digest(), before)
        window.save_timer.stop()
        window._save_session()
        self.assertEqual(SessionStore().data["photo_decisions"][window.store.photo_path_key(pair.display_path)], "")

    def test_arrow_keys_navigate_once_even_when_zoom_slider_has_focus(self):
        window = self.window
        first, second, third = [pair.key for pair in window.visible]
        self.press(Qt.Key.Key_Right)
        self.assertEqual(window.current_key, second)

        self.press(Qt.Key.Key_Right)
        self.assertEqual(window.current_key, third)
        self.press(Qt.Key.Key_Right)
        self.assertEqual(window.current_key, third)
        window.image_zoom_slider.setFocus()
        self.press(Qt.Key.Key_Left, window.image_zoom_slider)
        self.assertEqual(window.current_key, second)
        self.press(Qt.Key.Key_Left, window.image_zoom_slider)
        self.assertEqual(window.current_key, first)
        self.press(Qt.Key.Key_Left, window.image_zoom_slider)
        self.assertEqual(window.current_key, first)
        self.press(Qt.Key.Key_Right, window.image_zoom_slider)
        self.assertEqual(window.current_key, second)

    def test_rotation_button_turns_counterclockwise_without_changing_the_file(self):
        window = self.window
        path = window._current_preview_path()
        before = hashlib.sha256(path.read_bytes()).digest()
        image = QImage(240, 160, QImage.Format.Format_RGB32)
        image.fill("#405e72")
        window.preview_canvas.set_image(image)
        for expected in (270, 180, 90, 0):
            window.image_rotate_button.click()
            self.assertEqual(window.preview_canvas.rotation, expected)
        self.assertEqual(hashlib.sha256(path.read_bytes()).digest(), before)

    def test_editors_dialogs_modifiers_and_grid_do_not_receive_review_keys(self):
        window = self.window
        original = window.current_key
        editor = QLineEdit(window.preview_canvas.parentWidget())
        editor.setGeometry(0, 0, 120, 28)
        editor.show()
        editor.setFocus()
        QTest.keyClicks(editor, "pxur")
        self.press(Qt.Key.Key_Left, editor)
        self.assertEqual(editor.text(), "pxur")
        self.assertEqual(editor.cursorPosition(), 3)
        self.assertEqual(window.current_key, original)
        self.assertFalse(window.kept or window.marked)
        editor.hide()
        window.preview_canvas.setFocus()
        self.press(Qt.Key.Key_P, modifiers=Qt.KeyboardModifier.ControlModifier)
        self.assertFalse(window.kept)
        dialog = QDialog(window)
        dialog.setModal(True)
        dialog.show()
        self.app.processEvents()
        self.press(Qt.Key.Key_X)
        self.assertFalse(window.marked)
        dialog.reject()
        window._show_grid()
        self.press(Qt.Key.Key_P, window.filmstrip)
        self.assertFalse(window.kept)
        self.assertFalse(window.review_feedback.isVisible())

    def test_feedback_reuses_one_widget_does_not_take_focus_and_expires(self):
        window = self.window
        hud = window.review_feedback
        for key, kind in ((Qt.Key.Key_P, "keep"), (Qt.Key.Key_X, "reject"), (Qt.Key.Key_U, "none")):
            self.press(key)
            self.assertIs(window.review_feedback, hud)
            self.assertEqual(hud.kind, kind)
            self.assertIs(window.focusWidget(), window.preview_canvas)
        self.assertTrue(hud.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
        QTest.qWait(160)
        self.app.processEvents()
        self.assertGreater(hud._opacity, 0.95)
        self.assertLessEqual(abs(hud.geometry().center().x() - window.preview_canvas.geometry().center().x()), 1)
        self.assertLessEqual(hud.geometry().bottom(), window.preview_canvas.geometry().bottom())
        QTest.qWait(1400)
        self.app.processEvents()
        self.assertFalse(hud.isVisible())

    def test_feedback_clears_on_navigation_mode_exit_and_filter_removal(self):
        window = self.window
        self.press(Qt.Key.Key_P)
        self.press(Qt.Key.Key_Right)
        self.assertFalse(window.review_feedback.isVisible())
        self.press(Qt.Key.Key_X)
        window._show_grid()
        self.assertFalse(window.review_feedback.isVisible())
        window.filters.states = {"none"}
        window._apply_filter()
        # First photo was kept, second rejected; clear the first through the
        # existing button semantics before reviewing the unmarked subset.
        window.filters.clear()
        window._apply_filter()
        window.filmstrip.setCurrentRow(0)
        window._set_photo_decision("")
        window.filters.states = {"none"}
        window._apply_filter()
        window._show_loupe()
        self.press(Qt.Key.Key_P)
        self.assertFalse(window.review_feedback.isVisible())

    def test_rating_feedback_follows_success_and_never_claims_failed_write(self):
        window = self.window
        pair = window._current_pair()
        self.press(Qt.Key.Key_4)
        self.assertEqual((window.review_feedback.kind, window.review_feedback.stars), ("rating", 4))
        self.assertEqual(read_pair_rating(pair), 4)
        with patch("picklight.photos.write_pair_rating", side_effect=MetadataError("read only")), \
                patch("picklight.photos.QMessageBox.warning") as warning:
            self.press(Qt.Key.Key_5)
        warning.assert_called_once()
        self.assertEqual(window.ratings[pair.key], 4)
        self.assertFalse(window.review_feedback.isVisible())
        self.press(Qt.Key.Key_0)
        self.assertEqual(window.review_feedback.stars, 0)
        self.assertEqual(read_pair_rating(pair), 0)

    def test_auto_advance_switch_is_next_to_rotation_and_persists(self):
        window = self.window
        button = window.review_auto_advance_button
        layout = window.loupe_right_tools.layout()
        self.assertEqual(layout.indexOf(button), layout.indexOf(window.image_rotate_button) + 1)
        self.assertFalse(button.isChecked())
        current = window.current_key
        window.store.data["unrelated_setting"] = "preserved"
        button.click()
        self.assertTrue(button.isChecked())
        self.assertEqual(window.current_key, current)
        self.assertIs(window.focusWidget(), window.preview_canvas)
        self.assertTrue(SessionStore().data["review_auto_advance"])
        window.close()
        self.window = MainWindow(restore_project=False)
        self.assertTrue(self.window.review_auto_advance_button.isChecked())
        self.assertEqual(self.window.store.data["unrelated_setting"], "preserved")

    def test_auto_advance_handles_keys_and_buttons_and_stops_at_last_photo(self):
        window = self.window
        first, second, third = [pair.key for pair in window.visible]
        before = {pair.key: hashlib.sha256(pair.display_path.read_bytes()).digest() for pair in window.visible}
        window.review_auto_advance_button.click()
        self.press(Qt.Key.Key_P)
        self.assertIn(first, window.kept)
        self.assertEqual(window.current_key, second)
        window.reject_flag_button.click()
        self.assertIn(second, window.marked)
        self.assertEqual(window.current_key, third)
        self.press(Qt.Key.Key_X)
        self.assertIn(third, window.marked)
        self.assertEqual(window.current_key, third)
        window.filmstrip.setCurrentRow(0)
        self.press(Qt.Key.Key_P)  # Confirm an already-kept photo, still advance.
        self.assertEqual(window.current_key, second)
        for pair in window.visible:
            self.assertEqual(hashlib.sha256(pair.display_path.read_bytes()).digest(), before[pair.key])

    def test_auto_advance_excludes_rating_clear_unmark_and_grid(self):
        window = self.window
        first = window.current_key
        window.review_auto_advance_button.click()
        self.press(Qt.Key.Key_2)
        self.assertEqual(window.current_key, first)
        self.press(Qt.Key.Key_U)
        self.assertEqual(window.current_key, first)
        self.press(Qt.Key.Key_P)
        window.filmstrip.setCurrentRow(0)
        window.keep_flag_button.click()  # Turning the selected mark off is not a review decision.
        self.assertEqual(window.current_key, first)
        self.assertNotIn(first, window.kept)
        window.review_auto_advance_button.click()
        self.press(Qt.Key.Key_X)
        self.assertEqual(window.current_key, first)
        window.review_auto_advance_button.click()
        window._show_grid()
        window.keep_flag_button.click()
        self.assertEqual(window.current_key, first)

    def test_auto_advance_never_skips_when_a_filter_already_selects_the_next_photo(self):
        window = self.window
        first, second, third = [pair.key for pair in window.visible]
        window.filters.states = {"none"}
        window._apply_filter()
        window.review_auto_advance_button.click()
        self.press(Qt.Key.Key_P)
        self.assertIn(first, window.kept)
        self.assertEqual(window.current_key, second)
        self.press(Qt.Key.Key_X)
        self.assertIn(second, window.marked)
        self.assertEqual(window.current_key, third)
        self.press(Qt.Key.Key_X)
        self.assertEqual(window.visible, [])

    def test_auto_advance_switch_rolls_back_when_settings_cannot_be_saved(self):
        window = self.window
        with patch.object(window.store, "save", side_effect=OSError("read only")), \
                patch("picklight.workspace.QMessageBox.warning") as warning:
            window.review_auto_advance_button.click()
        warning.assert_called_once()
        self.assertFalse(window.review_auto_advance_button.isChecked())
        self.assertNotIn("review_auto_advance", window.store.data)

    def paired_source(self):
        window = self.window
        window.source_monitor.shutdown()
        pair = window._current_pair()
        raw = self.root / "paired-preview.arw"
        raw.write_bytes(b"test placeholder; decoding is controlled by the test")
        paired = replace(pair, raw=raw)
        window.pairs = [paired if item.key == pair.key else item for item in window.pairs]
        window.visible = [paired if item.key == pair.key else item for item in window.visible]
        window.pairs_by_key[pair.key] = paired
        return paired

    def test_r_switches_cached_jpg_raw_without_changing_photo_or_starting_spinner(self):
        window = self.window
        pair = self.paired_source()
        jpg = QImage(60, 40, QImage.Format.Format_RGB32)
        raw = QImage(60, 40, QImage.Format.Format_RGB32)
        jpg.fill("#405e72")
        raw.fill("#896542")
        window.loader.remember(str(pair.jpg), 2200, jpg)
        window.loader.remember(str(pair.raw), 2200, raw)
        errors = []
        with patch.object(window.details_loader, "request"), patch("sys.excepthook", side_effect=lambda *args: errors.append(args)):
            window._on_row_changed(0)
            self.press(Qt.Key.Key_R)
            self.assertEqual(window.preview_source, "raw")
            self.assertTrue(window.raw_source_button.isChecked())
            self.assertEqual(window.current_image.pixelColor(0, 0), raw.pixelColor(0, 0))
            self.assertFalse(window.preview_canvas.loading_spinner._wanted)
            self.press(Qt.Key.Key_R)
            self.assertEqual(window.preview_source, "jpg")
            self.assertTrue(window.jpg_source_button.isChecked())
            self.assertEqual(window.current_image.pixelColor(0, 0), jpg.pixelColor(0, 0))
            self.assertFalse(window.inspector_preview.loading_spinner._wanted)
        self.assertEqual(errors, [])
        self.assertEqual(window.current_key, pair.key)
        window._show_grid()
        self.press(Qt.Key.Key_R, window.filmstrip)
        self.assertEqual(window.preview_source, "jpg")

    def test_r_does_nothing_when_only_one_format_is_available(self):
        window = self.window
        with patch.object(window, "_load_current_preview") as request:
            self.press(Qt.Key.Key_R)
            request.assert_not_called()
            self.assertEqual(window.preview_source, "jpg")
            pair = replace(self.paired_source(), jpg=None)
            window.pairs_by_key[pair.key] = pair
            window.preview_source = "raw"
            self.press(Qt.Key.Key_R)
            request.assert_not_called()
            self.assertEqual(window.preview_source, "raw")

    def test_spinner_animates_pauses_when_hidden_and_stops_on_success_or_current_error(self):
        window = self.window
        pair = self.paired_source()
        spinner = window.preview_canvas.loading_spinner
        with patch.object(window.loader, "request"), patch.object(window.details_loader, "request"):
            self.press(Qt.Key.Key_R)
            self.assertTrue(spinner.isVisible())
            self.assertTrue(spinner.timer.isActive())
            self.assertEqual(window.preview_canvas.message, "")
            first_frame = spinner.grab().toImage()
            QTest.qWait(55)
            self.assertNotEqual(spinner.grab().toImage(), first_frame)
            window._show_grid()
            self.assertFalse(spinner.timer.isActive())
            window._show_loupe()
            self.assertTrue(spinner.timer.isActive())
            ready = QImage(60, 40, QImage.Format.Format_RGB32)
            ready.fill("#405e72")
            window._preview_ready(str(pair.raw), 2200, ready)
            self.assertFalse(spinner.isVisible())
            self.assertFalse(spinner.timer.isActive())
            self.assertFalse(window.inspector_preview.loading_spinner.timer.isActive())
            window.preview_canvas.set_loading()
            window.inspector_preview.set_loading()
            window._preview_failed(str(pair.raw), 2200, "test decode failure")
            self.assertFalse(spinner.isVisible())
            self.assertIn("无法显示", window.preview_canvas.message)
            window.loader.invalidate({str(pair.jpg), str(pair.raw)})
            self.press(Qt.Key.Key_R)  # New JPG request; a stale RAW error must not stop it.
            self.assertTrue(spinner.timer.isActive())
            window._preview_failed(str(pair.raw), 2200, "obsolete failure")
            self.assertTrue(spinner.timer.isActive())


if __name__ == "__main__":
    unittest.main()
