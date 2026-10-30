"""Local update placeholder matches the modal flow without claiming an online check."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from picklight import __version__
from picklight.theme import STYLE
from picklight.update_dialog import UpdateDialog
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

    def test_local_version_modal_centers_and_confirmation_removes_backdrop_without_network(self):
        with patch("socket.create_connection", side_effect=AssertionError("Unexpected network request")):
            dialog = UpdateDialog(self.window)
            dialog.show()
            self.app.processEvents()
            self.assertIn(__version__, dialog.message.text())
            self.assertIn("暂未开放", dialog.message.text())
            self.assertNotIn("最新版本", dialog.message.text())
            self.assertEqual(dialog.geometry().center(), self.window.mapToGlobal(self.window.rect().center()))
            self.assertTrue(dialog.isModal())
            self.assertIsNotNone(dialog._shade)
            QTest.mouseClick(dialog.confirm_button, Qt.MouseButton.LeftButton)
            self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
            self.assertIsNone(dialog._shade)
            self.assertFalse(dialog.isVisible())

    def test_enter_confirms_and_escape_dismisses(self):
        for key, expected in ((Qt.Key.Key_Return, QDialog.DialogCode.Accepted),
                              (Qt.Key.Key_Escape, QDialog.DialogCode.Rejected)):
            dialog = UpdateDialog(self.window)
            dialog.show()
            self.app.processEvents()
            QTest.keyClick(dialog, key)
            self.assertEqual(dialog.result(), expected)
            self.assertIsNone(dialog._shade)
