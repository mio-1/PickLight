"""Small workspace transitions and unobtrusive region scrollbars."""

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPointF, QTimer, QVariantAnimation, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QAbstractScrollArea, QApplication, QGraphicsOpacityEffect, QWidget


class PageTransitionOverlay(QWidget):
    def __init__(self, parent, snapshot):
        super().__init__(parent)
        previous = getattr(parent, "_page_transition", None)
        if previous is not None:
            previous.stop()
        parent._page_transition = self
        self.snapshot = snapshot
        self.progress = 0.0
        self.setGeometry(parent.rect())
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(180)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.valueChanged.connect(self._advance)
        self.animation.finished.connect(self.stop)

    def start(self):
        self.show()
        self.raise_()
        self.animation.start()

    def stop(self):
        self.animation.stop()
        self.hide()
        parent = self.parentWidget()
        if getattr(parent, "_page_transition", None) is self:
            parent._page_transition = None
        self.deleteLater()

    def _advance(self, value):
        self.progress = float(value)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setOpacity(1 - self.progress)
        painter.drawPixmap(QPointF(-12 * self.progress, 0), self.snapshot)
        painter.end()


class RegionScrollVisibility(QObject):
    def __init__(self, area):
        super().__init__(area)
        self.area = area
        self.animations = []
        self.effects = []
        self._target = None
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.setInterval(450)
        self.hide_timer.timeout.connect(self._hide_if_outside)
        for bar in (area.verticalScrollBar(), area.horizontalScrollBar()):
            effect = QGraphicsOpacityEffect(bar)
            effect.setOpacity(0)
            bar.setGraphicsEffect(effect)
            animation = QVariantAnimation(self)
            animation.setDuration(160)
            animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            animation.setStartValue(0.0)
            animation.setEndValue(0.0)
            animation.valueChanged.connect(effect.setOpacity)
            self.effects.append(effect)
            self.animations.append(animation)
            bar.sliderPressed.connect(self.reveal)
            bar.sliderReleased.connect(self.hide_timer.start)

    def _fade(self, value):
        if self._target == value:
            return
        self._target = value
        for effect, animation in zip(self.effects, self.animations):
            animation.stop()
            animation.setStartValue(effect.opacity())
            animation.setEndValue(float(value))
            animation.start()

    def reveal(self):
        self.hide_timer.stop()
        self._fade(1.0)

    def _hide_if_outside(self):
        if any(bar.isSliderDown() for bar in
               (self.area.verticalScrollBar(), self.area.horizontalScrollBar())):
            return
        if not self.area.underMouse():
            self._fade(0.0)


class ScrollVisibilityManager(QObject):
    """Keep native scrolling and scrollbar geometry while fading only the handles."""

    def __init__(self, root):
        super().__init__(root)
        for area in root.findChildren(QAbstractScrollArea):
            self._register(area)
        QApplication.instance().installEventFilter(self)

    def shutdown(self):
        """Detach the application-wide filter before the owning window closes."""
        QApplication.instance().removeEventFilter(self)

    def _register(self, area):
        if not hasattr(area, "_scroll_visibility"):
            area._scroll_visibility = RegionScrollVisibility(area)

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind == QEvent.Type.Show and isinstance(watched, QAbstractScrollArea):
            self._register(watched)
        if kind in (QEvent.Type.Enter, QEvent.Type.Leave, QEvent.Type.Wheel,
                    QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            widget = watched if isinstance(watched, QWidget) else None
            while widget is not None and not isinstance(widget, QAbstractScrollArea):
                widget = widget.parentWidget()
            if widget is not None:
                self._register(widget)
                controller = widget._scroll_visibility
                if kind in (QEvent.Type.Enter, QEvent.Type.Wheel, QEvent.Type.FocusIn):
                    controller.reveal()
                    if kind != QEvent.Type.Enter:
                        controller.hide_timer.start()
                else:
                    controller.hide_timer.start()
        return False
