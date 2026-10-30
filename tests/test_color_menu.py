"""Color menu choices persist and invalidate only the preview presentation."""

from concurrent.futures import Future
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QColorSpace, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from picklight.color_management import convert_preview, valid_color_mode
from picklight.palette import PaletteLoader, extract_palette
from picklight.preview import PreviewLoader, decode
from picklight.session import SessionStore
from picklight.theme import STYLE
from picklight.window import MainWindow


class ColorMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.style = cls.app.styleSheet()
        cls.app.setStyleSheet(STYLE)

    @classmethod
    def tearDownClass(cls):
        cls.app.setStyleSheet(cls.style)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        environment = patch.dict(os.environ, {"PICKLIGHT_SETTINGS": str(self.root / "settings.json")})
        environment.start()
        self.addCleanup(environment.stop)
        self.window = None

    def tearDown(self):
        if self.window is not None:
            self.window.close()
        self.app.processEvents()

    def wait_for(self, predicate):
        deadline = time.monotonic() + 5
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(5)
        self.assertTrue(predicate())

    def photo(self):
        image = QImage(60, 40, QImage.Format.Format_RGB32)
        image.fill(QColor(100, 150, 200))
        image.setColorSpace(QColorSpace(QColorSpace.NamedColorSpace.AdobeRgb))
        folder = self.root / "photos"
        folder.mkdir(exist_ok=True)
        path = folder / "photo.jpg"
        self.assertTrue(image.save(str(path), "JPEG", 100))
        return path

    def make_window(self):
        self.window = MainWindow(restore_project=False)
        self.window.show()
        self.app.processEvents()
        return self.window

    def test_menu_choices_are_exclusive_and_survive_restart_without_resetting_other_settings(self):
        store = SessionStore()
        store.data["unrelated_setting"] = "preserve me"
        store.save()
        window = self.make_window()
        self.assertEqual([action.text() for action in window.color_management_menu.actions()],
                         ["sRGB", "Display P3", "未管理"])
        self.assertTrue(window.color_mode_actions["srgb"].isChecked())
        for mode in ("display_p3", "unmanaged", "srgb", "display_p3"):
            window.color_mode_actions[mode].trigger()
            self.assertEqual(window.color_mode, mode)
            self.assertEqual(window.loader.color_mode, mode)
            self.assertEqual(sum(action.isChecked() for action in window.color_mode_actions.values()), 1)
        window.close()
        self.window = MainWindow(restore_project=False)
        self.assertTrue(self.window.color_mode_actions["display_p3"].isChecked())
        self.assertEqual(self.window.loader.color_mode, "display_p3")
        self.assertEqual(self.window.store.data["unrelated_setting"], "preserve me")

    def test_modes_produce_different_target_pixels_without_changing_source(self):
        path = self.photo()
        before = hashlib.sha256(path.read_bytes()).digest()
        outputs = {mode: decode(path, 420, mode) for mode in ("srgb", "display_p3", "unmanaged")}
        self.assertEqual(outputs["srgb"].colorSpace(), QColorSpace(QColorSpace.NamedColorSpace.SRgb))
        self.assertEqual(outputs["display_p3"].colorSpace(), QColorSpace(QColorSpace.NamedColorSpace.DisplayP3))
        original = QImage(str(path))
        self.assertEqual(outputs["unmanaged"].pixelColor(0, 0), original.pixelColor(0, 0))
        self.assertNotEqual(outputs["srgb"].pixelColor(0, 0), outputs["display_p3"].pixelColor(0, 0))
        self.assertNotEqual(outputs["srgb"].pixelColor(0, 0), outputs["unmanaged"].pixelColor(0, 0))
        self.assertEqual(hashlib.sha256(path.read_bytes()).digest(), before)

    def test_running_result_from_previous_mode_cannot_replace_new_mode(self):
        loader = PreviewLoader()
        self.addCleanup(loader.shutdown)
        path = self.photo()
        old, new = Future(), Future()
        old.set_running_or_notify_cancel()
        received = []
        loader.ready.connect(lambda path, width, image:
                             (loader.remember(path, width, image), received.append(image)))
        with patch.object(loader.hero_pool, "submit", side_effect=[old, new]) as submit:
            loader.request(path, 2200)
            loader.set_color_mode("display_p3")
            loader.request(path, 2200)
            self.assertEqual(submit.call_args.args[-1], "display_p3")
        source = QImage(str(path))
        old.set_result(convert_preview(source, "srgb"))
        new.set_result(convert_preview(source, "display_p3"))
        self.app.processEvents()
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].colorSpace(), QColorSpace(QColorSpace.NamedColorSpace.DisplayP3))
        loader.set_color_mode("unmanaged")
        self.assertIsNone(loader.cached(path, 2200))

    def test_switch_refreshes_hero_and_thumbnail_while_retaining_loupe_state(self):
        path = self.photo()
        window = self.make_window()
        window.open_project(path.parent)
        window.source_monitor.shutdown()
        self.wait_for(lambda: window.current_image is not None and bool(window.palette_strip.colors))
        window._show_loupe()
        QTest.qWait(25)
        window.preview_canvas.set_zoom(0.75)
        window.preview_canvas.pan = QPointF(15, 20)
        window.preview_canvas.rotate_clockwise()
        window.kept.add(window.current_key)
        selection, filters = window.current_key, deepcopy(window.filters)
        old_icon = window.filmstrip.item(0).icon().cacheKey()
        palette = list(window.palette_strip.colors)
        window._set_color_mode("display_p3")
        self.wait_for(lambda: window.current_image is not None
                      and window.current_image.colorSpace() == QColorSpace(QColorSpace.NamedColorSpace.DisplayP3)
                      and window.filmstrip.item(0).icon().cacheKey() != old_icon)
        self.assertEqual(window.current_key, selection)
        self.assertIn(selection, window.kept)
        self.assertEqual(window.filters, filters)
        self.assertEqual(window.center_stack.currentIndex(), 1)
        self.assertEqual(window.preview_canvas.zoom, 0.75)
        self.assertEqual(window.preview_canvas.pan, QPointF(15, 20))
        self.assertEqual(window.preview_canvas.rotation, 90)
        self.assertEqual(window.palette_strip.colors, palette)

    def test_canonical_palette_reads_source_instead_of_display_clipped_pixels(self):
        path = self.photo()
        expected = extract_palette(decode(path, 480))
        display = QImage(10, 10, QImage.Format.Format_RGB32)
        display.fill(Qt.GlobalColor.red)
        loader = PaletteLoader()
        self.addCleanup(loader.shutdown)
        received = []
        loader.ready.connect(lambda path, colors: (loader.remember(path, colors), received.append(colors)))
        loader.request(str(path), display, from_source=True)
        self.wait_for(lambda: bool(received))
        self.assertEqual(received[0], expected)

    def test_invalid_stored_modes_fall_back_to_srgb(self):
        for mode in (None, [], {}, "unsupported"):
            self.assertEqual(valid_color_mode(mode), "srgb")
        store = SessionStore()
        store.data["color_mode"] = ["invalid"]
        store.save()
        window = self.make_window()
        self.assertEqual(window.color_mode, "srgb")
        self.assertTrue(window.color_mode_actions["srgb"].isChecked())

    def test_folder_cover_refreshes_when_photos_and_child_folders_share_grid(self):
        path = self.photo()
        child = path.parent / "child"
        child.mkdir()
        (child / "cover.jpg").write_bytes(path.read_bytes())
        window = self.make_window()
        window.open_project(path.parent)
        window.source_monitor.shutdown()
        project = window.store.project_by_id(window.project_id)
        window.store.add_project(child, project["id"])
        window._show_folder_overview(project)
        window.folder_children_heading.setChecked(True)
        card = window._folder_cards[0]
        self.wait_for(lambda: card.image is not None)
        window._set_color_mode("display_p3")
        window._request_visible_thumbnails()
        self.wait_for(lambda: card.image.colorSpace() == QColorSpace(QColorSpace.NamedColorSpace.DisplayP3))
