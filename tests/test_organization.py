"""Catalog comparison, filtering, and source-state workflows."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication



class OrganizationWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from picklight.window import MainWindow
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        environment = patch.dict(os.environ, {"PICKLIGHT_SETTINGS": str(self.root / "settings.json")})
        environment.start()
        self.addCleanup(environment.stop)
        source = self.root / "photos"
        source.mkdir()
        for index in range(4):
            image = QImage(300 + 20 * index, 200, QImage.Format.Format_RGB32)
            image.fill("#527e9a")
            image.save(str(source / f"{index}.jpg"))
        self.window = MainWindow(restore_project=False)
        self.window.open_project(source)
        self.window.show()
        self.addCleanup(self.window.close)
        errors = []
        hook = patch("sys.excepthook", lambda *error: errors.append(error))
        hook.start()
        self.addCleanup(hook.stop)
        self.addCleanup(lambda: self.assertFalse(errors, errors))
        self.app.processEvents()

    def test_comparison_links_views_but_decisions_remain_independent(self):
        from picklight.comparison import ComparisonDialog
        w = self.window
        pairs = w.visible[:2]
        dialog = ComparisonDialog(pairs, w)
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.reject)
        image = QImage(300, 200, QImage.Format.Format_RGB32)
        image.fill("#527e9a")
        for tile in dialog.tiles:
            tile.canvas.set_image(image)
        dialog.tiles[0].canvas.set_zoom(1.5)
        self.assertEqual(dialog.tiles[1].canvas.zoom, 1.5)
        dialog.link.setChecked(False)
        dialog.tiles[0].canvas.set_zoom(2)
        self.assertEqual(dialog.tiles[1].canvas.zoom, 1.5)
        w._mark_comparison_photo(pairs[0], "keep")
        self.assertIn(pairs[0].key, w.kept)
        self.assertNotIn(pairs[1].key, w.kept)
        with patch.object(w.batch_rating_loader, "load") as load:
            w._rate_comparison_photo(pairs[1], 4)
            load.assert_called_once_with([pairs[1]], 4)

    def test_renamed_files_migrate_decisions_without_overwriting_swapped_states(self):
        w = self.window
        first, second = w.visible[:2]
        w.kept.add(first.key)
        w.marked.add(second.key)
        mapping = {first.jpg: second.jpg, second.jpg: first.jpg}
        with patch.object(w.source_monitor, "refresh"):
            w._photo_files_finished(({first.jpg: (), second.jpg: ()}, mapping, []))
        self.assertEqual(w.store.data["photo_decisions"][w.store.photo_path_key(second.jpg)], "keep")
        self.assertEqual(w.store.data["photo_decisions"][w.store.photo_path_key(first.jpg)], "reject")

    def test_clear_search_filter_leaves_collection_category_active(self):
        w = self.window
        w._open_sidebar_view("all")
        w.filters.path_contains = "0"
        w.filters.search_scopes = {"name"}
        w._apply_filter()
        self.assertFalse(w.sidebar_nav["all"].active)
        w._clear_filters()
        self.assertEqual(len(w.visible), 4)
        self.assertTrue(w.sidebar_nav["all"].active)
