"""Preference transactions and live presentation must preserve the workspace."""

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel

from picklight.appearance import configure_appearance, sidebar_counts, ui_color
from picklight.preferences import Preferences, configure_startup_scale, save_preferences
from picklight.preferences_dialog import PreferencesDialog
from picklight.session import SessionStore
from picklight.window import MainWindow


class PreferenceDataTests(unittest.TestCase):
    def test_invalid_types_values_and_unknown_keys_are_bounded(self):
        for value in (None, [], "bad", {"appearance": [], "scale": True, "gpu": "false"}):
            self.assertEqual(Preferences.from_data(value), Preferences())
        prefs = Preferences.from_data({"appearance": "purple", "scale": 150, "sidebar_counts": False, "future": 3})
        self.assertEqual((prefs.appearance, prefs.scale, prefs.sidebar_counts), ("purple", 150, False))

    def test_scale_composes_with_existing_os_factor_once_across_restart(self):
        with patch.dict(os.environ, {"QT_SCALE_FACTOR": "1.25"}):
            os.environ.pop("PICKLIGHT_BASE_QT_SCALE", None)
            configure_startup_scale(replace(Preferences(), scale=150))
            self.assertEqual(float(os.environ["QT_SCALE_FACTOR"]), 1.875)
            configure_startup_scale(replace(Preferences(), scale=150))
            self.assertEqual(float(os.environ["QT_SCALE_FACTOR"]), 1.875)
            configure_startup_scale(Preferences())
            self.assertEqual(float(os.environ["QT_SCALE_FACTOR"]), 1.25)

    def test_save_preserves_unrelated_and_future_data_and_rolls_back_os_on_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(Path(directory) / "settings.json")
            store.data.update({"photo_decisions": {"real.jpg": "keep"}, "preferences": {"future": 7}})
            store.save()
            login = Mock()
            login.read.return_value = '"old PickLight.exe"'
            preferences = replace(Preferences(), launch_at_login=True, scale=125)
            save_preferences(store, preferences, login=login)
            login.set_enabled.assert_called_once_with(True)
            self.assertEqual(store.data["preferences"]["future"], 7)
            self.assertEqual(SessionStore(store.path).data["photo_decisions"], {"real.jpg": "keep"})
            old_data = json.loads(store.path.read_text(encoding="utf8"))
            with patch.object(store, "save", side_effect=OSError("read only")):
                with self.assertRaises(OSError):
                    save_preferences(store, replace(preferences, launch_at_login=False), login=login)
            self.assertEqual(store.data, old_data)
            login.write.assert_called_once_with('"old PickLight.exe"')
            self.assertEqual(json.loads(store.path.read_text(encoding="utf8")), old_data)


class PreferencesDialogTests(unittest.TestCase):
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
        login = patch("picklight.preferences_dialog.LoginStartup.read", return_value=None)
        login.start()
        self.addCleanup(login.stop)
        self.window = MainWindow(restore_project=False)
        self.window.show()
        self.app.processEvents()
        self.dialog = None

    def tearDown(self):
        if self.dialog is not None:
            self.dialog.reject()
            self.dialog.deleteLater()
        configure_appearance("dark")
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def make_dialog(self):
        self.dialog = PreferencesDialog(self.window)
        self.dialog.show()
        self.app.processEvents()
        return self.dialog

    def test_menu_opens_preferences_without_shortcut_and_favorites_are_absent(self):
        self.assertTrue(self.window.preferences_action.shortcut().isEmpty())
        with patch.object(PreferencesDialog, "exec", return_value=QDialog.DialogCode.Rejected) as opened:
            QTest.keyClick(self.window, Qt.Key.Key_Comma, Qt.KeyboardModifier.ControlModifier)
            self.app.processEvents()
            opened.assert_not_called()
            self.window.preferences_action.trigger()
            opened.assert_called_once()
        dialog = self.make_dialog()
        self.assertFalse(any("收藏" in label.text() for label in dialog.findChildren(QLabel)))
        dialog.search.setText("GPU")
        self.assertFalse(dialog.general_button.property("selected"))
        self.assertTrue(dialog.appearance_card.isHidden())
        self.assertFalse(dialog.startup_card.isHidden())
        dialog.search.setText("不存在的项目")
        self.assertTrue(dialog.empty.isVisible())
        dialog.general_button.click()
        self.assertEqual(dialog.search.text(), "")
        self.assertTrue(dialog.general_button.property("selected"))
        self.assertFalse(dialog.appearance_card.isHidden())
        self.assertFalse(dialog.startup_card.isHidden())

    def test_close_reverts_theme_preview_and_discards_unapplied_settings(self):
        dialog = self.make_dialog()
        original = self.window.preferences
        original_text_color = ui_color("#ffffff").name()
        dialog.swatches["light"].click()
        self.assertLess(ui_color("#ffffff").lightness(), 100)
        self.assertEqual(dialog._shade.styleSheet(), "background: rgba(0, 0, 0, 140);")
        dialog.counts.setChecked(False)
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        self.assertEqual(self.window.preferences, original)
        self.assertEqual(ui_color("#ffffff").name(), original_text_color)
        self.assertNotIn("preferences", self.window.store.data)

    def test_apply_stays_open_save_closes_and_future_close_keeps_last_apply(self):
        dialog = self.make_dialog()
        dialog.counts.setChecked(False)
        dialog.scale.setCurrentIndex(dialog.scale.findData(125))
        dialog.swatches["purple"].click()
        dialog.apply_button.click()
        self.assertTrue(dialog.isVisible())
        self.assertFalse(sidebar_counts(self.window.project_list))
        self.assertEqual(self.window.project_header_label.text(), "文件夹")
        self.assertTrue(dialog.restart_button.isVisible())
        self.assertEqual(dialog.status.text(), "")
        applied_color = ui_color("#18191c").name()
        dialog.swatches["light"].click()
        dialog.reject()
        self.assertEqual(self.window.preferences.appearance, "purple")
        self.assertEqual(ui_color("#18191c").name(), applied_color)
        dialog = self.make_dialog()
        dialog.counts.setChecked(True)
        dialog.save_button.click()
        self.assertFalse(dialog.isVisible())
        persisted = Preferences.from_data(SessionStore().data["preferences"])
        self.assertEqual((persisted.sidebar_counts, persisted.scale, persisted.appearance), (True, 125, "purple"))

    def test_save_failure_keeps_dialog_open_and_keeps_last_applied_state(self):
        dialog = self.make_dialog()
        dialog.counts.setChecked(False)
        with patch.object(self.window.store, "save", side_effect=OSError("disk full")):
            dialog.save_button.click()
        self.assertTrue(dialog.isVisible())
        self.assertIn("无法保存", dialog.status.text())
        self.assertTrue(self.window.preferences.sidebar_counts)

    def test_palette_switch_preserves_photo_bytes_and_canvas_geometry(self):
        from picklight.ui.visual_filters import ColorFilterPanel
        picker = ColorFilterPanel()
        picker.setParent(self.window)
        picker.set_value("#808080")
        original_swatch_style = picker.preview.styleSheet()
        image = QImage(80, 60, QImage.Format.Format_RGB32)
        image.fill(0xff6496c8)
        path = self.root / "photo.jpg"
        image.save(str(path))
        digest = hashlib.sha256(path.read_bytes()).digest()
        canvas = self.window.preview_canvas
        canvas.set_image(image)
        canvas.zoom = 1.5
        canvas.pan = QPointF(23, -17)
        canvas.rotation = 90
        self.window.current_key = "unchanged"
        self.window.kept = {"unchanged"}
        for appearance in ("light", "blue", "purple", "gray", "lightgray", "dark"):
            self.window._apply_preferences(replace(self.window.preferences, appearance=appearance))
            self.assertEqual(canvas.image.pixel(0, 0), image.pixel(0, 0))
            self.assertEqual((canvas.zoom, canvas.pan, canvas.rotation), (1.5, QPointF(23, -17), 90))
            self.assertEqual(self.window.current_key, "unchanged")
            self.assertEqual(self.window.kept, {"unchanged"})
            self.assertEqual(picker.preview.styleSheet(), original_swatch_style)
        self.assertEqual(hashlib.sha256(path.read_bytes()).digest(), digest)

    def test_transparency_preserves_the_original_three_panel_colors(self):
        window = self.window
        window._show_workspace()

        def backdrop(owner, enabled, light=False):
            owner.setProperty("backdropActive", enabled)
            owner.centralWidget().update()
            return enabled

        with patch("picklight.platform_effects.set_backdrop", side_effect=backdrop):
            for appearance in ("dark", "light", "blue"):
                for transparent in (False, True):
                    window._apply_preferences(replace(window.preferences, appearance=appearance,
                                                      transparency=transparent))
                    self.app.processEvents()
                    screenshot = window.grab().toImage()
                    samples = []
                    for widget, point in ((window.browser_panel, QPoint(window.browser_panel.width() - 12, window.browser_panel.height() // 2)),
                                          (window.viewer, QPoint(2, window.viewer.height() // 2)),
                                          (window.inspector, QPoint(10, window.inspector.height() - 80))):
                        samples.append(screenshot.pixelColor(widget.mapTo(window, point)))
                    self.assertEqual(samples[0], ui_color("#1f2023"))
                    self.assertEqual(samples[1], ui_color("#18191c"))
                    self.assertEqual(samples[2], ui_color("#1f2023"))
                    self.assertNotEqual(samples[0], samples[1])

    def test_selectors_use_compact_popups_and_language_remains_chinese_only(self):
        dialog = self.make_dialog()
        self.assertEqual(dialog.language.count(), 1)
        self.assertEqual(dialog.language.currentText(), "简体中文")
        dialog.scale.showPopup()
        self.app.processEvents()
        popup = dialog.scale._popup
        self.assertEqual(len(popup.actions()), 10)
        QTest.keyClick(popup, Qt.Key.Key_Down)
        QTest.keyClick(popup, Qt.Key.Key_Return)
        self.assertEqual(dialog.scale.currentData(), 110)
        self.assertFalse(dialog.scale.property("popupOpen"))
        dialog.language.showPopup()
        self.app.processEvents()
        QTest.keyClick(dialog.language._popup, Qt.Key.Key_Escape)
        self.assertEqual(dialog.language.currentData(), "zh_CN")

    def test_theme_selector_applies_registered_assets_and_preserves_review_view(self):
        from picklight.themes import theme_manager
        package = self.root / "themes" / "test-theme"
        package.mkdir(parents=True)
        (package / "theme.json").write_text(json.dumps({"format_version": 1, "id": "test-theme",
            "name": "测试主题", "assets": {"app.menu": "menu.svg"}}), encoding="utf8")
        (package / "menu.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><rect width="16" height="16" fill="#ff0000"/></svg>', encoding="utf8")
        (package.parent / "catalog.json").write_text(json.dumps({"themes": ["test-theme"]}), encoding="utf8")
        source = self.root / "photos"
        source.mkdir()
        image = QImage(64, 48, QImage.Format.Format_RGB32)
        image.fill("#405e72")
        image.save(str(source / "photo.jpg"))
        window = self.window
        window.open_project(source)
        window._show_loupe()
        self.app.processEvents()
        window.preview_canvas.set_image(image)
        window.current_image = image
        window.preview_canvas.rotation = 270
        window.preview_canvas.set_zoom(2)
        window.preview_canvas.pan = QPointF(13, -17)
        path = window._current_preview_path()
        dialog = self.make_dialog()
        self.assertEqual(dialog.icon_theme.count(), 3)
        dialog.icon_theme.setCurrentIndex(dialog.icon_theme.findData("test-theme"))
        with patch.object(MainWindow, "_show_preferences") as reopened:
            dialog.apply_button.click()
            self.app.processEvents()
            self.window = self.app._main_window
            QTest.qWait(30)
            self.app.processEvents()
            reopened.assert_called_once_with("")
        self.assertTrue(window.loader.closed)
        self.assertEqual(theme_manager().active.id, "test-theme")
        self.assertEqual(SessionStore().data["icon_theme"], "test-theme")
        self.assertEqual(self.window._current_preview_path(), path)
        canvas = self.window.preview_canvas
        self.assertEqual((canvas.rotation, canvas.zoom, canvas.pan), (270, 2, QPointF(13, -17)))
        dialog.deleteLater()
        self.dialog = None

    def test_palette_change_restores_manual_gallery_layout_and_stable_scroll_range(self):
        source = self.root / "photos"
        source.mkdir()
        for index in range(12):
            image = QImage(48, 80 if index % 2 else 40, QImage.Format.Format_RGB32)
            image.fill("#405e72")
            image.save(str(source / f"{index:02}.jpg"))
        window = self.window
        window.resize(1100, 700)
        window.open_project(source)
        QTest.qWait(120)
        window._resize_grid()
        grid = window.filmstrip
        bar = grid.verticalScrollBar()
        bar.setValue(73)
        original = [grid.visualItemRect(grid.item(index)) for index in range(4)]
        maximum = bar.maximum()
        for name in ("light", "blue", "dark"):
            configure_appearance(name)
            QTest.qWait(50)
            self.app.processEvents()
            self.assertEqual([grid.visualItemRect(grid.item(index)) for index in range(4)], original)
            self.assertEqual(bar.maximum(), maximum)
            self.assertEqual(bar.value(), 73)
            self.assertTrue(window.updatesEnabled())


if __name__ == "__main__":
    unittest.main()
