"""Watch linked photo sources and scan changes without blocking the UI thread."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from threading import Event
import os

from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer, Signal

from picklight.library import JPEG_EXTENSIONS, RAW_EXTENSIONS, scan_pairs
from picklight.ui.graphics import safe_rating
from picklight.file_access import file_stamp


@dataclass
class SourceSnapshot:
    files: dict
    pairs: dict
    directories: set
    changed: set
    renamed: dict
    ratings: dict


def scan_sources(roots, previous, forced, stop):
    files, pairs, directories = {}, {}, set()
    extensions = JPEG_EXTENSIONS | RAW_EXTENSIONS | {".xmp"}
    for source in roots:
        if stop.is_set():
            return None
        root = Path(source)
        ancestor = root.parent
        while not ancestor.is_dir() and ancestor != ancestor.parent:
            ancestor = ancestor.parent
        if ancestor.is_dir():
            directories.add(str(ancestor))
        if not root.is_dir():
            pairs[source] = []
            continue
        try:
            def failed(error):
                raise error

            for directory, _children, names in os.walk(root, onerror=failed, followlinks=False):
                if stop.is_set():
                    return None
                directories.add(directory)
                for name in names:
                    path = Path(directory) / name
                    if path.suffix.casefold() in extensions:
                        try:
                            files[str(path)] = file_stamp(path)
                        except FileNotFoundError:
                            continue
            pairs[source] = scan_pairs(root)
        except (OSError, ValueError):
            # A temporarily inaccessible source must not look like an empty directory.
            prefix = os.path.normcase(str(root)) + os.sep
            files.update({path: value for path, value in previous.items()
                          if os.path.normcase(path).startswith(prefix)})
    changed = {path for path in files.keys() | previous.keys()
               if files.get(path) != previous.get(path)} | set(forced)
    old_ids, new_ids = {}, {}
    for table, paths, values in ((old_ids, previous.keys() - files.keys(), previous),
                                 (new_ids, files.keys() - previous.keys(), files)):
        for path in paths:
            stamp = values[path]
            if stamp[-1]:
                table.setdefault((stamp[-2], stamp[-1], stamp[0], stamp[2]), []).append(path)
    renamed = {paths[0]: new_ids[key][0] for key, paths in old_ids.items()
               if len(paths) == 1 and len(new_ids.get(key, [])) == 1}
    affected = {}
    for values in pairs.values():
        for pair in values:
            related = {str(path) for path in (pair.jpg, pair.raw) if path}
            related |= {str(path.with_suffix(".xmp")) for path in (pair.jpg, pair.raw) if path}
            if related & changed:
                affected[str(pair.display_path)] = pair

    def rating(pair):
        return safe_rating(pair, {}) if not stop.is_set() else (0, True)

    with ThreadPoolExecutor(max_workers=8, thread_name_prefix="picklight-sync-rating") as pool:
        ratings = dict(zip(affected, pool.map(rating, affected.values())))
    return SourceSnapshot(files, pairs, directories, changed, renamed, ratings)


class SourceMonitor(QObject):
    updated = Signal(object)
    _completed = Signal(int, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(self._schedule)
        self.watcher.fileChanged.connect(self._file_changed)
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(450)
        self.debounce.timeout.connect(self.scan)
        self.poll = QTimer(self)
        self.poll.setInterval(5000)
        self.poll.timeout.connect(self.scan)
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="picklight-source-sync")
        self.stop = Event()
        self.roots = ()
        self.files = {}
        self._forced = set()
        self._current = set()
        self._rating_retries = {}
        self._generation = 0
        self._busy = False
        self._rescan = False
        self.closed = False
        self._completed.connect(self._finished)

    def set_sources(self, roots):
        roots = tuple(sorted({str(Path(root).resolve()) for root in roots}))
        if self.closed or roots == self.roots:
            return
        self.roots = roots
        self._rating_retries.clear()
        self._generation += 1
        self._schedule()
        if roots:
            self.poll.start()
        else:
            self.poll.stop()
            self.files.clear()
            self._set_watches(set())

    def watch_current(self, paths):
        if self.closed:
            return
        self._current = {str(path) for path in paths if path is not None}
        self._set_watches(set(self.watcher.directories()))

    def _set_watches(self, directories):
        wanted = directories | {path for path in self._current if Path(path).is_file()}
        existing = set(self.watcher.directories()) | set(self.watcher.files())
        if existing - wanted:
            self.watcher.removePaths(sorted(existing - wanted))
        if wanted - existing:
            self.watcher.addPaths(sorted(wanted - existing))

    def _file_changed(self, path):
        self._forced.add(path)
        self._schedule()

    def _schedule(self, *_args):
        if not self.closed:
            self.debounce.start()

    def refresh(self, paths=()):
        """Invalidate a scan begun before an explicit photo operation."""
        self._generation += 1
        self._forced.update(paths)
        self.debounce.stop()
        self.scan()

    def scan(self):
        if self.closed or not self.roots:
            return
        if self._busy:
            self._rescan = True
            return
        self._busy = True
        generation = self._generation
        forced, self._forced = self._forced, set()
        forced |= set(self._rating_retries)
        future = self.pool.submit(scan_sources, self.roots, self.files.copy(), forced, self.stop)
        future.add_done_callback(lambda value: self._completed.emit(generation, value) if not self.closed else None)

    def _finished(self, generation, future):
        self._busy = False
        if self.closed:
            return
        try:
            result = future.result()
        except Exception:
            result = None
        if generation == self._generation and result is not None:
            self.files = result.files
            self._set_watches(result.directories)
            for path, (_, failed) in result.ratings.items():
                attempts = self._rating_retries.pop(path, 0)
                if failed and attempts < 2:
                    self._rating_retries[path] = attempts + 1
            if result.changed:
                self.updated.emit(result)
        if self._rescan or generation != self._generation:
            self._rescan = False
            self._schedule()

    def shutdown(self):
        self.closed = True
        self.stop.set()
        self.debounce.stop()
        self.poll.stop()
        self.pool.shutdown(wait=True, cancel_futures=True)
