"""Stream verified release assets to a disposable update workspace."""

import hashlib
from pathlib import Path
import shutil
import tempfile

from PySide6.QtCore import QObject, QStandardPaths, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest


class UpdateDownload(QObject):
    progress = Signal(int, int)
    ready = Signal(object)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.network = QNetworkAccessManager(self)
        self.reply = self.file = self.directory = None
        self.path = self.asset = None
        self.handed_off = False

    def start(self, asset):
        self.cancel()
        self.asset = asset
        self.received = 0
        self.digest = hashlib.sha256()
        try:
            cache = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation)) / "updates"
            cache.mkdir(parents=True, exist_ok=True)
            self.directory = Path(tempfile.mkdtemp(prefix="download-", dir=cache))
            self.path = self.directory / asset.name
            self.file = self.path.with_suffix(self.path.suffix + ".part").open("wb")
            request = QNetworkRequest(QUrl(asset.url))
            request.setTransferTimeout(30000)
            self.reply = self.network.get(request)
            reply = self.reply
            reply.readyRead.connect(lambda: self._read(reply))
            reply.finished.connect(lambda: self._finished(reply))
        except OSError:
            self._fail("无法保存更新文件，请检查磁盘空间和目录权限")

    def _read(self, reply):
        if reply is not self.reply:
            return
        try:
            while reply.bytesAvailable():
                chunk = bytes(reply.read(256 * 1024))
                if not chunk:
                    break
                self.received += len(chunk)
                if self.received > self.asset.size:
                    self._fail("更新文件大小不符，请重新下载")
                    return
                self.file.write(chunk)
                self.digest.update(chunk)
            self.progress.emit(self.received, self.asset.size)
        except OSError:
            self._fail("更新文件写入失败，请检查磁盘空间后重试")

    def _finished(self, reply):
        if reply is not self.reply:
            return
        self._read(reply)
        if reply is not self.reply:
            return
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        failed = reply.error() != QNetworkReply.NetworkError.NoError or status != 200
        self.reply = None
        reply.deleteLater()
        self.file.close()
        self.file = None
        if failed:
            self._fail("更新下载失败，请检查网络后重试")
        elif self.received != self.asset.size or self.digest.hexdigest() != self.asset.sha256:
            self._fail("更新文件校验失败，请重新下载")
        else:
            try:
                self.path.with_suffix(self.path.suffix + ".part").replace(self.path)
            except OSError:
                self._fail("无法保存更新文件，请检查目录权限")
            else:
                self.ready.emit(self.path)

    def _fail(self, message):
        self.cancel()
        self.failed.emit(message)

    def cancel(self):
        reply, self.reply = self.reply, None
        if reply is not None:
            reply.abort()
            reply.deleteLater()
        if self.file is not None:
            self.file.close()
            self.file = None
        if self.directory is not None and not self.handed_off:
            shutil.rmtree(self.directory, ignore_errors=True)
            self.directory = None
