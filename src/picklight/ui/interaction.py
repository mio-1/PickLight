"""Shared animation state for painted button hover feedback."""

from PySide6.QtCore import QEasingCurve, QVariantAnimation


class HoverAnimationMixin:
    def _init_hover_animation(self):
        self._hover_amount = 0.0
        self._hover_animation = QVariantAnimation(self)
        self._hover_animation.setDuration(160)
        self._hover_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._hover_animation.valueChanged.connect(self._set_hover_amount)

    def _set_hover_amount(self, amount):
        self._hover_amount = float(amount)
        self.update()

    def _animate_hover(self, target):
        self._hover_animation.stop()
        self._hover_animation.setStartValue(self._hover_amount)
        self._hover_animation.setEndValue(target)
        self._hover_animation.start()
