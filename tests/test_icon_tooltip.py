"""Icon tooltips follow their target without stealing focus or lingering."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QHelpEvent
from PySide6.QtWidgets import QApplication

from picklight.window import MainWindow


class IconTooltipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_help_event_shows_compact_tooltip_and_leave_hides_it(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
                "PICKLIGHT_SETTINGS": str(Path(directory) / "settings.json")}):
            window = MainWindow(restore_project=False)
            self.addCleanup(window.close)
            window.show()
            self.app.processEvents()
            self.assertEqual(window.menu_button.toolTip(), "")
            self.assertEqual(window.sidebar_toggle.toolTip(), "左栏")
            self.assertEqual(window.filter_button.toolTip(), "筛选")
            self.assertEqual(window.grid_button.toolTip(), "布局方式")
            window._toggle_filter_bar(True)
            window._set_gallery_layout("grid")
            self.assertEqual(window.filter_button.toolTip(), "筛选")
            self.assertEqual(window.grid_button.toolTip(), "布局方式")
            button = window.grid_button
            event = QHelpEvent(QEvent.Type.ToolTip, button.rect().center(),
                               button.mapToGlobal(button.rect().center()))
            QApplication.sendEvent(button, event)
            self.app.processEvents()
            tooltip = window._icon_tooltip
            self.assertTrue(tooltip.isVisible())
            self.assertEqual(tooltip.label.text(), button.toolTip())
            self.assertEqual(tooltip.height(), 26)
            self.assertGreaterEqual(tooltip.label.width(),
                                    tooltip.label.fontMetrics().boundingRect(button.toolTip()).width())
            self.assertEqual(tooltip.label.alignment(), Qt.AlignmentFlag.AlignCenter)
            self.assertLessEqual(abs(tooltip.label.x() -
                                     (tooltip.width() - tooltip.label.geometry().right() - 1)), 1)
            QApplication.sendEvent(button, QEvent(QEvent.Type.Leave))
            self.assertFalse(tooltip.isVisible())
