"""Color extraction, transparent pixels and inspector hover behavior."""

import unittest

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QColor, QHelpEvent, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from picklight.palette import PaletteColor, display_palette, extract_palette
from picklight.ui.palette import PaletteStrip


class PaletteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_color_ratios_exclude_transparent_pixels(self):
        image = QImage(100, 100, QImage.Format.Format_RGBA8888)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.fillRect(0, 0, 60, 100, QColor("#ff0000"))
        painter.fillRect(60, 0, 20, 100, QColor("#0000ff"))
        painter.end()
        colors = extract_palette(image)
        self.assertEqual([color.ratio for color in colors], [75.0, 25.0])
        self.assertGreater(colors[0].rgb[0], 248)
        self.assertGreater(colors[1].rgb[2], 248)
        self.assertEqual(extract_palette(QImage()), [])
        image.fill(Qt.GlobalColor.transparent)
        self.assertEqual(extract_palette(image), [])

    def test_palette_display_keeps_dominant_color_and_limits_swatches(self):
        colors = [PaletteColor((20 * index, 15 * index, 10 * index), 20 - index)
                  for index in range(12)]
        shown = display_palette(colors)
        self.assertEqual(len(shown), 10)
        self.assertEqual(shown[0], colors[0])
        self.assertEqual(set(shown), set(colors[:10]))

    def test_color_swatches_show_hex_ratio_and_dismiss_stale_tip(self):
        strip = PaletteStrip()
        self.addCleanup(strip.close)
        strip.set_colors([PaletteColor((95, 124, 162), 0.6), PaletteColor((10, 15, 20), 99.4)])
        strip.show()
        self.app.processEvents()
        QTest.mouseMove(strip, QPoint(33, 14))
        self.app.processEvents()
        self.assertEqual(strip.hovered, 1)
        point = QPoint(33, 14)
        QApplication.sendEvent(strip, QHelpEvent(QEvent.Type.ToolTip, point, strip.mapToGlobal(point)))
        self.assertTrue(strip._tooltip.isVisible())
        self.assertEqual(strip._tooltip.label.text(), "#5F7CA2 (0.6%)")
        QTest.mouseMove(strip, QPoint(15, 14))
        self.app.processEvents()
        self.assertEqual(strip._tooltip.label.text(), "#0A0F14 (99.4%)")
        QApplication.sendEvent(strip, QEvent(QEvent.Type.Leave))
        self.assertFalse(strip._tooltip.isVisible())
        strip.set_colors([PaletteColor((255, 0, 0), 100)])
        self.assertFalse(strip._tooltip.isVisible())
        self.assertFalse(strip.isHidden())
        strip.set_colors([])
        self.assertEqual(strip.colors, [])

    def test_empty_palette_reserves_its_space_before_colors_arrive(self):
        container = QWidget()
        self.addCleanup(container.close)
        layout = QVBoxLayout(container)
        strip = PaletteStrip()
        details = QLabel("照片详情")
        layout.addWidget(strip)
        layout.addWidget(details)
        container.show()
        self.app.processEvents()
        position = details.y()
        size = strip.size()
        self.assertTrue(strip.isVisible())
        for colors in ([PaletteColor((255, 0, 0), 60), PaletteColor((0, 0, 255), 40)],
                       [], [PaletteColor((0, 255, 0), 100)]):
            strip.set_colors(colors)
            self.app.processEvents()
            self.assertEqual(details.y(), position)
            self.assertEqual(strip.size(), size)
            self.assertTrue(strip.isVisible())
