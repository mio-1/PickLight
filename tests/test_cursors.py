"""Canvas uses an open hand everywhere and a closed hand while pressed."""

import unittest
from unittest.mock import patch
from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QEnterEvent, QImage, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from picklight.ui.cursors import cursor_pixmap, system_cursor_size
from picklight.viewer import LoupeCanvas


class LoupeCursorBoundsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.canvas = LoupeCanvas()
        self.addCleanup(self.canvas.close)
        self.canvas.resize(600, 400)
        self.image = QImage(200, 300, QImage.Format.Format_RGB32)
        self.image.fill("#405e72")
        self.canvas.set_image(self.image)

    def move(self, position, buttons=Qt.MouseButton.NoButton):
        point = QPointF(position)
        event = QMouseEvent(QEvent.Type.MouseMove, point, QPointF(self.canvas.mapToGlobal(point.toPoint())), Qt.MouseButton.NoButton,
                            buttons, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(self.canvas, event)

    def test_review_marks_never_cover_or_darken_the_photo(self):
        original = self.canvas.grab().toImage()
        for state in ("keep", "reject", ""):
            self.canvas.set_decision_state(state)
            for hovered in (False, True):
                self.canvas.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, hovered)
                self.assertEqual(self.canvas.grab().toImage(), original)

    def assert_hand(self, closed=False):
        ratio = self.canvas.devicePixelRatioF()
        expected = cursor_pixmap("cursor.grabbing" if closed else "cursor.grab", system_cursor_size(ratio), ratio, crisp=True)
        self.assertEqual(self.canvas.cursor().pixmap().toImage(), expected.toImage())

    def test_photo_and_surrounding_blank_both_start_drag(self):
        self.assert_hand()
        blank = QPoint(30, 200)
        center = QPoint(300, 200)
        self.move(blank)
        self.assert_hand()
        QTest.mousePress(self.canvas, Qt.MouseButton.LeftButton, pos=blank)
        self.assertTrue(self.canvas._dragging)
        self.assert_hand(closed=True)
        self.move(blank + QPoint(10, 0), Qt.MouseButton.LeftButton)
        self.assertEqual(self.canvas.pan, QPointF(10, 0))
        QTest.mouseRelease(self.canvas, Qt.MouseButton.LeftButton, pos=blank)
        self.move(center)
        self.assert_hand()
        QTest.mousePress(self.canvas, Qt.MouseButton.LeftButton, pos=center)
        self.assert_hand(closed=True)
        self.move(center + QPoint(20, 10), Qt.MouseButton.LeftButton)
        self.assertEqual(self.canvas.pan, QPointF(30, 10))
        QTest.mouseRelease(self.canvas, Qt.MouseButton.LeftButton, pos=center + QPoint(20, 10))
        self.assert_hand()
        self.move(blank)
        self.assert_hand()

    def test_hand_is_unchanged_by_rotation_zoom_and_loading(self):
        self.move(QPoint(410, 200))
        self.assert_hand()
        self.canvas.rotate_clockwise()
        self.assert_hand()
        self.canvas.set_zoom(0.2)
        self.assert_hand()
        self.canvas.fit_to_canvas()
        self.assert_hand()
        self.canvas.begin_image("another-photo")
        self.assert_hand()
        self.canvas.set_image(self.image)
        self.assert_hand()
        self.move(QPoint(300, 200))
        self.assert_hand()
        self.canvas.set_message("无法显示预览")
        self.assert_hand()

    def test_drag_outside_canvas_can_finish_and_reenter(self):
        self.canvas.set_zoom(3)
        center = QPoint(300, 200)
        outside = QPoint(-10, 200)
        self.move(center)
        QTest.mousePress(self.canvas, Qt.MouseButton.LeftButton, pos=center)
        self.assert_hand(closed=True)
        self.move(outside, Qt.MouseButton.LeftButton)
        self.assertTrue(self.canvas._dragging)
        self.assert_hand(closed=True)
        QTest.mouseRelease(self.canvas, Qt.MouseButton.LeftButton, pos=outside)
        self.assertFalse(self.canvas._dragging)
        self.assert_hand()
        position = self.canvas.image_rect().intersected(QRectF(self.canvas.rect())).center()
        QApplication.sendEvent(self.canvas, QEnterEvent(position, position, position))
        self.assert_hand()
        QApplication.sendEvent(self.canvas, QEvent(QEvent.Type.Leave))
        self.assert_hand()

    def test_movement_never_replaces_cursor_or_emits_pan_zoom_notifications(self):
        zoom_notifications = []
        self.canvas.zoomChanged.connect(zoom_notifications.append)
        with patch.object(self.canvas, "setCursor", wraps=self.canvas.setCursor) as apply:
            for x in range(220, 380):
                self.move(QPoint(x, 200))
            self.assertEqual(apply.call_count, 0)
            self.assert_hand()
            for x in range(10, 50):
                self.move(QPoint(x, 200))
            self.assertEqual(apply.call_count, 0)
            self.assert_hand()
            QTest.mousePress(self.canvas, Qt.MouseButton.LeftButton, pos=QPoint(300, 200))
            self.assertEqual(apply.call_count, 1)
            self.assert_hand(closed=True)
            for x in range(310, 350):
                self.move(QPoint(x, 200), Qt.MouseButton.LeftButton)
            self.assertEqual(apply.call_count, 1)
            self.assertEqual(zoom_notifications, [])
            QTest.mouseRelease(self.canvas, Qt.MouseButton.LeftButton, pos=QPoint(300, 200))
            self.assertEqual(apply.call_count, 2)
            self.assert_hand()
            self.canvas.set_zoom(0.8)
            self.assertEqual(zoom_notifications, [0.8])

    def test_enter_and_density_change_keep_open_hand(self):
        position = QPointF(300, 200)
        QApplication.sendEvent(self.canvas, QEnterEvent(position, position, position))
        QApplication.sendEvent(self.canvas, QEvent(QEvent.Type.DevicePixelRatioChange))
        self.assert_hand()

    def test_pressed_hand_survives_density_change_and_resets_when_loading(self):
        center = QPoint(300, 200)
        QTest.mousePress(self.canvas, Qt.MouseButton.LeftButton, pos=center)
        with patch.object(self.canvas, "devicePixelRatioF", return_value=1.5):
            QApplication.sendEvent(self.canvas, QEvent(QEvent.Type.DevicePixelRatioChange))
            self.assert_hand(closed=True)
            self.canvas.begin_image("next")
            self.assert_hand()
        QTest.mouseRelease(self.canvas, Qt.MouseButton.LeftButton, pos=center)
        self.assert_hand()

    def test_blank_drag_continues_beyond_canvas_and_stops_on_release(self):
        start = QPoint(30, 200)
        outside = QPoint(-50, 220)
        QTest.mousePress(self.canvas, Qt.MouseButton.LeftButton, pos=start)
        self.move(outside, Qt.MouseButton.LeftButton)
        self.assertEqual(self.canvas.pan, QPointF(-80, 20))
        self.assert_hand(closed=True)
        QTest.mouseRelease(self.canvas, Qt.MouseButton.LeftButton, pos=outside)
        self.move(QPoint(50, 250))
        self.assertEqual(self.canvas.pan, QPointF(-80, 20))
        self.assertFalse(self.canvas._dragging)
        self.assert_hand()

    def test_loading_or_failed_image_cannot_be_panned(self):
        self.canvas.set_message("无法显示预览")
        QTest.mousePress(self.canvas, Qt.MouseButton.LeftButton, pos=QPoint(30, 200))
        self.move(QPoint(80, 250), Qt.MouseButton.LeftButton)
        self.assertFalse(self.canvas._dragging)
        self.assertEqual(self.canvas.pan, QPointF())
        QTest.mouseRelease(self.canvas, Qt.MouseButton.LeftButton, pos=QPoint(80, 250))
        self.assert_hand()
