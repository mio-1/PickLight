"""Prepare an import off the GUI thread; publish only completed, current jobs."""

from concurrent.futures import CancelledError, ThreadPoolExecutor
from threading import Event
from time import monotonic

from PySide6.QtCore import QObject, Signal

from picklight.projects import prepare_project


class ImportLoader(QObject):
    ready = Signal(object)
    failed = Signal(str)
    progress = Signal(int, int, str)
    cancelled = Signal()
    _completed = Signal(int, object)
    _progress = Signal(int, int, int, str)

    def __init__(self, parent):
        super().__init__(parent)
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="picklight-import")
        self.busy = self.closed = False
        self.generation = 0
        self.stop = Event()
        self.future = None
        self._completed.connect(self._deliver)
        self._progress.connect(self._deliver_progress)

    def load(self, folder):
        if self.closed or self.busy:
            return
        self.busy = True
        self.generation += 1
        generation, stop = self.generation, Event()
        self.stop = stop
        last = 0.0

        def report(done, total, path):
            nonlocal last
            now = monotonic()
            if not stop.is_set() and (now - last >= .05 or done == total):
                last = now
                try:
                    self._progress.emit(generation, done, total, path)
                except RuntimeError:
                    return

        def completed(future):
            if not self.closed and not stop.is_set():
                try:
                    self._completed.emit(generation, future)
                except RuntimeError:
                    return

        self.future = self.pool.submit(prepare_project, folder, capture_files=True, progress=report, cancel=stop)
        self.future.add_done_callback(completed)

    def _deliver_progress(self, generation, done, total, path):
        if not self.closed and self.busy and generation == self.generation:
            self.progress.emit(done, total, path)

    def _deliver(self, generation, future):
        if self.closed or generation != self.generation:
            return
        self.busy = False
        try:
            result = future.result()
        except CancelledError:
            self.cancelled.emit()
        except Exception as error:
            self.failed.emit(str(error))
        else:
            self.ready.emit(result)

    def cancel(self):
        self.generation += 1
        self.stop.set()
        if self.future is not None:
            self.future.cancel()
        self.busy = False
        self.cancelled.emit()

    def shutdown(self):
        self.closed = True
        self.cancel()
        self.pool.shutdown(wait=False, cancel_futures=True)
