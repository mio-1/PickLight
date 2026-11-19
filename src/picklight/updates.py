"""Read the latest public stable release without credentials or blocking the UI."""

from dataclasses import dataclass
import json
import re

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from picklight import __version__


RELEASE_API = "https://api.github.com/repos/mio-1/PickLight/releases/latest"
RELEASE_PAGE = "https://github.com/mio-1/PickLight/releases/tag/"


def version_parts(value):
    if not isinstance(value, str) or not re.fullmatch(r"v?\d+\.\d+\.\d+", value):
        raise ValueError("Invalid stable release version")
    return tuple(int(part) for part in value.removeprefix("v").split("."))


@dataclass(frozen=True)
class UpdateAsset:
    name: str
    url: str
    size: int
    sha256: str
    kind: str


@dataclass(frozen=True)
class Release:
    version: str
    url: str
    newer: bool
    assets: tuple[UpdateAsset, ...] = ()


def parse_release(payload, current=__version__):
    data = json.loads(payload)
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        raise ValueError("Expected a published stable release")
    tag = data.get("tag_name")
    latest = version_parts(tag)
    version = tag.removeprefix("v")
    names = {f"PickLight-{version}-Setup.exe": "installer",
             f"PickLight-{version}-win-x64.zip": "portable"}
    assets = []
    for asset in data.get("assets", []):
        if not isinstance(asset, dict):
            continue
        name = asset.get("name")
        digest = asset.get("digest") or ""
        url = f"https://github.com/mio-1/PickLight/releases/download/{tag}/{name}"
        size = asset.get("size")
        if (name in names and asset.get("browser_download_url") == url
                and re.fullmatch(r"sha256:[a-fA-F0-9]{64}", digest)
                and isinstance(size, int) and 0 < size < 2 * 1024 ** 3
                and asset.get("state") == "uploaded"):
            assets.append(UpdateAsset(name, url, size, digest[7:].lower(), names[name]))
    return Release(version, RELEASE_PAGE + tag, latest > version_parts(current), tuple(assets))


class UpdateChecker(QObject):
    ready = Signal(object)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.network = QNetworkAccessManager(self)
        self.reply = None

    def check(self):
        if self.reply is not None:
            return
        request = QNetworkRequest(QUrl(RELEASE_API))
        request.setRawHeader(b"Accept", b"application/vnd.github+json")
        request.setRawHeader(b"User-Agent", f"PickLight/{__version__}".encode("ascii"))
        request.setRawHeader(b"X-GitHub-Api-Version", b"2022-11-28")
        request.setTransferTimeout(15000)
        self.reply = self.network.get(request)
        self.reply.finished.connect(lambda reply=self.reply: self._finished(reply))

    def cancel(self):
        reply, self.reply = self.reply, None
        if reply is not None:
            reply.abort()
            reply.deleteLater()

    def _finished(self, reply):
        if reply is not self.reply:
            return
        self.reply = None
        try:
            status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            if status == 404:
                self.failed.emit("暂未找到正式版本，请稍后重试")
            elif status in (403, 429):
                self.failed.emit("检查请求过于频繁，请稍后重试")
            elif reply.error() != QNetworkReply.NetworkError.NoError or status != 200:
                self.failed.emit("无法连接更新服务，请检查网络后重试")
            else:
                try:
                    release = parse_release(bytes(reply.readAll()))
                except (ValueError, TypeError, UnicodeError):
                    self.failed.emit("更新信息暂不可用，请稍后重试")
                else:
                    self.ready.emit(release)
        finally:
            reply.deleteLater()
