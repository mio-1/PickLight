"""JPG-only, RAW-only and paired-photo format filtering."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QMenu, QWidgetAction

from picklight.filters import PhotoFilter
from picklight.library import PhotoPair
from picklight.ui.visual_filters import FormatFilterPanel
from picklight.window import MainWindow


class FormatFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_modes_are_three_disjoint_pairing_states(self):
        paired = PhotoPair("paired", Path("paired.JPG"), Path("paired.ARW"))
        jpg = PhotoPair("jpg", Path("only.JPG"), None)
        raw = PhotoPair("raw", None, Path("only.NEF"))
        filters = PhotoFilter()
        pairs = [paired, jpg, raw]
        self.assertTrue(all(filters.matches(pair, 0, False) for pair in pairs))
        for mode, expected in (("jpg", jpg), ("raw", raw), ("both", paired)):
            filters.format_mode = mode
            self.assertEqual([pair for pair in pairs if filters.matches(pair, 0, False)], [expected])
            self.assertTrue(filters.active)
            self.assertTrue(all(filters.matches(pair, 0, False, except_facet="format") for pair in pairs))
        self.assertEqual(filters.paths(paired), (paired.jpg, paired.raw))
        filters.clear()
        self.assertIsNone(filters.format_mode)
        self.assertFalse(filters.active)

    def test_raw_covers_all_supported_extensions_and_composes_with_other_facets(self):
        filters = PhotoFilter(format_mode="raw", rating_values={4}, states={"keep"})
        for extension in ("arw", "CR3", "nef", "RAF", "dng"):
            pair = PhotoPair(extension, None, Path("shot." + extension))
            self.assertTrue(filters.matches(pair, 4, False, kept=True))
            self.assertEqual(filters.paths(pair), (pair.raw,))
            self.assertFalse(filters.matches(pair, 3, False, kept=True))
            self.assertFalse(filters.matches(pair, 4, True, kept=True))
        filters.path_contains = ".jpg"
        self.assertFalse(filters.matches(pair, 4, False, kept=True))

    def test_popup_has_three_exclusive_rows_no_search_and_ignores_right_click(self):
        panel = FormatFilterPanel()
        self.addCleanup(panel.close)
        counts = {"jpg": 2, "raw": 1, "both": 3}
        panel.set_counts(counts, None)
        panel.show()
        self.app.processEvents()
        self.assertEqual(list(panel.rows), ["jpg", "raw", "both"])
        self.assertEqual([row.title for row in panel.rows.values()], ["仅有 JPG", "仅有 RAW", "JPG+RAW 配对"])
        self.assertFalse(panel.findChildren(QLineEdit))
        choices = []
        def selected(mode):
            choices.append(mode)
            panel.set_counts(counts, mode)
        panel.formatSelected.connect(selected)
        for mode in ("jpg", "raw", "both", "both"):
            QTest.mouseClick(panel.rows[mode], Qt.MouseButton.LeftButton)
            self.assertEqual([key for key, row in panel.rows.items() if row.isChecked()], [mode])
        QTest.mouseClick(panel.rows["raw"], Qt.MouseButton.RightButton)
        self.assertEqual(choices, ["jpg", "raw", "both", "both"])
        self.assertTrue(panel.rows["both"].isChecked())
        panel.set_counts({}, None)
        self.assertTrue(all(not row.isHidden() for row in panel.rows.values()))
        self.assertFalse(any(row.isChecked() for row in panel.rows.values()))

    def test_popup_fits_all_rows_and_closes_after_selection(self):
        menu = QMenu()
        self.addCleanup(menu.close)
        panel = FormatFilterPanel()
        action = QWidgetAction(menu)
        action.setDefaultWidget(panel)
        menu.addAction(action)
        menu.show()
        self.app.processEvents()
        for row in panel.rows.values():
            self.assertTrue(menu.rect().contains(row.mapTo(menu, row.rect().bottomRight())))
        QTest.mouseClick(panel.rows["jpg"], Qt.MouseButton.LeftButton)
        self.assertFalse(menu.isVisible())

    def test_workspace_switches_pairing_states_and_clear_restores_all(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
                "PICKLIGHT_SETTINGS": directory + "/settings.json"}):
            root = Path(directory) / "photos"
            root.mkdir()
            image = QImage(64, 48, QImage.Format.Format_RGB32)
            image.fill("#526e7d")
            image.save(str(root / "one.JPG"))
            image.save(str(root / "two.JPG"))
            (root / "one.ARW").write_bytes(b"raw metadata fixture")
            (root / "three.NEF").write_bytes(b"raw metadata fixture")
            w = MainWindow(restore_project=False)
            try:
                w.open_project(root)
                with patch.object(w.loader, "request"), patch.object(w.details_loader, "request"):
                    for mode, filename in (("raw", "three.NEF"), ("jpg", "two.JPG"), ("both", "one.JPG")):
                        w._set_format_filter(mode)
                        self.assertEqual(len(w.visible), 1)
                        self.assertEqual(w.filmstrip.item(0).text(), filename)
                        self.assertEqual(w._current_preview_path(), root / filename)
                        self.assertEqual(w.filter_badge.text(), "1")
                        self.assertEqual([key for key, row in w.format_facet.rows.items() if row.isChecked()], [mode])
                    self.assertEqual([row.count for row in w.format_facet.rows.values()], [1, 1, 1])
                    w._clear_visual_facet("format")
                    self.assertEqual(len(w.visible), 3)
                    self.assertIsNone(w.filters.format_mode)
                    self.assertFalse(w.filters.active)
            finally:
                w.close()
