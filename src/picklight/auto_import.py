"""Watch folders already registered in PickLight for new child folders."""

from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer, Signal


class AutoImportMonitor(QObject):
    discovered = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.roots = set()
        self.known = set()
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(self.scan)
        self.timer = QTimer(self)
        self.timer.setInterval(5000)
        self.timer.timeout.connect(self.scan)

    def configure(self, enabled, paths=(), *, scan_now=True):
        if isinstance(paths, (str, Path)):
            paths = (paths,)
        roots = ({Path(path).resolve() for path in paths if path}
                 if enabled else set())
        roots = {path for path in roots if path.is_dir()}
        if not enabled:
            watched = self.watcher.directories()
            if watched:
                self.watcher.removePaths(watched)
            self.roots.clear()
            self.known.clear()
            self.timer.stop()
            return
        if roots == self.roots:
            if scan_now:
                self.scan()
            return
        watched = self.watcher.directories()
        if watched:
            self.watcher.removePaths(watched)
        self.roots = roots
        self.known.update(roots)
        if not roots:
            self.timer.stop()
            return
        self.watcher.addPaths([str(root) for root in roots])
        self.timer.start()
        if scan_now:
            self.scan()

    def scan(self, *_):
        if not self.roots:
            return
        fresh = []
        for root in sorted(self.roots, key=lambda path: str(path).casefold()):
            if not root.is_dir():
                continue
            try:
                for child in root.iterdir():
                    if child.is_dir():
                        child = child.resolve()
                        if child not in self.known:
                            self.known.add(child)
                            fresh.append((child, root))
            except OSError:
                continue
        if fresh:
            self.discovered.emit(sorted(fresh, key=lambda item: str(item[0]).casefold()))
