"""Shared task cancellation and UI-owned LRU caches for background loaders."""

from collections import OrderedDict
from concurrent.futures import CancelledError, ThreadPoolExecutor
from threading import Event

from PySide6.QtCore import QObject, Signal
from picklight.file_access import path_key


class TaskLoader(QObject):
    """One explicit operation at a time; return results on the GUI thread."""

    finished = Signal(object)
    failed = Signal(str)
    _completed = Signal(object)

    def __init__(self, parent, *, name):
        super().__init__(parent)
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix=name)
        self.stop = Event()
        self.busy = self.closed = False
        self._completed.connect(self._deliver)

    def _submit(self, function):
        if self.closed or self.busy:
            return
        self.busy = True
        self.pool.submit(function).add_done_callback(self._done)

    def _done(self, future):
        if not self.closed:
            try:
                self._completed.emit(future)
            except RuntimeError:
                pass

    def _deliver(self, future):
        self.busy = False
        if self.closed:
            return
        try:
            result = future.result()
        except CancelledError:
            return
        except Exception as error:
            self.failed.emit(str(error))
        else:
            self.finished.emit(result)

    def shutdown(self):
        self.closed = True
        self.stop.set()
        self.pool.shutdown(wait=False, cancel_futures=True)


class CachedLoader(QObject):
    """Workers emit results; connected UI slots remember them in the cache."""

    _completed = Signal(object, object)

    def __init__(self, parent, *, name, workers=2, cache_size=128):
        super().__init__(parent)
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix=name)
        self._pools = [self.pool]
        self.cache = OrderedDict()
        self.pending = {}
        self.cache_size = cache_size
        self.closed = False
        self._completed.connect(self._deliver)

    def cached(self, key):
        value = self.cache.get(key)
        if value is not None:
            self.cache.move_to_end(key)
        return value

    def cancel_pending(self, predicate):
        for key, future in list(self.pending.items()):
            if predicate(key) and future.cancel():
                self.pending.pop(key, None)

    def _request(self, key, function, *args, pool=None, cancel=None):
        if self.closed:
            return
        if cancel is not None:
            self.cancel_pending(cancel)
        signal_args = key if isinstance(key, tuple) else (key,)
        # Keys are canonical here; subclasses may expose a multi-argument cached().
        cached = CachedLoader.cached(self, key)
        if cached is not None:
            self.ready.emit(*signal_args, cached)
            return
        if key in self.pending:
            return
        future = (pool or self.pool).submit(function, *args)
        self.pending[key] = future

        future.add_done_callback(lambda result: self._completed.emit(key, result) if not self.closed else None)

    def _deliver(self, key, future):
        # Validate on the UI thread so queued results cannot repopulate invalidated caches.
        if self.closed or self.pending.get(key) is not future:
            return
        signal_args = key if isinstance(key, tuple) else (key,)
        try:
            value = future.result()
        except CancelledError:
            return
        except Exception as exc:
            self._failed(signal_args, exc)
        else:
            self.ready.emit(*signal_args, value)

    def invalidate(self, paths):
        paths = {path_key(path) for path in paths}
        for key in self.cache.keys() | self.pending.keys():
            path = key[0] if isinstance(key, tuple) else key
            if path_key(path) in paths:
                self.cache.pop(key, None)
                future = self.pending.pop(key, None)
                if future is not None:
                    future.cancel()

    def _failed(self, signal_args, error):
        self.failed.emit(*signal_args, str(error))

    def remember(self, key, value):
        self.pending.pop(key, None)
        self.cache[key] = value
        self.cache.move_to_end(key)
        while len(self.cache) > self.cache_size:
            self.cache.popitem(last=False)

    def forget_failed(self, key):
        self.pending.pop(key, None)

    def shutdown(self):
        self.closed = True
        # Wait for active readers to release Windows photo handles before closing.
        for pool in self._pools:
            pool.shutdown(wait=True, cancel_futures=True)

