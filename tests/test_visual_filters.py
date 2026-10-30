"""Exact rating alternatives, color matching and picker input behavior."""

import unittest
from pathlib import Path

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from picklight.filters import PhotoFilter
from picklight.library import PhotoPair
from picklight.palette import PaletteColor
from picklight.ui.visual_filters import ColorFilterPanel, RatingFilterPanel


class VisualFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_ratings_are_alternatives_and_combine_with_color(self):
        pair = PhotoPair("photo", Path("photo.JPG"), None)
        filters = PhotoFilter(rating_values={3, 4}, color_rgb=(255, 39, 39))
        red = [PaletteColor((252, 4, 4), 100)]
        blue = [PaletteColor((4, 4, 252), 100)]
        self.assertTrue(filters.matches(pair, 3, False, palettes=red))
        self.assertTrue(filters.matches(pair, 4, False, palettes=red))
        self.assertFalse(filters.matches(pair, 2, False, palettes=red))
        self.assertFalse(filters.matches(pair, 4, False, palettes=blue))
        self.assertTrue(filters.matches(pair, 0, False, except_facet="rating", palettes=red))
        filters.clear()
        self.assertFalse(filters.active)
        filters.color_gray = True
        self.assertTrue(filters.matches(pair, 0, False, palettes=[PaletteColor((110, 115, 112), 100)]))
        self.assertFalse(filters.matches(pair, 0, False, palettes=red))

    def test_color_picker_hex_presets_and_clear(self):
        panel = ColorFilterPanel()
        self.addCleanup(panel.close)
        values = []
        panel.colorChanged.connect(values.append)
        panel.show()
        panel.presets["#FFD534"].click()
        self.assertEqual(values[-1], "#FFD534")
        panel.hex_edit.selectAll()
        QTest.keyClicks(panel.hex_edit, "#30D159")
        QTest.qWait(160)
        self.assertEqual(values[-1], "#30D159")
        panel.presets["gray"].click()
        self.assertEqual(values[-1], "gray")
        panel.presets[""].click()
        self.assertEqual(values[-1], "")

    def test_rating_menu_keeps_selected_zero_count_rows(self):
        panel = RatingFilterPanel()
        self.addCleanup(panel.close)
        panel.set_counts({4: 1, 0: 6}, {4, 3})
        self.assertFalse(panel.rows[3].isHidden())
        self.assertEqual(panel.rows[3].count, 0)
        self.assertTrue(panel.rows[4].isChecked())
        self.assertTrue(panel.rows[3].isChecked())
        self.assertTrue(panel.rows[5].isHidden())
        self.assertEqual(panel.height(), 84)
