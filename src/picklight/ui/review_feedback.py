"""A small, non-interactive acknowledgment above the photo canvas."""

from PySide6.QtCore import QEvent, QEasingCurve, QRectF, QTimer, QVariantAnimation, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen
from PySide6.QtWidgets import QWidget

from picklight.ui.graphics import photo_state_pixmap, theme_icon, theme_rating_pixmap


class ReviewFeedback(QWidget):
    def __init__(self, canvas):
        super().__init__(canvas.parentWidget())
        self.canvas = canvas
        self.kind = ""
        self.stars = None
        self.message = ""
        self.key_label = ""
        self._opacity = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedSize(112, 32)
        self.motion = QVariantAnimation(self)
        self.motion.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.motion.valueChanged.connect(self._animate_frame)
        self.motion.finished.connect(self._animation_finished)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(750)
        self.timer.timeout.connect(self._fade_out)
        canvas.installEventFilter(self)
        self.parentWidget().installEventFilter(self)
        self.hide()

    def present(self, kind, stars=None, *, key_label=None):
        self.kind, self.stars = kind, stars
        if kind == "rating":
            self.message = f"{stars} 星" if stars else "清除评分"
            self.key_label = str(stars)
        else:
            self.message, self.key_label = {
                "keep": ("已保留", "P"), "reject": ("待删除", "X"),
                "none": ("已清除标记", "U"),
            }[kind]
        if key_label is not None:
            self.key_label = key_label
        self.setAccessibleName(self.message)
        font = QFont(self.font())
        font.setPixelSize(12)
        self.setFont(font)
        icon_width = 78 if kind == "rating" else 20
        width = self.fontMetrics().horizontalAdvance(self.message) + icon_width + 20
        self.setFixedWidth(min(width, max(80, self.canvas.width() - 24)))
        self.reposition()
        if not self.isVisible():
            self._opacity = 0.0
        self.show()
        self.raise_()
        self._animate_to(1.0, 100)
        self.timer.start()

    def dismiss(self):
        self.timer.stop()
        self.motion.stop()
        self._opacity = 0.0
        self.hide()

    def _animate_to(self, value, duration):
        self.motion.stop()
        self.motion.setDuration(duration)
        self.motion.setStartValue(self._opacity)
        self.motion.setEndValue(value)
        self.motion.start()

    def _fade_out(self):
        self._animate_to(0.0, 180)

    def _animate_frame(self, value):
        if value is None:
            return
        self._opacity = float(value)
        self.reposition()
        self.update()

    def _animation_finished(self):
        if self._opacity < 0.01:
            self.hide()

    def reposition(self):
        rect = self.canvas.geometry()
        self.move(round(rect.center().x() - self.width() / 2),
                  max(rect.top(), rect.bottom() - self.height() - 12 + round((1 - self._opacity) * 5)))

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Hide:
            self.dismiss()
        elif event.type() in (QEvent.Type.Resize, QEvent.Type.Move) and self.isVisible():
            self.reposition()
        return False

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(self._opacity)
        body = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        background = QColor(20, 22, 26, 190)
        painter.setBrush(background)
        painter.setPen(QPen(QColor(255, 255, 255, 28), 1))
        painter.drawRoundedRect(body, 8, 8)
        x, y = 10, 9
        if self.kind == "rating":
            for index in range(5):
                QIcon(theme_rating_pixmap(index < (self.stars or 0))).paint(painter, x + index * 14, y, 12, 12)
            x += 78
        else:
            icon = (QIcon(photo_state_pixmap(self.kind, 14)) if self.kind in ("keep", "reject")
                    else theme_icon("photo.none", 14))
            icon.paint(painter, x, y, 14, 14)
            x += 20
        painter.setFont(self.font())
        painter.setPen(QColor("#f0f2f5"))
        text_rect = QRectF(x, body.top(), max(0, body.right() - x - 9), body.height())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter,
                         self.fontMetrics().elidedText(self.message, Qt.TextElideMode.ElideRight, int(text_rect.width())))
        painter.end()
