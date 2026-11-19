"""Manual release checks on the existing compact update surface."""

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout

from picklight import __version__
from picklight.folder_dialogs import FolderModal
from picklight.updates import UpdateChecker
from picklight.update_download import UpdateDownload
from picklight.update_install import installation_kind, launch_update


class UpdateDialog(FolderModal):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("检查更新")
        self.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)
        self.setFixedSize(456, 204)
        self.layout().setContentsMargins(28, 28, 28, 28)
        self.surface.setFixedSize(400, 148)
        self.surface.setObjectName("updateSurface")
        shadow = QGraphicsDropShadowEffect(self.surface)
        shadow.setBlurRadius(20)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 150))
        self.surface.setGraphicsEffect(shadow)
        self.surface.setStyleSheet("""
            QFrame#updateSurface { background: #18191c; border: 1px solid #414246; border-radius: 8px; }
            QLabel#updateTitle { color: #f7f8f8; font-size: 16px; font-weight: 700; }
            QLabel#updateMessage { color: #bdbec0; font-size: 12px; }
        """)
        layout = QVBoxLayout(self.surface)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(0)
        self.title_label = QLabel("检查更新", objectName="updateTitle")
        self.title_label.setFixedHeight(22)
        layout.addWidget(self.title_label)
        layout.addSpacing(8)
        self.message = QLabel("正在检查更新…", objectName="updateMessage")
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setFixedHeight(18)
        layout.addWidget(self.message)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setStyleSheet("QProgressBar {border:0;background:#36373b;border-radius:2px;}"
                                      "QProgressBar::chunk {background:#3296fa;border-radius:2px;}")
        layout.addWidget(self.progress_bar)
        self.progress_bar.hide()
        layout.addSpacing(18)
        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        self.close_button = QPushButton("取消", objectName="folderModalCancel")
        self.close_button.setFixedHeight(34)
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.clicked.connect(self.reject)
        buttons.addWidget(self.close_button)
        self.confirm_button = QPushButton("检查中…", objectName="folderModalPrimary")
        self.confirm_button.setFixedHeight(34)
        self.confirm_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.confirm_button.setDefault(True)
        self.confirm_button.clicked.connect(self._confirm)
        buttons.addWidget(self.confirm_button, 1)
        layout.addLayout(buttons)
        self.checker = UpdateChecker(self)
        self.checker.ready.connect(self._ready)
        self.checker.failed.connect(self._failed)
        self.download = UpdateDownload(self)
        self.download.progress.connect(self._progress)
        self.download.ready.connect(self._downloaded)
        self.download.failed.connect(self._failed)
        self.handoff_timer = QTimer(self)
        self.handoff_timer.setInterval(100)
        self.handoff_timer.timeout.connect(self._handoff)
        self.updater = None
        self.asset = self.package = None
        self.state = "checking"
        self.release = None
        self.confirm_button.setEnabled(False)
        QTimer.singleShot(0, self._check)

    def _check(self):
        if not self.isVisible():
            return
        self.download.cancel()
        self._show_progress(False)
        self.state = "checking"
        self.message.setText("正在检查更新…")
        self.confirm_button.setText("检查中…")
        self.confirm_button.setEnabled(False)
        self.close_button.setText("取消")
        self.close_button.show()
        self.checker.check()

    def _ready(self, release):
        self.release = release
        self.confirm_button.setEnabled(True)
        if release.newer:
            kind = installation_kind()
            self.asset = next((asset for asset in release.assets if asset.kind == kind), None)
            self.state = "available"
            self.message.setText(f"发现新版本 {release.version}，当前版本 {__version__}")
            self.confirm_button.setText("下载更新" if self.asset else "前往下载")
            self.close_button.setText("稍后")
        else:
            self.state = "current"
            self.message.setText(f"PickLight {__version__} 已是最新版本")
            self.confirm_button.setText("确定")
            self.close_button.hide()

    def _failed(self, message):
        self._cancel_handoff()
        self.state = "failed"
        self._show_progress(False)
        self.message.setText(message)
        self.confirm_button.setText("重试")
        self.confirm_button.setEnabled(True)
        self.close_button.setText("关闭")
        self.close_button.show()

    def _confirm(self):
        if self.state == "failed":
            self._check()
        elif self.state == "available":
            if self.asset:
                self.state = "downloading"
                self._show_progress(True)
                self.progress_bar.setValue(0)
                self.message.setText("正在下载更新…")
                self.confirm_button.setText("下载中…")
                self.confirm_button.setEnabled(False)
                self.close_button.setText("取消")
                self.download.start(self.asset)
            elif QDesktopServices.openUrl(QUrl(self.release.url)):
                self.accept()
            else:
                self._failed("无法打开浏览器，请重试")
        elif self.state == "current":
            self.accept()
        elif self.state == "downloaded":
            parent = self.parentWidget()
            if any(getattr(getattr(parent, name, None), "busy", False)
                   for name in ("import_loader", "photo_file_loader", "batch_rating_loader")):
                self.message.setText("请等待当前文件操作完成后再更新")
                return
            try:
                self.updater = launch_update(self.package, self.asset)
            except (OSError, ValueError) as error:
                self._failed(str(error))
                return
            self.download.handed_off = True
            self.state = "handoff"
            self.handoff_attempts = 0
            self.message.setText("正在准备更新，请稍候…")
            self.confirm_button.setEnabled(False)
            self.handoff_timer.start()

    def _show_progress(self, visible):
        self.progress_bar.setVisible(visible)
        self.surface.setFixedHeight(172 if visible else 148)
        self.setFixedHeight(228 if visible else 204)
        if self.isVisible() and self.parentWidget():
            self.move(self.parentWidget().mapToGlobal(self.parentWidget().rect().center()) - self.rect().center())

    def _progress(self, received, total):
        self.progress_bar.setValue(round(received * 1000 / total))
        self.message.setText(f"正在下载更新… {received / 1048576:.1f} / {total / 1048576:.1f} MB")

    def _downloaded(self, path):
        self.package = path
        self.state = "downloaded"
        self.progress_bar.setValue(1000)
        self.message.setText(f"校验通过，重启后将更新到 {self.release.version}")
        self.confirm_button.setText("重启并更新")
        self.confirm_button.setEnabled(True)
        self.close_button.setText("取消更新")

    def _handoff(self):
        self.handoff_attempts += 1
        work = self.package.parent
        if (work / "error").exists():
            self._failed("无法准备更新，请重试或手动下载安装包")
        elif (work / "ready").exists():
            self.handoff_timer.stop()
            self.state = "installing"
            self.accept()
            if not self.parentWidget().close():
                (work / "cancel").touch()
                self.state = "handoff"
                self.show()
                self._failed("当前操作尚未完成，请稍后重试")
        elif self.updater.poll() is not None or self.handoff_attempts >= 600:
            self._failed("更新组件启动失败，请重试")

    def _cancel_handoff(self):
        self.handoff_timer.stop()
        if self.updater is not None and self.state != "installing":
            try:
                (self.package.parent / "cancel").touch()
            except OSError:
                pass
            self.download.handed_off = False
            self.updater = None

    def hideEvent(self, event):
        self.checker.cancel()
        self._cancel_handoff()
        self.download.cancel()
        super().hideEvent(event)
