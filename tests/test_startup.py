"""Startup stays responsive while restoring real temporary source/session data."""

import hashlib
import os
from pathlib import Path
import tempfile
from threading import Event
import time
import unittest
from unittest.mock import patch

from PySide6.QtCore import QTimer
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from picklight.projects import prepare_project
from picklight.session import SessionStore
from picklight.startup import StartupController, StartupSplash, _prepare_source
from picklight.window import MainWindow


class StartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        environment = patch.dict(os.environ, {"PICKLIGHT_SETTINGS": str(self.root / "settings.json")})
        environment.start()
        self.addCleanup(environment.stop)
        self.quit_on_close = self.app.quitOnLastWindowClosed()
        self.addCleanup(self.app.setQuitOnLastWindowClosed, self.quit_on_close)
        self.completed = []
        self.controller = None
        self.window = None

    def tearDown(self):
        if self.window is not None and not self.window.loader.closed:
            self.window.close()
        if self.controller is not None and not self.completed:
            with patch.object(self.app, "quit"):
                self.controller.abort()
            self.controller.splash.dismiss()
            self.controller.pool.shutdown(wait=True, cancel_futures=True)
        self.app.processEvents()

    def wait_for(self, predicate):
        deadline = time.monotonic() + 6
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(5)
        self.assertTrue(predicate())

    def source(self):
        folder = self.root / "photos"
        folder.mkdir()
        image = QImage(80, 120, QImage.Format.Format_RGB32)
        image.fill("#476578")
        image.save(str(folder / "photo.jpg"))
        store = SessionStore()
        project = store.add_project(folder)
        store.activate_project(project["id"])
        store.data["photo_decisions"] = {store.photo_path_key(folder / "photo.jpg"): "keep"}
        store.data["sidebar_width"] = 290
        store.save()
        return folder

    def start(self, **kwargs):
        self.controller = StartupController(self.app, **kwargs)
        self.controller.finished.connect(lambda: self.completed.append(True))
        self.controller.start()

    def finish(self):
        self.wait_for(lambda: bool(self.completed))
        self.window = self.app._main_window
        self.assertTrue(self.window.isVisible())
        self.assertEqual(self.window.windowOpacity(), 1)
        self.assertTrue(self.app.quitOnLastWindowClosed())

    def test_brand_surface_animates_and_stops_when_dismissed(self):
        splash = StartupSplash()
        splash.show()
        self.app.processEvents()
        self.assertFalse(splash.logo.isNull())
        with patch.object(splash.clock, "elapsed", return_value=400):
            first = splash.grab().toImage()
        with patch.object(splash.clock, "elapsed", return_value=800):
            second = splash.grab().toImage()
        self.assertNotEqual(first, second)
        self.assertTrue(splash.timer.isActive())
        splash.dismiss()
        self.assertFalse(splash.timer.isActive())

    def test_empty_startup_reaches_workspace_and_releases_controller(self):
        self.start()
        self.finish()
        self.assertEqual(self.window.pairs, [])
        self.assertTrue(self.window.splitter.isVisible())
        self.assertTrue(self.window.browser_panel.isVisible())
        self.assertIs(self.window.center_stack.currentWidget(), self.window.empty_page)
        self.assertFalse(hasattr(self.window, "welcome"))
        self.assertTrue(self.window.empty_import_button.isVisible())
        with patch.object(self.window, "choose_project") as choose:
            self.window.empty_import_button.click()
            choose.assert_called_once_with(parent_id=None)
        self.assertIsNone(self.app._startup_controller)

    def test_restoration_runs_in_background_and_preserves_decisions_and_photo_bytes(self):
        folder = self.source()
        photo = folder / "photo.jpg"
        before = hashlib.sha256(photo.read_bytes()).digest()
        started, release = Event(), Event()

        def slow_source(*args):
            started.set()
            release.wait(3)
            return _prepare_source(*args)

        try:
            with patch("picklight.startup._prepare_source", side_effect=slow_source):
                self.start()
                self.wait_for(started.is_set)
                ticks = []
                timer = QTimer()
                timer.setInterval(10)
                timer.timeout.connect(lambda: ticks.append(True))
                timer.start()
                QTest.qWait(80)
                timer.stop()
                self.assertGreaterEqual(len(ticks), 3)
                self.assertTrue(self.controller.splash.timer.isActive())
                self.assertFalse(self.controller.window.isVisible())
                release.set()
                self.finish()
            self.assertEqual(self.window.project_folder, folder)
            self.assertIn(self.window.current_key, self.window.kept)
            self.assertIsNotNone(self.window.preview_canvas.image)
            self.assertEqual(self.window.store.data["sidebar_width"], 290)
            self.assertEqual(hashlib.sha256(photo.read_bytes()).digest(), before)
        finally:
            release.set()

    def test_unbound_folder_and_child_covers_are_restored(self):
        folder = self.source()
        store = SessionStore()
        source = store.project_by_id(store.data["active_project_id"])
        parent = store.add_folder("精选项目")
        store.move_project(source["id"], parent["id"])
        store.activate_project(parent["id"])
        self.start()
        self.finish()
        self.assertEqual(self.window.project_id, parent["id"])
        self.assertIsNone(self.window.project_folder)
        self.assertEqual(len(self.window._folder_cards), 1)
        self.assertEqual(self.window._folder_card_pairs[source["id"]][0].jpg, folder / "photo.jpg")

    def test_failed_background_restore_opens_window_and_reports_error(self):
        self.source()
        with patch("picklight.startup._prepare_source", side_effect=OSError("读取照片目录失败")), \
                patch("picklight.startup.QMessageBox.warning") as warning:
            self.start()
            self.finish()
            warning.assert_called_once()
        self.assertEqual(self.window.pairs, [])

    def test_prepared_source_is_applied_without_a_second_scan(self):
        folder = self.source()
        prepared = prepare_project(folder)
        self.window = MainWindow(restore_project=False)
        with patch("picklight.projects.scan_pairs", side_effect=AssertionError("重复扫描")):
            self.assertTrue(self.window.open_project(folder, prepared=prepared))
        self.assertEqual(self.window.ratings, prepared.ratings)
        self.assertIn(self.window.current_key, self.window.kept)

    def test_closing_splash_discards_a_late_background_import(self):
        started, release = Event(), Event()

        def slow_import():
            started.set()
            release.wait(3)
            return MainWindow

        try:
            with patch("picklight.startup._window_type", side_effect=slow_import), \
                    patch.object(self.app, "quit") as quit_app:
                self.start()
                self.wait_for(started.is_set)
                self.controller.splash.close()
                quit_app.assert_called_once()
                release.set()
                self.controller.pool.shutdown(wait=True)
                self.app.processEvents()
                self.assertIsNone(self.controller.window)
                self.assertEqual(self.completed, [])
        finally:
            release.set()

    def test_startup_baseline_keeps_warm_previews_and_detects_later_edits(self):
        folder = self.source()
        prepared, children, baseline = _prepare_source(str(folder), [])
        self.window = MainWindow(restore_project=False)
        monitor = self.window.source_monitor
        monitor.debounce.stop()
        monitor.poll.stop()
        monitor.files.update(baseline)
        snapshots = []
        monitor.updated.connect(snapshots.append)
        monitor.scan()
        self.wait_for(lambda: not monitor._busy)
        self.assertEqual(snapshots, [])
        photo = folder / "photo.jpg"
        image = QImage(90, 130, QImage.Format.Format_RGB32)
        image.fill("#67a34f")
        image.save(str(photo))
        monitor.debounce.stop()
        monitor.scan()
        self.wait_for(lambda: bool(snapshots))
        self.assertIn(str(photo), snapshots[-1].changed)

    def test_light_remains_visible_through_the_entire_loop(self):
        splash = StartupSplash()
        splash.show()
        try:
            for elapsed in (0, 200, 700, 1200, 1399, 1400):
                with self.subTest(elapsed=elapsed), patch.object(splash.clock, "elapsed", return_value=elapsed):
                    image = splash.grab().toImage()
                    self.assertTrue(any(image.pixelColor(x, 286).red() > 120
                                        for x in range(221, 459)))
        finally:
            splash.dismiss()

    def test_isolated_surface_keeps_ticking_when_parent_ui_thread_is_blocked(self):
        from picklight.splash_process import RemoteSplash
        remote = RemoteSplash(self.app)
        ready, statistics = [], []
        remote.ready.connect(lambda: ready.append(True))
        remote.statistics.connect(statistics.append)
        remote.show()
        try:
            self.wait_for(lambda: bool(ready))
            self.assertIsNone(remote.fallback)
            remote.request_statistics()
            self.wait_for(lambda: len(statistics) == 1)
            # Deliberately occupy the parent event loop, like building a large workspace.
            time.sleep(0.4)
            remote.request_statistics()
            self.wait_for(lambda: len(statistics) == 2)
            self.assertGreaterEqual(statistics[1]["frames"] - statistics[0]["frames"], 10)
            self.assertLess(statistics[1]["max_gap_ms"], 200)
        finally:
            remote.dismiss()
            remote.process.waitForFinished(3000)

    def test_isolated_startup_restores_workspace_and_helper_exits(self):
        self.source()
        self.start(isolated_splash=True)
        exited = []
        self.controller.splash.process.finished.connect(lambda *_: exited.append(True))
        self.finish()
        self.wait_for(lambda: bool(exited))
        self.assertIn(self.window.current_key, self.window.kept)

    def test_unavailable_helper_falls_back_to_local_startup(self):
        from PySide6.QtCore import QProcess
        with patch.object(QProcess, "start"):
            self.start(isolated_splash=True)
        self.controller.splash.process.errorOccurred.emit(QProcess.ProcessError.FailedToStart)
        self.finish()
