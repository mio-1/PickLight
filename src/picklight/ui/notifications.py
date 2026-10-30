"""Transient in-window notifications with an optional undo action."""

from PySide6.QtCore import QEvent, QSize, QTimer, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QToolButton

from picklight.ui.common import ElidedLabel
from picklight.ui.graphics import theme_icon


class UndoToast(QFrame):
    def __init__(self, owner):
        super().__init__(owner.centralWidget())
        self.owner = owner
        self._undo = None
        self.setObjectName("undoToast")
        self.setFixedHeight(38)
        self.setStyleSheet("""
            QFrame#undoToast { background: #18191c; border: 1px solid #414246; border-radius: 6px; }
            QLabel { color: #f7f8f8; border: 0; background: transparent; font-size: 12px; }
            QPushButton { color: #f7f8f8; background: transparent; border: 0; padding: 0; font-size: 12px; font-weight: 600; }
            QPushButton:hover { text-decoration: underline; }
            QToolButton { background: transparent; border: 0; border-radius: 4px; padding: 0; }
            QToolButton:hover { background: rgba(255, 255, 255, 13); }
            QFrame#toastSeparator { background: #343538; border: 0; }
        """)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(18)
        shadow.setOffset(0, 5)
        shadow.setColor(QColor(0, 0, 0, 110))
        self.setGraphicsEffect(shadow)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 8, 0)
        layout.setSpacing(8)
        icon = QLabel()
        icon.setFixedSize(16, 16)
        icon.setPixmap(theme_icon("notification.success", 16).pixmap(16, 16))
        layout.addWidget(icon)
        self.message = ElidedLabel()
        self.message.elide_mode = Qt.TextElideMode.ElideRight
        self.message.setMinimumWidth(0)
        self.message.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.message)
        self.undo_button = QPushButton("撤销")
        self.undo_button.setFixedWidth(32)
        self.undo_button.clicked.connect(self._trigger_undo)
        layout.addWidget(self.undo_button)
        separator = QFrame(objectName="toastSeparator")
        separator.setFixedSize(1, 16)
        layout.addWidget(separator)
        self.close_button = QToolButton()
        self.close_button.setIcon(theme_icon("modal.close", 24))
        self.close_button.setIconSize(QSize(24, 24))
        self.close_button.setFixedSize(24, 24)
        self.close_button.setAccessibleName("关闭删除提示")
        self.close_button.clicked.connect(self.dismiss)
        layout.addWidget(self.close_button)
        for button in (self.undo_button, self.close_button):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(10000)
        self.timer.timeout.connect(self.dismiss)
        self.parentWidget().installEventFilter(self)
        owner.viewer.installEventFilter(self)
        self.hide()

    def show_deletion(self, name, undo):
        self._undo = undo
        self.message.setText(f'“{name}”已删除。')
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self._fit_width()
        self.reposition()
        self.show()
        self.raise_()
        self.timer.start()

    def _fit_width(self):
        text_width = self.message.fontMetrics().horizontalAdvance(self.message.text())
        self.setFixedWidth(min(self.parentWidget().width() - 24, max(240, text_width + 130)))

    def reposition(self):
        anchor = self.owner.viewer if self.owner.viewer.isVisible() else self.parentWidget()
        center = anchor.mapTo(self.parentWidget(), anchor.rect().center())
        x = max(12, min(center.x() - self.width() // 2, self.parentWidget().width() - self.width() - 12))
        y = (self.owner.title_bar.height() if self.owner.title_bar.isVisible() else 0) + (self.owner.filter_bar.height()
            if self.owner.filter_bar.isVisible() else 0) + 12
        self.move(x, y)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Move) and self.isVisible():
            self._fit_width()
            self.reposition()
        return super().eventFilter(watched, event)

    def enterEvent(self, event):
        self.timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self.isVisible():
            self.timer.start()
        super().leaveEvent(event)

    def dismiss(self):
        self.timer.stop()
        self._undo = None
        self.hide()

    def _trigger_undo(self):
        undo = self._undo
        self.dismiss()
        if undo is not None:
            undo()
