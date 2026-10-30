"""Regression checks for responsive layout, scrolling and cached photo selection."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QImage, QPixmap, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from picklight.library import PhotoPair
from picklight.ui.gallery import PhotoGrid
from picklight.ui_motion import PageTransitionOverlay, RegionScrollVisibility
from picklight.window import MainWindow


class MotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def grid(self):
        grid = PhotoGrid()
        self.addCleanup(grid.close)
        grid.setVerticalScrollMode(PhotoGrid.ScrollMode.ScrollPerPixel)
        grid.verticalScrollBar().setRange(0, 2000)
        return grid

    def wheel(self, grid, angle=-120, pixels=0):
        event = QWheelEvent(QPointF(20, 20), QPointF(20, 20), QPoint(0, pixels),
                            QPoint(0, angle), Qt.MouseButton.NoButton,
                            Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        grid.wheelEvent(event)

    def advance(self, grid, count=1):
        for _ in range(count):
            grid._wheel_last_tick -= 0.016
            grid._advance_wheel()

    def test_continuous_wheel_keeps_velocity_and_settles_without_overshoot(self):
        grid = self.grid()
        self.wheel(grid)
        self.advance(grid, 2)
        velocity = grid._wheel_velocity
        self.assertGreater(velocity, 0)
        self.wheel(grid)
        self.assertEqual(grid._wheel_velocity, velocity)
        target = grid._wheel_target
        positions = [grid.verticalScrollBar().value()]
        for _ in range(40):
            self.advance(grid)
            positions.append(grid.verticalScrollBar().value())
        self.assertEqual(positions, sorted(positions))
        self.assertLessEqual(max(positions), target)
        self.assertEqual(positions[-1], target)
        self.assertFalse(grid._wheel_timer.isActive())

    def test_reverse_wheel_touchpad_and_manual_scroll_take_control(self):
        grid = self.grid()
        grid.verticalScrollBar().setValue(600)
        self.wheel(grid)
        self.advance(grid, 2)
        before = grid.verticalScrollBar().value()
        self.wheel(grid, angle=120)
        self.advance(grid, 2)
        self.assertLess(grid.verticalScrollBar().value(), before)
        before = grid.verticalScrollBar().value()
        self.wheel(grid, angle=0, pixels=-17)
        self.assertEqual(grid.verticalScrollBar().value(), before + 17)
        self.assertFalse(grid._wheel_timer.isActive())
        self.wheel(grid)
        grid.verticalScrollBar().setValue(350)
        self.assertFalse(grid._wheel_timer.isActive())
        self.assertEqual(grid._wheel_target, 350)

    def test_scroll_range_shrink_cannot_leave_an_animation_running(self):
        grid = self.grid()
        grid.verticalScrollBar().setValue(1900)
        self.wheel(grid)
        grid.verticalScrollBar().setRange(0, 100)
        self.advance(grid, 40)
        self.assertEqual(grid.verticalScrollBar().value(), 100)
        self.assertFalse(grid._wheel_timer.isActive())

    def test_repeated_scroll_reveal_does_not_restart_opacity_animation(self):
        grid = self.grid()
        controller = RegionScrollVisibility(grid)
        controller.reveal()
        animation = controller.animations[0]
        animation.setCurrentTime(80)
        for _ in range(20):
            controller.reveal()
        self.assertEqual(animation.currentTime(), 80)
        controller._fade(0)
        self.assertEqual(animation.startValue(), controller.effects[0].opacity())

    def test_folder_transition_replaces_previous_overlay(self):
        parent = QWidget()
        self.addCleanup(parent.close)
        snapshot = QPixmap(100, 100)
        snapshot.fill(Qt.GlobalColor.black)
        first = PageTransitionOverlay(parent, snapshot)
        first.start()
        second = PageTransitionOverlay(parent, snapshot)
        self.assertTrue(first.isHidden())
        self.assertIs(parent._page_transition, second)
        second.start()
        second.animation.setCurrentTime(second.animation.duration())
        self.assertIsNone(parent._page_transition)


class WorkspacePerformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        environment = patch.dict(os.environ, {"PICKLIGHT_SETTINGS": str(self.root / "settings.json")})
        environment.start()
        self.addCleanup(environment.stop)
        self.window = MainWindow(restore_project=False)
        self.addCleanup(self.window.close)
        self.window.resize(1400, 900)
        self.window.show()
        self.app.processEvents()
        image = QImage(180, 120, QImage.Format.Format_RGB32)
        image.fill("#405e72")
        path = self.root / "sample.jpg"
        image.save(str(path))
        self.window.pairs = [PhotoPair(str(i), path, None, False) for i in range(80)]
        self.window.pairs_by_key = {pair.key: pair for pair in self.window.pairs}
        with patch.object(self.window.loader, "request"), patch.object(self.window, "_load_current_preview"):
            self.window._apply_filter()
        self.window.center_stack.setCurrentIndex(0)
        self.app.processEvents()
        self.window._resize_grid()

    def test_backdrop_refresh_does_not_restyle_panel_children(self):
        with patch.object(self.window.browser_panel, "setStyleSheet") as left, \
                patch.object(self.window.inspector, "setStyleSheet") as right:
            self.window._refresh_preference_effects()
            left.assert_not_called()
            right.assert_not_called()

    def test_unchanged_layout_skips_all_row_positions_and_rebuild_still_works(self):
        window = self.window
        with patch.object(window.filmstrip, "setPositionForIndex", wraps=window.filmstrip.setPositionForIndex) as position:
            for _ in range(20):
                window._resize_grid()
            position.assert_not_called()
            with patch.object(window.loader, "request"), patch.object(window, "_load_current_preview"):
                window._apply_filter()
            self.assertEqual(position.call_count, len(window.visible))

    def test_resize_requests_are_coalesced_and_height_changes_update_scroll_range(self):
        window = self.window
        with patch.object(window, "_resize_grid", wraps=window._resize_grid) as layout:
            for _ in range(30):
                window._schedule_grid_resize()
            QTest.qWait(25)
            self.assertLessEqual(layout.call_count, 2)
        window.filmstrip.resize(window.filmstrip.width(), window.filmstrip.height() - 80)
        window._resize_grid()
        self.assertEqual(window.filmstrip.verticalScrollBar().maximum(),
                         max(0, window._grid_content_height - window.filmstrip.viewport().height()))

    def test_cached_hero_is_never_cleared_and_thumbnail_is_shown_while_hero_loads(self):
        window = self.window
        path = window._current_preview_path()
        image = QImage(180, 120, QImage.Format.Format_RGB32)
        image.fill("#405e72")
        window.loader.remember(str(path), 2200, image)
        with patch.object(window.preview_canvas, "set_message") as clear, patch.object(window.details_loader, "request"):
            window._load_current_preview()
            clear.assert_not_called()
            self.assertEqual(window.current_image.cacheKey(), image.cacheKey())
        window.loader.invalidate({str(path)})
        window.loader.remember(str(path), 420, image)
        with patch.object(window.loader, "request"), patch.object(window.details_loader, "request"):
            window._load_current_preview()
            self.assertEqual(window.preview_canvas.image.cacheKey(), image.cacheKey())
            self.assertIsNone(window.current_image)
            window._preview_ready(str(path), 2200, image)
            self.assertEqual(window.current_image.cacheKey(), image.cacheKey())


    def test_marking_reuses_thumbnail_and_coalesces_session_writes(self):
        window = self.window
        window.session_key = window.store.session_key(self.root)
        image = QImage(180, 120, QImage.Format.Format_RGB32)
        image.fill("#405e72")
        window.loader.remember(str(window._current_preview_path()), 420, image)
        window._paint_thumbnail(0, image)
        icon_key = window.filmstrip.item(0).icon().cacheKey()
        with patch.object(window.store, "save") as save, patch.object(window, "_paint_thumbnail") as rasterize:
            window._set_inspector_mark(False)
            self.assertIn(window.current_key, window.kept)
            self.assertTrue(window.save_timer.isActive())
            rasterize.assert_not_called()
            save.assert_not_called()
            self.assertEqual(window.filmstrip.item(0).icon().cacheKey(), icon_key)
            window._save_session()
            save.assert_called_once()
            self.assertIn(window.current_key, window.store.state_for(window.session_key)["kept"])
