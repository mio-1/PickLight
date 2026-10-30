"""Compact picker input, popup integration and sampled-color delivery."""

import unittest
from unittest.mock import patch

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from picklight.ui.color_picker import ColorPickerPopup, SamplingOverlay
from picklight.ui.visual_filters import ColorFilterPanel


class ColorPickerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.panel = ColorFilterPanel()
        self.panel.show()
        self.addCleanup(self.panel.close)

    def test_rgb_hsl_hex_and_plane_update_filter_without_system_dialog(self):
        self.panel._open_color_dialog()
        popup = self.panel.color_popup
        self.addCleanup(popup.close)
        self.assertTrue(popup.isVisible())
        for field, value in zip(popup.fields, (32, 100, 200)):
            field.setText(str(value))
        popup._fields_changed()
        self.assertEqual(self.panel.current, "#2064C8")
        popup._switch_mode()
        self.assertEqual(popup.mode_button.mode, "HSL")
        popup._switch_mode()
        popup.fields[0].setText("#30D159")
        popup._fields_changed()
        self.assertEqual(self.panel.current, "#30D159")
        popup._switch_mode()
        self.assertEqual([field.text() for field in popup.fields], ["48", "209", "89"])
        QTest.mouseClick(popup.plane, Qt.MouseButton.LeftButton, pos=QPoint(1, 1))
        self.assertGreater(min(QColor(self.panel.current).getRgb()[:3]), 250)
        QTest.keyClick(popup, Qt.Key.Key_Escape)
        self.assertFalse(popup.isVisible())

    def test_hue_and_rgb_stay_in_sync_and_sampling_cancel_keeps_color(self):
        popup = ColorPickerPopup(self.panel, QColor("#ff0000"))
        self.addCleanup(popup.close)
        popup._hue_changed(1 / 3)
        self.assertEqual(popup.color.name(), "#00ff00")
        popup._sample_finished(QColor())
        self.assertEqual(popup.color.name(), "#00ff00")
        popup._sample_finished(QColor("#123456"))
        self.assertEqual([field.text() for field in popup.fields], ["18", "52", "86"])

    def test_sampling_uses_logical_to_image_pixel_mapping(self):
        image = QImage(40, 40, QImage.Format.Format_RGB32)
        image.fill(QColor("#abcdef"))
        screen = self.app.primaryScreen()
        owner = unittest.mock.Mock()
        overlay = SamplingOverlay(owner, screen, QPixmap.fromImage(image))
        self.addCleanup(overlay.close)
        overlay.resize(20, 20)
        overlay.show()
        QTest.mouseClick(overlay, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
        self.assertEqual(owner.finish.call_args.args[0].name(), "#abcdef")
