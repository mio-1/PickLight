"""Coordinate photo reads and metadata replacement within this process."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from functools import wraps
from pathlib import Path
from threading import Lock, RLock
from weakref import WeakValueDictionary
import os


_registry_lock = Lock()
_file_locks: WeakValueDictionary[str, RLock] = WeakValueDictionary()


def path_key(path):
    return os.path.normcase(os.path.abspath(path))


def file_stamp(path):
    """One watcher signature shared by import snapshots and live source scans."""
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, stat.st_dev, stat.st_ino


@contextmanager
def photo_files(paths: list[Path]):
    """Hold file locks in a stable order, including nested calls on this thread."""
    keys = sorted({path_key(path) for path in paths})
    with _registry_lock:
        locks = []
        for key in keys:
            lock = _file_locks.get(key)
            if lock is None:
                lock = RLock()
                _file_locks[key] = lock
            locks.append(lock)
    with ExitStack() as stack:
        for lock in locks:
            stack.enter_context(lock)
        yield


def locked_paths(path_getter):
    """Apply the same file lock to a complete read or write operation."""
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            with photo_files(path_getter(*args, **kwargs)):
                return function(*args, **kwargs)
        return wrapped
    return decorate
