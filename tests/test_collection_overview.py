"""Sidebar categories show their own summary until a photo is explicitly selected."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from picklight.window import MainWindow


class CollectionOverviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        override = patch.dict(os.environ, {"PICKLIGHT_SETTINGS": str(self.root / "settings.json")})
        override.start()
        self.addCleanup(override.stop)
        self.window = MainWindow(restore_project=False)
        self.window.show()
        self.addCleanup(self.window.close)
        self.app.processEvents()

    def photos(self):
        source = self.root / "photos"
        source.mkdir()
        image = QImage(64, 48, QImage.Format.Format_RGB32)
        image.fill("#526e7d")
        for name in ("one.jpg", "two.jpg"):
            self.assertTrue(image.save(str(source / name)))
        self.window.open_project(source)
        self.window.ratings[self.window.pairs[0].key] = 4
        return source

    def assert_summary(self, title, count, size):
        w = self.window
        self.assertIs(w.inspector_stack.currentWidget(), w.collection_inspector)
        self.assertEqual(w.collection_inspector_name.text(), title)
        self.assertTrue(w.collection_inspector_name.isReadOnly())
        self.assertEqual(w.collection_inspector_count.text(), str(count))
        self.assertEqual(w.collection_inspector_size.text(), w._folder_size_text(size))

    def test_no_folders_defaults_to_all_and_empty_categories_have_zero_summaries(self):
        w = self.window
        self.assertTrue(w.sidebar_nav["all"].active)
        self.assert_summary("全部", 0, 0)
        fields = [label.text() for label in w.collection_inspector.findChildren(QLabel)
                  if label.objectName() == "detailKey"]
        self.assertEqual(fields, ["文件数", "占用空间"])
        for view, title in (("rated", "已评分"), ("marked", "待删除"), ("all", "全部")):
            w.sidebar_nav[view].click()
            self.assertTrue(w.sidebar_nav[view].active)
            self.assert_summary(title, 0, 0)
        self.assertEqual(w.store.projects(), [])

    def test_category_totals_follow_filters_and_clicking_photo_opens_details(self):
        w = self.window
        source = self.photos()
        w.sidebar_nav["all"].click()
        self.assert_summary("全部", 2, sum(path.stat().st_size for path in source.iterdir()))
        w.sidebar_nav["rated"].click()
        self.assert_summary("已评分", 1, (source / "one.jpg").stat().st_size)
        self.app.processEvents()
        rect = w.filmstrip.visualItemRect(w.filmstrip.item(0))
        QTest.mouseClick(w.filmstrip.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
        self.assertIs(w.inspector_stack.currentWidget(), w.inspector_scroll)
        self.assertEqual(w.info_name.text(), "one.jpg")
        w.sidebar_nav["all"].click()
        self.assert_summary("全部", 2, sum(path.stat().st_size for path in source.iterdir()))

    def test_empty_search_and_clear_keep_category_summary_in_sync(self):
        w = self.window
        source = self.photos()
        w.sidebar_nav["rated"].click()
        w._search_photos("does-not-match")
        self.assert_summary("已评分", 0, 0)
        w._search_photos("")
        self.assert_summary("已评分", 1, (source / "one.jpg").stat().st_size)
        w.sidebar_nav["marked"].click()
        self.assert_summary("待删除", 0, 0)

    def test_no_folders_clears_stale_folder_selection_and_returns_to_all(self):
        w = self.window
        w._sidebar_selection = "folder"
        w.filters.rating_min = 1
        w._show_empty()
        self.assertTrue(w.sidebar_nav["all"].active)
        self.assertFalse(w.filters.active)
        self.assert_summary("全部", 0, 0)
