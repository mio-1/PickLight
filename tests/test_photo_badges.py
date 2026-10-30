"""Transparent photo marks rendered at the target display density."""

import unittest

from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from picklight.ui.graphics import paint_photo_state, photo_state_pixmap


class PhotoBadgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_marks_have_no_backplate_at_supported_display_scales(self):
        for ratio in (1, 1.25, 1.5, 2):
            for state in ("keep", "reject"):
                with self.subTest(ratio=ratio, state=state):
                    image = QImage(round(100 * ratio), round(80 * ratio), QImage.Format.Format_ARGB32_Premultiplied)
                    image.setDevicePixelRatio(ratio)
                    image.fill(0)
                    painter = QPainter(image)
                    paint_photo_state(painter, QRectF(0, 0, 100, 80), state)
                    painter.end()
                    for x, y in ((7, 60), (34, 60), (21, 46)):
                        self.assertEqual(image.pixelColor(round(x * ratio), round(y * ratio)).alpha(), 0)
                    pixels = sum(image.pixelColor(x, y).alpha() > 0
                                 for y in range(image.height()) for x in range(image.width()))
                    self.assertGreater(pixels, 10)
                    self.assertLess(pixels, 250 * ratio * ratio)
                    icon = photo_state_pixmap(state, 24, badge=True, device_ratio=ratio)
                    self.assertEqual(icon.width(), round(24 * ratio))
                    self.assertEqual(icon.devicePixelRatioF(), ratio)
