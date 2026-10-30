"""Keep the startup surface responsive while the workspace builds its widgets."""

import json
import sys
from uuid import uuid4

from PySide6.QtCore import QEasingCurve, QObject, QProcess, QTimer, QVariantAnimation, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from picklight.startup import StartupSplash


def _send(socket, message):
    if socket is not None and socket.state() == QLocalSocket.LocalSocketState.ConnectedState:
        socket.write((json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"))
        socket.flush()


class RemoteSplash(QObject):
    """A small adapter; only local named-pipe messages cross the process boundary."""

    ready = Signal()
    cancelled = Signal()
    statistics = Signal(object)

    def __init__(self, app):
        super().__init__(app)
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self._connected)
        self.channel = "picklight-startup-" + uuid4().hex
        self.process = QProcess(self)
        self.process.finished.connect(self._process_finished)
        self.process.errorOccurred.connect(self._process_error)
        self.socket = None
        self.fallback = None
        self._ready = False
        self._done = False
        self._fading = False
        self._message = "正在启动 PickLight…"
        self.timeout = QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.setInterval(5000)
        self.timeout.timeout.connect(self._show_fallback)
        self.kill_timer = QTimer(self)
        self.kill_timer.setSingleShot(True)
        self.kill_timer.setInterval(2000)
        self.kill_timer.timeout.connect(self._stop_if_running)

    def show(self):
        if not self.server.listen(self.channel):
            self._show_fallback()
            return
        args = ["--startup-splash", self.channel]
        if not getattr(sys, "frozen", False):
            args = ["-m", "picklight.app", *args]
        self.process.start(sys.executable, args)
        self.timeout.start()

    def _connected(self):
        socket = self.server.nextPendingConnection()
        if self.socket is not None or self._done:
            socket.disconnectFromServer()
            socket.deleteLater()
            return
        self.socket = socket
        socket.readyRead.connect(self._read)

    def _read(self):
        while self.socket is not None and self.socket.canReadLine():
            try:
                message = json.loads(bytes(self.socket.readLine()))
            except (ValueError, UnicodeDecodeError):
                continue
            if message.get("event") == "shown" and not self._ready and not self._done:
                self.timeout.stop()
                self._ready = True
                self.set_message(self._message)
                self.ready.emit()
            elif message.get("event") == "cancelled" and not self._done:
                self._done = True
                self.cancelled.emit()
            elif message.get("event") == "statistics":
                self.statistics.emit(message)

    def set_message(self, message):
        self._message = message
        if self.fallback is not None:
            self.fallback.set_message(message)
        _send(self.socket, {"command": "message", "text": message})

    def raise_(self):
        if self.fallback is not None:
            self.fallback.raise_()
        else:
            _send(self.socket, {"command": "raise"})

    def setWindowOpacity(self, opacity):
        if self.fallback is not None:
            self.fallback.setWindowOpacity(opacity)
        elif opacity < 1 and not self._fading:
            self._fading = True
            _send(self.socket, {"command": "fade", "duration": 180})

    def request_statistics(self):
        _send(self.socket, {"command": "statistics"})

    def dismiss(self):
        self._done = True
        self.timeout.stop()
        if self.fallback is not None:
            self.fallback.dismiss()
            self.fallback.deleteLater()
            self.fallback = None
        _send(self.socket, {"command": "fade", "duration": 180})
        if self.process.state() == QProcess.ProcessState.NotRunning:
            self._cleanup()
        else:
            self.kill_timer.start()

    def dispose(self):
        # The application owns this adapter until the helper finishes its fade.
        pass

    def _stop_if_running(self):
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()

    def _show_fallback(self):
        if self._done or self.fallback is not None:
            return
        self.timeout.stop()
        self._stop_if_running()
        if self.socket is not None:
            self.socket.disconnectFromServer()
        self.server.close()
        self.fallback = StartupSplash()
        self.fallback.cancelled.connect(self.cancelled)
        self.fallback.set_message(self._message)
        self.fallback.show()
        if not self._ready:
            self._ready = True
            self.ready.emit()

    def _process_error(self, error):
        if not self._done:
            self._show_fallback()

    def _process_finished(self, *args):
        self._read()
        if self._done:
            self._cleanup()
        elif self.fallback is None:
            self._show_fallback()

    def _cleanup(self):
        self.timeout.stop()
        self.kill_timer.stop()
        if self.socket is not None:
            self.socket.disconnectFromServer()
        self.server.close()
        self.deleteLater()


class SplashBridge(QObject):
    def __init__(self, app, channel):
        super().__init__(app)
        self.app = app
        self.splash = StartupSplash()
        self.socket = QLocalSocket(self)
        self.socket.connected.connect(lambda: _send(self.socket, {"event": "shown"}))
        self.socket.readyRead.connect(self._read)
        self.socket.disconnected.connect(app.quit)
        self.socket.errorOccurred.connect(lambda *_: app.quit())
        self.splash.cancelled.connect(self._cancel)
        self.fade = QVariantAnimation(self)
        self.fade.setDuration(180)
        self.fade.setStartValue(1.0)
        self.fade.setEndValue(0.0)
        self.fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.fade.valueChanged.connect(self.splash.setWindowOpacity)
        self.fade.finished.connect(self.splash.dismiss)
        self._fading = False
        self.frames = 0
        self.max_gap = 0
        self._last_tick = None
        self.splash.timer.timeout.connect(self._record_tick)
        self.splash.show()
        self.socket.connectToServer(channel)

    def _record_tick(self):
        now = self.splash.clock.elapsed()
        if self._last_tick is not None:
            self.max_gap = max(self.max_gap, now - self._last_tick)
        self._last_tick = now
        self.frames += 1

    def _read(self):
        while self.socket.canReadLine():
            try:
                message = json.loads(bytes(self.socket.readLine()))
            except (ValueError, UnicodeDecodeError):
                continue
            command = message.get("command")
            if command == "message":
                self.splash.set_message(str(message.get("text", "")))
            elif command == "raise":
                self.splash.raise_()
            elif command == "fade" and not self._fading:
                self._fading = True
                self.fade.start()
            elif command == "statistics":
                _send(self.socket, {"event": "statistics", "frames": self.frames,
                                    "max_gap_ms": self.max_gap})

    def _cancel(self):
        _send(self.socket, {"event": "cancelled"})


def run_splash_process(app, channel):
    app._splash_bridge = SplashBridge(app, channel)
    return app.exec()
