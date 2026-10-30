"""Branded, centered application information surface."""

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QLabel, QPushButton, QToolButton, QVBoxLayout

from picklight.folder_dialogs import FolderModal
from picklight import __version__
from picklight.paths import asset_path


class AboutDialog(FolderModal):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("关于 PickLight")
        # The transparent gutter contains the rounded surface's shadow; suppress
        # the platform shadow, which follows the rectangular top-level window.
        self.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)
        self.setFixedSize(384, 454)
        self.layout().setContentsMargins(32, 32, 32, 32)
        self.surface.setFixedSize(320, 390)
        shadow = QGraphicsDropShadowEffect(self.surface)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(0, 0, 0, 140))
        self.surface.setGraphicsEffect(shadow)
        self.surface.setObjectName("aboutSurface")
        self.surface.setStyleSheet("""
            QFrame#aboutSurface { background: #18191c; border: 1px solid #414246; border-radius: 8px; }
            QLabel { border: 0; background: transparent; }
            QLabel#aboutName { color: #f7f8f8; font-size: 24px; font-weight: 700; }
            QLabel#aboutDescription { color: #f7f8f8; font-size: 16px; font-weight: 600; }
            QLabel#aboutVersion { color: #929397; font-size: 13px; font-weight: 600; }
            QLabel#aboutCopyright { color: #929397; font-size: 12px; }
            QToolButton#aboutClose { background: transparent; border: 0; border-radius: 4px; padding: 0; }
            QToolButton#aboutClose:hover { background: rgba(255, 255, 255, 13); }
        """)
        layout = QVBoxLayout(self.surface)
        layout.setContentsMargins(32, 48, 32, 40)
        layout.setSpacing(0)
        logo = QLabel()
        logo.setFixedSize(80, 80)
        logo.setPixmap(QIcon(asset_path("picklight.ico")).pixmap(QSize(80, 80)))
        layout.addWidget(logo, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(24)
        for text, name, height in (("PickLight", "aboutName", 30),
                                   ("照片整理与选图工具", "aboutDescription", 28)):
            label = QLabel(text, objectName=name)
            label.setFixedHeight(height)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(label)
        layout.addStretch()
        version = QLabel(__version__, objectName="aboutVersion")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version)
        layout.addSpacing(26)
        self.confirm_button = QPushButton("确认", objectName="folderModalPrimary")
        self.confirm_button.setFixedHeight(38)
        self.confirm_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.confirm_button.setDefault(True)
        self.confirm_button.clicked.connect(self.accept)
        layout.addWidget(self.confirm_button)
        layout.addSpacing(10)
        self.copyright_label = QLabel("Copyright © 2026 iroak", objectName="aboutCopyright")
        self.copyright_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.copyright_label)
        self.close_button = QToolButton(self.surface)
        self.close_button.setObjectName("aboutClose")
        self.close_button.setGeometry(284, 12, 24, 24)
        self.close_button.setIcon(QIcon(asset_path("modal.close")))
        self.close_button.setIconSize(QSize(24, 24))
        self.close_button.setAccessibleName("关闭")
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.clicked.connect(self.reject)
