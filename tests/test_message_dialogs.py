"""Warnings and input prompts use the same modal surface as folder deletion."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit

from picklight.folder_dialogs import DeleteFolderDialog, InputDialog, NoticeDialog
from picklight.theme import STYLE
from picklight.update_dialog import UpdateDialog
from picklight.window import MainWindow


class MessageDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(STYLE)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        environment = patch.dict(os.environ, {"PICKLIGHT_SETTINGS": str(Path(temporary.name) / "settings.json")})
        environment.start()
        self.addCleanup(environment.stop)
        self.window = MainWindow(restore_project=False)
        self.window.show()
        self.addCleanup(self.window.close)
        self.app.processEvents()

    def test_notices_share_folder_surface_and_show_plain_message(self):
        deletion = DeleteFolderDialog("folder", self.window)
        notice = NoticeDialog("无法关联文件夹", '目录已关联至“<sample>”', self.window)
        update = UpdateDialog(self.window)
        self.addCleanup(update.close)
        self.assertEqual(update.surface.objectName(), "updateSurface")
        for dialog in (deletion, notice):
            self.addCleanup(dialog.close)
            self.assertEqual(dialog.surface.objectName(), "folderModalSurface")
            self.assertEqual(dialog.width(), 400)
        notice.show()
        self.app.processEvents()
        self.assertEqual(notice.message.textFormat(), Qt.TextFormat.PlainText)
        self.assertTrue(notice.message.wordWrap())
        self.assertIsNotNone(notice._shade)
        QTest.keyClick(notice, Qt.Key.Key_Return)
        self.assertEqual(notice.result(), QDialog.DialogCode.Accepted)
        self.assertIsNone(notice._shade)

    def test_unparented_startup_notice_and_rename_input(self):
        notice = NoticeDialog("无法启动", "测试", None)
        notice.show()
        self.app.processEvents()
        self.assertTrue(notice.isVisible())
        notice.close()

        def enter_name():
            dialog = self.app.activeModalWidget()
            self.assertEqual(dialog.surface.objectName(), "folderModalSurface")
            field = dialog.findChild(QLineEdit)
            field.setText("新名称")
            dialog.accept()

        QTimer.singleShot(0, enter_name)
        value, accepted = InputDialog.getText(self.window, "重命名文件夹", "文件夹名称：", text="旧名称")
        self.assertTrue(accepted)
        self.assertEqual(value, "新名称")
