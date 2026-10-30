"""Branded startup surface and background preparation of the restored workspace."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QElapsedTimer, QObject, QRectF, QTimer, QVariantAnimation, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from picklight.message_dialogs import MessageBox as QMessageBox
from picklight.paths import asset_path


def _window_type():
    # Import decoders and window definitions while the splash's event loop runs.
    # All widget construction remains on the UI thread.
    from picklight.window import MainWindow
    return MainWindow


def _prepare_source(folder, children):
    from picklight.library import scan_pairs
    from picklight.projects import prepare_project, source_stamps
    prepared = prepare_project(Path(folder), capture_files=True) if folder and Path(folder).is_dir() else None
    source_pairs = {}
    baseline = dict(prepared.files) if prepared is not None else {}
    for source in children:
        path = Path(source).resolve()
        try:
            source_pairs[str(path)] = scan_pairs(path)
            baseline.update(source_stamps(source_pairs[str(path)]))
        except (OSError, ValueError):
            source_pairs[str(path)] = []
    return prepared, source_pairs, baseline


class StartupSplash(QWidget):
    cancelled = Signal()

    def __init__(self):
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setWindowTitle("PickLight")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(680, 440)
        self.logo = QPixmap(asset_path("picklight.png"))
        self.message = "正在启动 PickLight…"
        self.copyright_text = f"Copyright © {datetime.now().year} iroak"
        self._dismissing = False
        self.clock = QElapsedTimer()
        self.clock.start()
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._advance)
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        if screen is not None:
            self.move(screen.availableGeometry().center() - self.rect().center())

    def showEvent(self, event):
        self.clock.restart()
        self.timer.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def set_message(self, message):
        self.message = message
        self.update(200, 300, 280, 30)

    def _advance(self):
        self.update(205, 274, 270, 30)
        if self.clock.elapsed() < 400:
            self.update(270, 52, 140, 140)

    def dismiss(self):
        self._dismissing = True
        self.close()

    def dispose(self):
        self.deleteLater()

    def closeEvent(self, event):
        self.timer.stop()
        if not self._dismissing:
            self.cancelled.emit()
        super().closeEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        surface = QRectF(20, 20, 640, 400)
        painter.setPen(Qt.PenStyle.NoPen)
        for spread in range(16, 0, -1):
            painter.setBrush(QColor(0, 0, 0, 2))
            painter.drawRoundedRect(surface.adjusted(-spread, -spread + 5, spread, spread + 5),
                                    12 + spread, 12 + spread)
        painter.setBrush(QColor("#18191c"))
        painter.setPen(QColor("#45464a"))
        painter.drawRoundedRect(surface, 12, 12)
        elapsed = self.clock.elapsed()
        painter.save()
        painter.setOpacity(0.65 + 0.35 * min(1, elapsed / 360))
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(QRectF(276, 58, 128, 128), self.logo, QRectF(self.logo.rect()))
        painter.restore()
        title = QFont("Segoe UI")
        title.setPixelSize(28)
        title.setWeight(QFont.Weight.DemiBold)
        painter.setFont(title)
        painter.setPen(QColor("#f4f4f5"))
        painter.drawText(QRectF(120, 202, 440, 42), Qt.AlignmentFlag.AlignCenter, "PickLight")
        rail = QRectF(221, 286, 238, 2)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#3a3b3e"))
        painter.drawRoundedRect(rail, 1, 1)
        center = rail.left() + rail.width() * ((elapsed % 1400) / 1400)
        painter.save()
        painter.setClipRect(QRectF(rail.left(), rail.top() - 7, rail.width(), 16))
        for offset in (-rail.width(), 0, rail.width()):
            position = center + offset
            glow = QLinearGradient(position - 46, 0, position + 46, 0)
            glow.setColorAt(0, QColor(239, 190, 100, 0))
            glow.setColorAt(0.5, QColor(239, 190, 100, 22))
            glow.setColorAt(1, QColor(239, 190, 100, 0))
            painter.fillRect(QRectF(position - 46, rail.top() - 3, 92, 8), glow)
            light = QLinearGradient(position - 36, 0, position + 36, 0)
            light.setColorAt(0, QColor(255, 220, 150, 0))
            light.setColorAt(0.45, QColor("#f7d991"))
            light.setColorAt(0.55, QColor("#fff0bf"))
            light.setColorAt(1, QColor(255, 220, 150, 0))
            painter.fillRect(QRectF(position - 36, rail.top(), 72, 2), light)
        painter.restore()
        caption = QFont("Microsoft YaHei UI")
        caption.setPixelSize(12)
        painter.setFont(caption)
        painter.setPen(QColor("#a0a1a6"))
        painter.drawText(QRectF(160, 305, 360, 24), Qt.AlignmentFlag.AlignCenter, self.message)
        caption.setFamily("Segoe UI")
        caption.setPixelSize(11)
        painter.setFont(caption)
        painter.setPen(QColor("#929397"))
        painter.drawText(QRectF(120, 385, 440, 20), Qt.AlignmentFlag.AlignCenter,
                         self.copyright_text)
        painter.end()


class StartupController(QObject):
    _completed = Signal(str, object)
    finished = Signal()

    def __init__(self, app, *, isolated_splash=None):
        super().__init__(app)
        self.app = app
        isolated_splash = app.platformName() == "windows" if isolated_splash is None else isolated_splash
        if isolated_splash:
            from picklight.splash_process import RemoteSplash
            self.splash = RemoteSplash(app)
        else:
            self.splash = StartupSplash()
        self._isolated_splash = isolated_splash
        self.window = None
        self._cancelled = False
        self._revealing = False
        self._active_project = None
        self._folder = None
        self._warning = None
        self._preview_connected = False
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="picklight-startup")
        self._completed.connect(self._task_finished)
        self.splash.cancelled.connect(self.abort)
        self.transition = QVariantAnimation(self)
        self.transition.setDuration(180)
        self.transition.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.transition.setStartValue(0.0)
        self.transition.setEndValue(1.0)
        self.transition.valueChanged.connect(self._fade)
        self.transition.finished.connect(self._finish)

    def start(self):
        self.app.setQuitOnLastWindowClosed(False)
        if self._isolated_splash:
            self.splash.ready.connect(lambda: self._submit("imports", _window_type))
        self.splash.show()
        if not self._isolated_splash:
            QTimer.singleShot(0, lambda: self._submit("imports", _window_type))

    def _submit(self, stage, function, *args):
        if self._cancelled:
            return
        future = self.pool.submit(function, *args)
        future.add_done_callback(lambda done: self._completed.emit(stage, done)
                                 if not self._cancelled else None)

    def _task_finished(self, stage, future):
        if self._cancelled:
            return
        try:
            result = future.result()
            if stage == "imports":
                self._build_window(result)
            else:
                self._restore_workspace(*result)
        except Exception as error:
            if self.window is None:
                self.splash.dismiss()
                self.pool.shutdown(wait=False, cancel_futures=True)
                QMessageBox.critical(None, "无法启动 PickLight", str(error))
                self.app.exit(1)
            else:
                self._warning = str(error)
                self._reveal()

    def _build_window(self, window_type):
        self.splash.set_message("正在准备照片…")
        self.window = window_type(restore_project=False)
        self.app._main_window = self.window
        # Avoid a second initial source scan while the startup reader is preparing it.
        self.window.source_monitor.debounce.stop()
        self.window.source_monitor.poll.stop()
        store = self.window.store
        active = store.project_by_id(store.data.get("active_project_id", ""))
        self._active_project = active if active and not active.get("folder") else None
        self._folder = None if self._active_project else store.recent_project()
        parent = active or (store.project_for_folder(Path(self._folder)) if self._folder else None)
        children = [project["folder"] for project in store.projects()
                    if parent and project.get("parent_id") == parent["id"] and project.get("folder")]
        self._submit("source", _prepare_source, self._folder, children)

    def _restore_workspace(self, prepared, source_pairs, baseline):
        # The first watcher scan must not discard previews we have just prepared.
        # Changes since these pre-read signatures still invalidate normally.
        self.window.source_monitor.files.update(baseline)
        self.window.loader.ready.connect(self._preview_ready)
        self.window.loader.failed.connect(self._preview_failed)
        self._preview_connected = True
        if self._active_project:
            self.window._open_unbound_folder(self._active_project, source_pairs=source_pairs)
        elif prepared is not None:
            self.window.open_project(prepared.folder, prepared=prepared, source_pairs=source_pairs)
        else:
            self.window._show_empty()
        if self.window._current_pair() is None or self.window.preview_canvas.image is not None:
            self._reveal()

    def _preview_ready(self, path, width, image):
        if not self._cancelled and not self._revealing and str(self.window._current_preview_path()) == path:
            # Defer until every connected preview slot has applied the pixels.
            QTimer.singleShot(0, self._reveal)

    def _preview_failed(self, path, width, error):
        if not self._cancelled and width >= 2200 and str(self.window._current_preview_path()) == path:
            QTimer.singleShot(0, self._reveal)

    def _reveal(self):
        if self._cancelled or self._revealing:
            return
        self._revealing = True
        self.splash.set_message("准备就绪")
        self.window.setWindowOpacity(0)
        self.window.show()
        self.splash.raise_()
        self.transition.start()

    def _fade(self, value):
        if not self._cancelled:
            self.window.setWindowOpacity(float(value))
            self.splash.setWindowOpacity(1 - float(value))

    def _finish(self):
        self.window.setWindowOpacity(1)
        self.window.centralWidget().update_window_shape()
        self.splash.dismiss()
        self.pool.shutdown(wait=False, cancel_futures=True)
        if self._preview_connected:
            self.window.loader.ready.disconnect(self._preview_ready)
            self.window.loader.failed.disconnect(self._preview_failed)
        monitor = self.window.source_monitor
        if monitor.roots:
            monitor.scan()
            monitor.poll.start()
        self.app.setQuitOnLastWindowClosed(True)
        if self.window.isVisible():
            self.window.raise_()
            self.window.activateWindow()
        else:
            self.app.quit()
        self.finished.emit()
        if self._warning:
            QMessageBox.warning(self.window, "无法恢复照片目录", self._warning)
        self.splash.dispose()
        self.app._startup_controller = None
        self.deleteLater()

    def abort(self):
        self._cancelled = True
        self.transition.stop()
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.splash.dismiss()
        if self.window is not None:
            self.window.close()
        self.app.quit()
