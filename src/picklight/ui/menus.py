"""Compact rounded popup surfaces that retain native QMenu interaction."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QMenu

from picklight.appearance import ui_color

from picklight.paths import asset_path


class ColorManagementMenu(QMenu):
    def __init__(self, parent):
        super().__init__("色彩管理", parent)
        self.setObjectName("colorManagementMenu")
        self.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(148)
        check = asset_path("check").replace("\\", "/")
        self.setStyleSheet(f"""
            QMenu#colorManagementMenu {{
                background: transparent; border: 0; padding: 14px 10px;
            }}
            QMenu#colorManagementMenu::item {{
                background: transparent; color: #f0f0f2;
                font-family: "Segoe UI", "Microsoft YaHei UI"; font-size: 12px;
                padding: 4px 12px 4px 8px; margin: 0 4px;
                min-height: 16px; border-radius: 4px;
            }}
            QMenu#colorManagementMenu::item:selected {{ background: #303136; color: white; }}
            QMenu#colorManagementMenu::indicator {{ width: 14px; height: 14px; }}
            QMenu#colorManagementMenu::indicator:unchecked {{ image: none; }}
            QMenu#colorManagementMenu::indicator:checked {{ image: url("{check}"); }}
        """)

    def showEvent(self, event):
        super().showEvent(event)
        parent = self.parentWidget()
        if isinstance(parent, QMenu) and parent.isVisible():
            # Native placement includes our transparent gutter; keep the surfaces attached.
            offset = -10 if self.x() >= parent.x() else 10
            screen = self.screen().availableGeometry()
            x = max(screen.left(), min(self.x() + offset, screen.right() - self.width() + 1))
            self.move(x, self.y())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        surface = QRectF(self.rect()).adjusted(10, 10, -10, -10)
        painter.setPen(Qt.PenStyle.NoPen)
        for spread in range(8, 0, -1):
            painter.setBrush(QColor(0, 0, 0, 2 + (8 - spread) // 2))
            painter.drawRoundedRect(surface.adjusted(-spread, -spread + 2, spread, spread + 2),
                                    8 + spread, 8 + spread)
        painter.setBrush(ui_color("#202124"))
        painter.setPen(ui_color("#414246"))
        painter.drawRoundedRect(surface.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        painter.end()
        super().paintEvent(event)
