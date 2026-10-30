"""Compact color popup and on-demand screen sampling."""

from PySide6.QtCore import QObject, QPoint, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QIntValidator, QPainter, QPainterPath, QPen, QRegion
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLineEdit, QMenu, QToolButton, QVBoxLayout, QWidget

from picklight.paths import asset_path
from picklight.ui.graphics import theme_icon


class ColorHueBar(QWidget):
    changed = Signal(float)

    def __init__(self):
        super().__init__()
        self.hue = 0.0
        self.setFixedSize(138, 20)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _select(self, event):
        self.hue = max(0.0, min(1.0, (event.position().x() - 6) / (self.width() - 12)))
        self.changed.emit(self.hue)
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._select(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._select(event)

    def paintEvent(self, event):
        from PySide6.QtGui import QLinearGradient
        painter = QPainter(self)
        gradient = QLinearGradient(6, 0, self.width() - 6, 0)
        for index in range(7):
            gradient.setColorAt(index / 6, QColor.fromHsvF(index / 6, 1, 1))
        painter.fillRect(QRectF(6, 4, self.width() - 12, 12), gradient)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("white"), 2))
        painter.setBrush(QColor.fromHsvF(self.hue, 1, 1))
        painter.drawEllipse(QRectF(self.hue * (self.width() - 12), 3, 12, 14))
        painter.end()


class ColorModeButton(QToolButton):
    def __init__(self):
        super().__init__()
        self.mode = "RGB"
        self.setFixedHeight(24)
        self.setAccessibleName("切换 RGB、HSL 或 HEX")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#f7f7f7"))
        painter.setPen(QColor("#111111"))
        titles = self.mode if self.mode != "HEX" else ("HEX",)
        for index, title in enumerate(titles):
            painter.drawText(QRectF(9 + index * 60, 0, 54 if self.mode != "HEX" else 174, 24),
                             Qt.AlignmentFlag.AlignCenter, title)
        QSvgRenderer(asset_path("color.mode")).render(painter, QRectF(self.width() - 20, 7, 10, 10))
        painter.end()


class SamplingOverlay(QWidget):
    def __init__(self, owner, screen, snapshot):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint)
        self.owner, self.snapshot = owner, snapshot
        self.setGeometry(screen.geometry())
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self.snapshot)
        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            image = self.snapshot.toImage()
            x = min(image.width() - 1, max(0, int(event.position().x() * image.width() / self.width())))
            y = min(image.height() - 1, max(0, int(event.position().y() * image.height() / self.height())))
            self.owner.finish(image.pixelColor(x, y))
        else:
            self.owner.finish()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.owner.finish()


class ScreenSampler(QObject):
    finished = Signal(QColor)

    def __init__(self, parent):
        super().__init__(parent)
        self.overlays = []

    def start(self):
        snapshots = [(screen, screen.grabWindow(0)) for screen in QGuiApplication.screens()]
        for screen, snapshot in snapshots:
            if not snapshot.isNull():
                overlay = SamplingOverlay(self, screen, snapshot)
                self.overlays.append(overlay)
                overlay.show()
        if self.overlays:
            self.overlays[0].activateWindow()
            self.overlays[0].setFocus()
        else:
            self.finish()

    def finish(self, color=QColor()):
        for overlay in self.overlays:
            overlay.close()
        self.overlays.clear()
        self.finished.emit(color)


class ColorPickerPopup(QFrame):
    colorChanged = Signal(QColor)

    def __init__(self, parent, color):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.NoDropShadowWindowHint)
        from picklight.ui.visual_filters import SaturationValuePlane
        self.setObjectName("compactColorPicker")
        self.setProperty("preserveContentColors", True)
        self.setFixedSize(232, 250)
        self.setStyleSheet("""
            QFrame#compactColorPicker { background: white; border: 0; }
            QFrame#compactColorPicker QWidget { background: transparent; color: #111111; font-size: 12px; }
            QFrame#compactColorPicker QLineEdit { background: white; color: #111111; border: 1px solid #cecece; border-radius: 0; padding: 0; selection-background-color: #3297ff; }
            QFrame#compactColorPicker QLineEdit:focus { border-color: #3297ff; }
            QFrame#compactColorPicker QToolButton { border: 0; padding: 0; }
        """)
        shape = QPainterPath()
        shape.addRoundedRect(QRectF(self.rect()), 7, 7)
        self.setMask(QRegion(shape.toFillPolygon().toPolygon()))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 6)
        outer.setSpacing(0)
        self.plane = SaturationValuePlane()
        self.plane.hue = 0.0
        self.plane.setFixedSize(232, 138)
        outer.addWidget(self.plane)
        controls = QWidget()
        layout = QVBoxLayout(controls)
        layout.setContentsMargins(14, 6, 10, 0)
        layout.setSpacing(5)
        top = QHBoxLayout()
        top.setSpacing(8)
        self.eyedropper = QToolButton()
        self.eyedropper.setFixedSize(20, 28)
        self.eyedropper.setIcon(theme_icon("color.eyedropper", 18))
        self.eyedropper.setAccessibleName("从屏幕选取颜色")
        self.eyedropper.setToolTip("从屏幕选取颜色，Esc 取消")
        self.eyedropper.setCursor(Qt.CursorShape.PointingHandCursor)
        top.addWidget(self.eyedropper)
        self.preview = QWidget()
        self.preview.setFixedSize(32, 32)
        self.preview.setProperty("preserveContentColors", True)
        top.addWidget(self.preview)
        self.hue = ColorHueBar()
        top.addWidget(self.hue)
        layout.addLayout(top)
        fields = QHBoxLayout()
        fields.setContentsMargins(9, 0, 20, 0)
        fields.setSpacing(8)
        self.fields = []
        for title in ("R", "G", "B"):
            field = QLineEdit()
            field.setFixedHeight(32)
            field.setAlignment(Qt.AlignmentFlag.AlignCenter)
            field.setAccessibleName(title)
            field.textEdited.connect(self._fields_changed)
            field.editingFinished.connect(lambda: self._sync(force=True))
            self.fields.append(field)
            fields.addWidget(field)
        layout.addLayout(fields)
        self.mode_button = ColorModeButton()
        self.mode_button.setFixedWidth(208)
        self.mode_button.clicked.connect(self._switch_mode)
        layout.addWidget(self.mode_button)
        outer.addWidget(controls)
        self.color = QColor(color)
        self.plane.changed.connect(self._sv_changed)
        self.hue.changed.connect(self._hue_changed)
        self.eyedropper.clicked.connect(self._sample_screen)
        self.sampler = ScreenSampler(self)
        self.sampler.finished.connect(self._sample_finished)
        self._configure_fields()
        self._sync()
        for widget in self.findChildren(QWidget):
            widget.setProperty("preserveContentColors", True)

    def open_at(self, anchor):
        position = anchor.mapToGlobal(QPoint(0, -self.height() - 6))
        position.setX(self.parentWidget().mapToGlobal(QPoint(0, 0)).x())
        screen = QGuiApplication.screenAt(position) or QGuiApplication.primaryScreen()
        if screen:
            area = screen.availableGeometry()
            position.setX(max(area.left(), min(position.x(), area.right() - self.width() + 1)))
            if position.y() < area.top():
                position.setY(min(area.bottom() - self.height() + 1,
                                  anchor.mapToGlobal(QPoint(0, anchor.height() + 6)).y()))
        self.move(position)
        self.show()

    def _sync(self, force=False):
        hue, saturation, value, _ = self.color.getHsvF()
        if hue >= 0:
            self.plane.hue = self.hue.hue = hue
        self.plane.saturation, self.plane.value = saturation, value
        self.plane.update()
        self.hue.update()
        self.preview.setStyleSheet(f"background: {self.color.name()}; border: 0; border-radius: 16px;")
        if self.mode_button.mode == "RGB":
            values = self.color.getRgb()[:3]
        elif self.mode_button.mode == "HSL":
            h, s, light, _ = self.color.getHslF()
            values = (round(max(0, h) * 360), round(s * 100), round(light * 100))
        else:
            values = (self.color.name().upper(),)
        for field, value in zip(self.fields, values):
            if force or not field.hasFocus():
                field.setText(str(value))

    def _set_color(self, color):
        self.color = QColor(color)
        self._sync()
        self.colorChanged.emit(QColor(self.color))

    def _sv_changed(self, saturation, value):
        self._set_color(QColor.fromHsvF(self.plane.hue, saturation, value))

    def _hue_changed(self, hue):
        self.plane.hue = self.hue.hue = hue
        self._set_color(QColor.fromHsvF(hue, self.plane.saturation, self.plane.value))

    def _configure_fields(self):
        mode = self.mode_button.mode
        for index, field in enumerate(self.fields):
            field.setVisible(mode != "HEX" or index == 0)
            field.setValidator(QIntValidator(0, 255 if mode == "RGB" else 360 if index == 0 else 100, field)
                               if mode != "HEX" else None)
            field.setMaxLength(7 if mode == "HEX" else 3)
            field.setAccessibleName((mode[index] if mode != "HEX" else "HEX") + " 颜色值")

    def _switch_mode(self):
        modes = ("RGB", "HSL", "HEX")
        self.mode_button.mode = modes[(modes.index(self.mode_button.mode) + 1) % 3]
        self.mode_button.update()
        self._configure_fields()
        self._sync()

    def _fields_changed(self, *_):
        texts = [field.text() for field in self.fields]
        mode = self.mode_button.mode
        if mode == "HEX":
            color = QColor(texts[0] if texts[0].startswith("#") else "#" + texts[0])
            if len(texts[0].lstrip("#")) == 6 and color.isValid():
                self._set_color(color)
        elif all(field.hasAcceptableInput() for field in self.fields):
            values = [int(text) for text in texts]
            self._set_color(QColor(*values) if mode == "RGB" else
                            QColor.fromHslF(values[0] / 360, values[1] / 100, values[2] / 100))

    def _sample_screen(self):
        self.hide()
        menu = self.parentWidget().parentWidget()
        if isinstance(menu, QMenu):
            menu.close()
        QTimer.singleShot(80, self.sampler.start)

    def _sample_finished(self, color):
        if color.isValid():
            self._set_color(color)
        self.show()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)
