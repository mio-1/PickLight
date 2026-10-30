"""Background loader cache, cancellation, failure and shutdown contracts."""

import time
import unittest
from concurrent.futures import Future
from pathlib import Path
from threading import Event
from unittest.mock import patch

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from picklight.details import DetailsLoader
from picklight.loading import CachedLoader, TaskLoader
from picklight.palette import PaletteLoader
from picklight.preview import PreviewLoader


class ProbeLoader(CachedLoader):
    ready = Signal(str, object)
    failed = Signal(str, str)


class LoaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def loader(self, kind=ProbeLoader, **kwargs):
        loader = kind(None, **kwargs)
        self.addCleanup(loader.shutdown)
        return loader

    def wait_for(self, predicate):
        deadline = time.monotonic() + 3
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(5)
        self.assertTrue(predicate())

    def test_operation_loader_rejects_overlap_and_late_shutdown_results(self):
        loader = self.loader(TaskLoader, name="test-operation")
        future = Future()
        received = []
        loader.finished.connect(received.append)
        with patch.object(loader.pool, "submit", return_value=future) as submit:
            loader._submit(lambda: 1)
            loader._submit(lambda: 2)
            self.assertEqual(submit.call_count, 1)
        loader.shutdown()
        future.set_result("late result")
        self.app.processEvents()
        self.assertFalse(received)
        self.assertTrue(loader.stop.is_set())
        with patch.object(loader.pool, "submit") as submit:
            loader._submit(lambda: 3)
            submit.assert_not_called()

    def test_operation_failure_can_retry_and_finishes_on_gui_thread(self):
        loader = self.loader(TaskLoader, name="test-operation-retry")
        errors, received = [], []
        loader.failed.connect(errors.append)
        loader.finished.connect(lambda value: received.append((value, QThread.currentThread())))

        def fail():
            raise OSError("write failed")

        loader._submit(fail)
        self.wait_for(lambda: bool(errors))
        self.assertEqual(errors, ["write failed"])
        self.assertFalse(loader.busy)
        loader._submit(lambda: 42)
        self.wait_for(lambda: bool(received))
        self.assertEqual(received, [(42, self.app.thread())])
        self.assertFalse(loader.busy)

    def test_lru_and_empty_cache_hits_do_not_submit_work(self):
        loader = self.loader(name="test-cache", cache_size=2)
        loader.remember("empty", [])
        loader.remember("other", [1])
        self.assertEqual(loader.cached("empty"), [])
        loader.remember("new", [2])
        self.assertIsNone(loader.cached("other"))
        received = []
        loader.ready.connect(lambda *args: received.append(args))
        with patch.object(loader.pool, "submit") as submit:
            loader._request("empty", lambda: self.fail("cache miss"))
            submit.assert_not_called()
        self.assertEqual(received, [("empty", [])])

    def test_invalidated_worker_cannot_overwrite_a_new_request(self):
        loader = self.loader(name="test-invalidate")
        old, new = Future(), Future()
        old.set_running_or_notify_cancel()
        received = []
        loader.ready.connect(lambda *args: received.append(args))
        with patch.object(loader.pool, "submit", side_effect=[old, new]):
            loader._request("photo.JPG", lambda: None)
            loader.invalidate({"photo.JPG"})
            loader._request("photo.JPG", lambda: None)
        old.set_result("old pixels")
        new.set_result("new pixels")
        self.app.processEvents()
        self.assertEqual(received, [("photo.JPG", "new pixels")])

    def test_cancellation_deduplication_and_failure_retry(self):
        loader = self.loader(name="test-pending")
        stale, current = Future(), Future()
        loader.pending["stale"] = stale
        failed = []
        loader.failed.connect(lambda key, error: (loader.forget_failed(key), failed.append(error)))
        with patch.object(loader.pool, "submit", return_value=current) as submit:
            loader._request("new", lambda: None, cancel=lambda key: key != "new")
            loader._request("new", lambda: None)
            self.assertEqual(submit.call_count, 1)
        self.assertTrue(stale.cancelled())
        self.assertNotIn("stale", loader.pending)
        current.set_exception(ValueError("bad metadata"))
        self.wait_for(lambda: bool(failed))
        self.assertEqual(failed, ["bad metadata"])
        self.assertNotIn("new", loader.pending)
        received = []
        loader.ready.connect(lambda *args: received.append(args))
        loader._request("new", lambda: 42)
        self.wait_for(lambda: bool(received))
        self.assertEqual(received, [("new", 42)])

    def test_cached_request_still_cancels_obsolete_queued_work(self):
        loader = self.loader(name="test-cached-priority")
        loader.remember("selected", 42)
        stale = Future()
        loader.pending["previous"] = stale
        received = []
        loader.ready.connect(lambda *args: received.append(args))
        loader._request("selected", lambda: None, cancel=lambda key: key != "selected")
        self.assertTrue(stale.cancelled())
        self.assertEqual(received, [("selected", 42)])

    def test_details_and_palette_keep_their_error_contracts(self):
        details, palette = self.loader(DetailsLoader), self.loader(PaletteLoader)
        errors, colors = [], []
        details.failed.connect(lambda *args: errors.append(args))
        palette.ready.connect(lambda *args: colors.append(args))
        with patch("picklight.details.read_photo_details", side_effect=ValueError("details")):
            details.request(Path("missing.JPG"))
            self.wait_for(lambda: bool(errors))
        with patch("picklight.palette.extract_palette", side_effect=ValueError("palette")):
            palette.request("missing.JPG", QImage())
            self.wait_for(lambda: bool(colors))
        self.assertEqual(errors, [("missing.JPG", "details")])
        self.assertEqual(colors, [("missing.JPG", [])])

    def test_preview_tuple_keys_and_large_image_eviction(self):
        loader = self.loader(PreviewLoader)
        image = QImage(4, 4, QImage.Format.Format_RGB32)
        loader.remember("first", 4400, image)
        loader.remember("thumb", 420, image)
        loader.remember("second", 5000, image)
        self.assertIsNone(loader.cached(Path("first"), 4400))
        self.assertIsNotNone(loader.cached(Path("thumb"), 420))
        received = []
        loader.ready.connect(lambda *args: received.append(args))
        with patch("picklight.preview.decode") as decode:
            loader.request(Path("second"), 5000)
            decode.assert_not_called()
        self.assertEqual(received[0][:2], ("second", 5000))

    def test_preview_cancellation_keeps_running_work_and_other_priorities(self):
        loader = self.loader(PreviewLoader)
        running, queued, thumbnail = Future(), Future(), Future()
        running.set_running_or_notify_cancel()
        loader.pending.update({("running", 2200): running, ("queued", 2200): queued,
                               ("thumb", 420): thumbnail})
        with patch.object(loader.hero_pool, "submit", return_value=Future()):
            loader.request(Path("latest"), 2200)
        self.assertFalse(running.cancelled())
        self.assertTrue(queued.cancelled())
        self.assertFalse(thumbnail.cancelled())
        loader.keep_thumbnails(set())
        self.assertTrue(thumbnail.cancelled())
        self.assertIn(("latest", 2200), loader.pending)

    def test_preview_pool_isolation_and_shutdown_suppresses_results(self):
        loader = self.loader(PreviewLoader)
        release, started = Event(), Event()
        self.addCleanup(release.set)
        received = []
        loader.ready.connect(lambda *args: received.append(args))

        def decode(path, width, color_mode="srgb"):
            if width >= 1000:
                started.set()
                release.wait(3)
            return QImage(4, 4, QImage.Format.Format_RGB32)

        with patch("picklight.preview.decode", side_effect=decode):
            loader.request(Path("hero"), 2200)
            self.wait_for(started.is_set)
            loader.request(Path("thumb"), 420)
            self.wait_for(lambda: bool(received))
            self.assertEqual(received[0][:2], ("thumb", 420))
            loader.closed = True
            release.set()
            loader.shutdown()
        self.app.processEvents()
        self.assertEqual(len(received), 1)
        with patch.object(loader.hero_pool, "submit") as submit:
            loader.request(Path("after-close"), 2200)
            submit.assert_not_called()
