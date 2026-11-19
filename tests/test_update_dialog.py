"""Release parsing, request handling and the manual update dialog."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtNetwork import QNetworkReply
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from picklight import __version__
from picklight.theme import STYLE
from picklight.update_dialog import UpdateDialog
from picklight.updates import Release, UpdateAsset, UpdateChecker, parse_release
from picklight.window import MainWindow


class UpdateDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.style = cls.app.styleSheet()
        cls.app.setStyleSheet(STYLE)

    @classmethod
    def tearDownClass(cls):
        cls.app.setStyleSheet(cls.style)

    def setUp(self):
        check = patch("picklight.update_dialog.UpdateChecker.check")
        self.check = check.start()
        self.addCleanup(check.stop)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        environment = patch.dict(os.environ, {"PICKLIGHT_SETTINGS": str(Path(temporary.name) / "settings.json")})
        environment.start()
        self.addCleanup(environment.stop)
        self.window = MainWindow(restore_project=False)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.app.processEvents()

    def test_checking_then_current_confirmation_clears_backdrop(self):
        self.assertTrue(self.window.check_update_action.isVisible())
        dialog = UpdateDialog(self.window)
        dialog.show()
        self.app.processEvents()
        self.check.assert_called_once()
        self.assertFalse(dialog.confirm_button.isEnabled())
        self.assertEqual(dialog.geometry().center(), self.window.mapToGlobal(self.window.rect().center()))
        self.assertTrue(dialog.isModal())
        self.assertIsNotNone(dialog._shade)
        dialog.checker.ready.emit(Release(__version__, "", False))
        self.assertIn("已是最新版本", dialog.message.text())
        self.assertIn(__version__, dialog.message.text())
        QTest.mouseClick(dialog.confirm_button, Qt.MouseButton.LeftButton)
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertIsNone(dialog._shade)
        self.assertFalse(dialog.isVisible())

    def test_new_release_opens_its_page_only_on_click(self):
        dialog = UpdateDialog(self.window)
        dialog.show()
        self.app.processEvents()
        release = parse_release(json.dumps({"tag_name": "v0.2.0"}), "0.1.0")
        with patch("picklight.update_dialog.QDesktopServices.openUrl", return_value=True) as open_url:
            dialog.checker.ready.emit(release)
            open_url.assert_not_called()
            self.assertEqual(dialog.confirm_button.text(), "前往下载")
            QTest.mouseClick(dialog.confirm_button, Qt.MouseButton.LeftButton)
            self.assertEqual(open_url.call_args.args[0].toString(), release.url)
            self.assertFalse(dialog.isVisible())

    def test_error_can_retry_and_closing_cancels_request(self):
        dialog = UpdateDialog(self.window)
        dialog.show()
        self.app.processEvents()
        dialog.checker.failed.emit("无法连接更新服务，请检查网络后重试")
        self.assertEqual(dialog.confirm_button.text(), "重试")
        QTest.mouseClick(dialog.confirm_button, Qt.MouseButton.LeftButton)
        self.assertEqual(self.check.call_count, 2)
        self.assertFalse(dialog.confirm_button.isEnabled())
        with patch.object(dialog.checker, "cancel") as cancel:
            dialog.reject()
            cancel.assert_called_once()
        self.assertIsNone(dialog._shade)

    def test_download_requires_a_second_confirmation_before_restart(self):
        dialog = UpdateDialog(self.window)
        dialog.show()
        self.app.processEvents()
        asset = UpdateAsset("update.zip", "", 100, "a" * 64, "portable")
        with tempfile.TemporaryDirectory() as work, \
                patch("picklight.update_dialog.installation_kind", return_value="portable"), \
                patch.object(dialog.download, "start") as download, \
                patch("picklight.update_dialog.launch_update", return_value=Mock()) as launch, \
                patch.object(self.window, "close", return_value=True) as close:
            package = Path(work) / "update.zip"
            dialog.checker.ready.emit(Release("0.2.0", "", True, (asset,)))
            self.assertEqual(dialog.confirm_button.text(), "下载更新")
            QTest.mouseClick(dialog.confirm_button, Qt.MouseButton.LeftButton)
            download.assert_called_once_with(asset)
            self.assertFalse(dialog.confirm_button.isEnabled())
            dialog.download.progress.emit(50, 100)
            self.assertEqual(dialog.progress_bar.value(), 500)
            dialog.download.ready.emit(package)
            self.assertEqual(dialog.confirm_button.text(), "重启并更新")
            launch.assert_not_called()
            close.assert_not_called()
            QTest.mouseClick(dialog.confirm_button, Qt.MouseButton.LeftButton)
            launch.assert_called_once_with(package, asset)
            close.assert_not_called()
            (Path(work) / "ready").touch()
            dialog._handoff()
            close.assert_called_once()
            self.assertTrue(dialog.download.handed_off)
            self.assertIsNone(dialog._shade)

    def test_failed_updater_preparation_keeps_application_open(self):
        dialog = UpdateDialog(self.window)
        dialog.show()
        self.app.processEvents()
        with tempfile.TemporaryDirectory() as work, \
                patch("picklight.update_dialog.launch_update", return_value=Mock()) as launch, \
                patch.object(self.window, "close") as close:
            dialog.package = Path(work) / "update.zip"
            dialog.asset = UpdateAsset("update.zip", "", 1, "a" * 64, "portable")
            dialog.state = "downloaded"
            dialog.confirm_button.setEnabled(True)
            QTest.mouseClick(dialog.confirm_button, Qt.MouseButton.LeftButton)
            launch.assert_called_once()
            (Path(work) / "error").write_text("invalid zip")
            dialog._handoff()
            close.assert_not_called()
            self.assertEqual(dialog.state, "failed")
            self.assertTrue((Path(work) / "cancel").exists())
            self.assertFalse(dialog.download.handed_off)
            dialog.reject()

    def test_enter_confirms_and_escape_dismisses(self):
        for key, expected in ((Qt.Key.Key_Return, QDialog.DialogCode.Accepted),
                              (Qt.Key.Key_Escape, QDialog.DialogCode.Rejected)):
            dialog = UpdateDialog(self.window)
            dialog.show()
            self.app.processEvents()
            dialog.checker.ready.emit(Release(__version__, "", False))
            QTest.keyClick(dialog, key)
            self.assertEqual(dialog.result(), expected)
            self.assertIsNone(dialog._shade)


class UpdateCheckerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_versions_compare_numerically_and_never_offer_downgrades(self):
        for tag, current, newer in (("v0.10.0", "0.9.0", True),
                                    ("1.0.0", "1.0.0", False),
                                    ("v0.1.0", "0.2.0", False)):
            result = parse_release(json.dumps({"tag_name": tag}), current)
            self.assertEqual(result.newer, newer)
            self.assertEqual(result.url, "https://github.com/mio-1/PickLight/releases/tag/" + tag)

    def test_invalid_and_unpublished_releases_are_rejected(self):
        for data in ([], {}, {"tag_name": "v0.2.0-beta.1"},
                     {"tag_name": "v0.2.0", "draft": True},
                     {"tag_name": "v0.2.0", "prerelease": True}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                parse_release(json.dumps(data))

    def test_network_response_errors_and_cancel(self):
        class Reply(QObject):
            finished = Signal()

            def __init__(self, status, data, error):
                super().__init__()
                self.status, self.data, self.failure = status, data, error
                self.aborted = False

            def attribute(self, _attribute):
                return self.status

            def error(self):
                return self.failure

            def readAll(self):
                return self.data

            def abort(self):
                self.aborted = True
                self.finished.emit()

        for status, data, error, expected in (
                (200, b'{"tag_name":"v0.2.0"}', QNetworkReply.NetworkError.NoError, "ready"),
                (200, b'broken', QNetworkReply.NetworkError.NoError, "暂不可用"),
                (404, b'', QNetworkReply.NetworkError.ContentNotFoundError, "正式版本"),
                (403, b'', QNetworkReply.NetworkError.ContentAccessDenied, "过于频繁"),
                (0, b'', QNetworkReply.NetworkError.TimeoutError, "网络"),
                (200, b'{}', QNetworkReply.NetworkError.NoError, "cancel")):
            with self.subTest(status=status, expected=expected):
                checker = UpdateChecker()
                reply = Reply(status, data, error)
                ready, failed = [], []
                checker.ready.connect(ready.append)
                checker.failed.connect(failed.append)
                with patch.object(checker.network, "get", return_value=reply) as get:
                    checker.check()
                    checker.check()
                    get.assert_called_once()
                    request = get.call_args.args[0]
                    self.assertEqual(request.transferTimeout(), 15000)
                    self.assertEqual(request.url().scheme(), "https")
                    self.assertFalse(request.hasRawHeader("Authorization"))
                    if expected == "cancel":
                        checker.cancel()
                        self.assertTrue(reply.aborted)
                        self.assertEqual(ready + failed, [])
                    else:
                        reply.finished.emit()
                        if expected == "ready":
                            self.assertEqual(len(ready), 1)
                            self.assertEqual(failed, [])
                        else:
                            self.assertEqual(ready, [])
                            self.assertIn(expected, failed[0])
                    self.assertIsNone(checker.reply)
