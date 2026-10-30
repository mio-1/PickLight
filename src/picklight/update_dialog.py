"""Local update-information placeholder; no network or updater operations."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QLabel, QPushButton, QVBoxLayout

from picklight import __version__
from picklight.folder_dialogs import FolderModal


class UpdateDialog(FolderModal):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("检查更新")
        self.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)
        self.setFixedSize(456, 204)
        self.layout().setContentsMargins(28, 28, 28, 28)
        self.surface.setFixedSize(400, 148)
        self.surface.setObjectName("updateSurface")
        shadow = QGraphicsDropShadowEffect(self.surface)
        shadow.setBlurRadius(20)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 150))
        self.surface.setGraphicsEffect(shadow)
        self.surface.setStyleSheet("""
            QFrame#updateSurface { background: #18191c; border: 1px solid #414246; border-radius: 8px; }
            QLabel#updateTitle { color: #f7f8f8; font-size: 16px; font-weight: 700; }
            QLabel#updateMessage { color: #bdbec0; font-size: 12px; }
        """)
        layout = QVBoxLayout(self.surface)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(0)
        self.title_label = QLabel("检查更新", objectName="updateTitle")
        self.title_label.setFixedHeight(22)
        layout.addWidget(self.title_label)
        layout.addSpacing(8)
        self.message = QLabel(f"PickLight {__version__}，暂未开放在线更新检查", objectName="updateMessage")
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setFixedHeight(18)
        layout.addWidget(self.message)
        layout.addSpacing(18)
        self.confirm_button = QPushButton("确定", objectName="folderModalPrimary")
        self.confirm_button.setFixedHeight(34)
        self.confirm_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.confirm_button.setDefault(True)
        self.confirm_button.clicked.connect(self.accept)
        layout.addWidget(self.confirm_button)
