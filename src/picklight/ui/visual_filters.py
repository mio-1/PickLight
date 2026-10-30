"""Theme-aware facet buttons, color selection and rating/status multi-selects."""

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QButtonGroup, QGridLayout, QHBoxLayout, QLineEdit, QMenu, QPushButton,
    QToolButton, QVBoxLayout, QWidget,
)

from picklight.appearance import ui_color
from picklight.filters import FORMAT_LABELS
from picklight.chrome import icon_canvas
from picklight.paths import asset_path
from picklight.ui.graphics import theme_icon


class FacetClearButton(QToolButton):
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setOpacity(1.0 if self.underMouse() else 0.7)
        theme_icon("filter.facet.clear", 16).paint(painter, self.rect())
        painter.end()

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)


class VisualFacetButton(QToolButton):
    def __init__(self, title, asset):
        super().__init__()
        self.asset = asset
        self.color = None
        self.setObjectName("visualFacet")
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_button = FacetClearButton(self)
        self.clear_button.setFixedSize(16, 16)
        self.clear_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.clear_button.setAccessibleName("清除" + title + "筛选")
        self.clear_button.setStyleSheet("QToolButton {background: transparent; border: 0; padding: 0;}")
        self.clear_button.hide()
        self.setText(title)

    def setText(self, text):
        super().setText(text)
        self.setFixedSize(self.fontMetrics().horizontalAdvance(text) + 34, 30)
        self.clear_button.move(self.width() - 16, 0)
        self.update()

    def set_active(self, active):
        self.setProperty("active", "true" if active else "false")
        self.clear_button.setVisible(bool(active))
        self.setText(self.text())

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        active = self.property("active") == "true"
        body = QRectF(0, 6, self.width() - 6, 24)
        hovered = self.underMouse()
        menu_open = bool(self.menu() and self.menu().isVisible())
        if hovered or active or menu_open:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(ui_color("#3c3c40" if hovered and active else "#303034"))
            painter.drawRoundedRect(body, 6, 6)
        icon_size = 18 if self.asset == "filter.status" else 16
        target = QRectF(11 - icon_size / 2, 18 - icon_size / 2, icon_size, icon_size)
        if self.color is not None:
            painter.setBrush(QColor(*self.color))
            painter.setPen(QPen(ui_color("#f7f8f8"), 1))
            painter.drawEllipse(target.adjusted(1, 1, -1, -1))
        else:
            icon = theme_icon(self.asset, icon_size)
            icon.paint(painter, target.toRect(), Qt.AlignmentFlag.AlignCenter,
                       QIcon.Mode.Active if hovered or menu_open else QIcon.Mode.Normal)
        painter.setPen(ui_color("#f7f8f8"))
        painter.drawText(body.adjusted(23, 0, -5, 0),
                         Qt.AlignmentFlag.AlignVCenter, self.text())
        painter.end()


@lru_cache(maxsize=2)
def _rating_star(lit):
    data = Path(asset_path("filter.star")).read_bytes()
    data = data.replace(b'fill="black"', b'fill="#cbcbcc"' if lit else b'fill="#45464a"')
    canvas = icon_canvas(16)
    painter = QPainter(canvas)
    QSvgRenderer(QByteArray(data)).render(painter, QRectF(2, 1, 12, 13))
    painter.end()
    return canvas


class RatingFilterRow(QPushButton):
    def __init__(self, rating):
        super().__init__()
        self.rating = rating
        self.count = 0
        self.setObjectName("ratingFilterRow")
        self.setCheckable(True)
        self.setFixedHeight(28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(f"{rating} 星" if rating else "尚未评分")
        self.check_icon = QSvgRenderer(asset_path("filter.check"), self)

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        if self.underMouse():
            painter.setBrush(ui_color("#242528"))
            painter.drawRoundedRect(QRectF(self.rect()), 5, 5)
        self.paint_indicator(painter)
        self.paint_value(painter)
        font = painter.font()
        font.setPixelSize(11)
        painter.setFont(font)
        painter.setPen(ui_color("#919296"))
        painter.drawText(self.rect().adjusted(0, 0, -10, 0),
                         Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, str(self.count))
        painter.end()

    def paint_indicator(self, painter):
        checked = self.isChecked()
        painter.setPen(QPen(ui_color("#3297ff" if checked else "#5b5c60"), 1))
        painter.setBrush(ui_color("#3297ff") if checked else Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(6, 7.5, 13, 13), 3, 3)
        if checked:
            self.check_icon.render(painter, QRectF(8.5, 11, 8, 6))

    def paint_value(self, painter):
        if self.rating:
            for index in range(5):
                pixmap = _rating_star(index < self.rating)
                painter.drawPixmap(QRectF(28 + index * 16, 6, 16, 16), pixmap, QRectF(pixmap.rect()))
        else:
            painter.setPen(ui_color("#f7f8f8"))
            painter.drawText(self.rect().adjusted(28, 0, -25, 0), Qt.AlignmentFlag.AlignVCenter, "尚未评分")


class RatingFilterPanel(QWidget):
    ratingToggled = Signal(int)

    def __init__(self):
        super().__init__()
        self.setFixedWidth(172)
        self.rows = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        for value in (5, 4, 3, 2, 1, 0):
            row = RatingFilterRow(value)
            row.clicked.connect(lambda checked=False, stars=value: self.ratingToggled.emit(stars))
            self.rows[value] = row
            layout.addWidget(row)

    def set_counts(self, counts, selected):
        visible = 0
        for value, row in self.rows.items():
            row.count = counts.get(value, 0)
            row.setChecked(value in selected)
            row.setProperty("lit", "true" if value in selected else "false")
            shown = row.count > 0 or value in selected
            row.setVisible(shown)
            visible += shown
            row.update()
        self.setFixedHeight(max(28, visible * 28))


class StatusFilterRow(RatingFilterRow):
    def __init__(self, state, title):
        super().__init__(0)
        self.state, self.title = state, title
        self.setAccessibleName(title)

    def paint_value(self, painter):
        painter.setPen(ui_color("#f7f8f8"))
        painter.drawText(self.rect().adjusted(28, 0, -30, 0),
                         Qt.AlignmentFlag.AlignVCenter, self.title)


class StatusFilterPanel(QWidget):
    stateToggled = Signal(str)

    def __init__(self):
        super().__init__()
        self.setFixedWidth(172)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.rows = {}
        for state, title in (("keep", "保留"), ("reject", "待删除"), ("none", "无")):
            row = StatusFilterRow(state, title)
            row.clicked.connect(lambda checked=False, value=state: self.stateToggled.emit(value))
            self.rows[state] = row
            layout.addWidget(row)

    def set_counts(self, counts, selected):
        for state, row in self.rows.items():
            row.count = counts.get(state, 0)
            row.setChecked(state in selected)
            row.update()


class FormatFilterRow(RatingFilterRow):
    def __init__(self, title):
        super().__init__(0)
        self.title = title
        self.setAccessibleName(title)

    def paint_indicator(self, painter):
        painter.setPen(QPen(ui_color("#3297ff" if self.isChecked() else "#5b5c60"), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QRectF(6, 7.5, 13, 13))
        if self.isChecked():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(ui_color("#3297ff"))
            painter.drawEllipse(QRectF(9.5, 11, 6, 6))

    def paint_value(self, painter):
        painter.setPen(ui_color("#f7f8f8"))
        painter.drawText(self.rect().adjusted(28, 0, -35, 0),
                         Qt.AlignmentFlag.AlignVCenter, self.title)


class FormatFilterPanel(QWidget):
    formatSelected = Signal(str)

    def __init__(self):
        super().__init__()
        self.setFixedSize(188, 96)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(0)
        self.rows = {}
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        for mode, title in FORMAT_LABELS.items():
            row = FormatFilterRow(title)
            self.group.addButton(row)
            row.clicked.connect(lambda checked=False, value=mode: self._select(value))
            self.rows[mode] = row
            layout.addWidget(row)

    def _select(self, mode):
        self.formatSelected.emit(mode)
        menu = self.parentWidget()
        if isinstance(menu, QMenu):
            menu.close()

    def set_counts(self, counts, selected):
        self.group.setExclusive(False)
        for mode, row in self.rows.items():
            row.count = counts.get(mode, 0)
            row.setChecked(mode == selected)
            row.update()
        self.group.setExclusive(True)


class SaturationValuePlane(QWidget):
    changed = Signal(float, float)

    def __init__(self):
        super().__init__()
        self.hue, self.saturation, self.value = 0.83, 0.0, 0.5
        self.setFixedSize(150, 150)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def _select(self, event):
        self.saturation = max(0.0, min(1.0, event.position().x() / (self.width() - 1)))
        self.value = 1 - max(0.0, min(1.0, event.position().y() / (self.height() - 1)))
        self.changed.emit(self.saturation, self.value)
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._select(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._select(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor.fromHsvF(self.hue, 1, 1))
        white = QLinearGradient(0, 0, self.width(), 0)
        white.setColorAt(0, QColor("white"))
        white.setColorAt(1, QColor(255, 255, 255, 0))
        painter.fillRect(self.rect(), white)
        black = QLinearGradient(0, 0, 0, self.height())
        black.setColorAt(0, QColor(0, 0, 0, 0))
        black.setColorAt(1, QColor("black"))
        painter.fillRect(self.rect(), black)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        x, y = self.saturation * (self.width() - 1), (1 - self.value) * (self.height() - 1)
        painter.setPen(QPen(QColor("#222222"), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QRectF(x - 4, y - 4, 8, 8))
        painter.setPen(QPen(QColor("white"), 1))
        painter.drawEllipse(QRectF(x - 4, y - 4, 8, 8))
        painter.end()


class HueStrip(QWidget):
    changed = Signal(float)

    def __init__(self):
        super().__init__()
        self.hue = 0.83
        self.setFixedSize(13, 150)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def _select(self, event):
        self.hue = 1 - max(0.0, min(1.0, event.position().y() / (self.height() - 1)))
        self.changed.emit(self.hue)
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._select(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._select(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        gradient = QLinearGradient(0, 0, 0, self.height())
        for index, color in enumerate(("#ff0000", "#ff00ff", "#0000ff", "#00ffff", "#00ff00", "#ffff00", "#ff0000")):
            gradient.setColorAt(index / 6, QColor(color))
        painter.fillRect(self.rect(), gradient)
        y = (1 - self.hue) * (self.height() - 1)
        painter.setPen(QPen(QColor("#18191c"), 3))
        painter.drawLine(0, round(y), self.width(), round(y))
        painter.setPen(QPen(QColor("white"), 1))
        painter.drawLine(0, round(y), self.width(), round(y))
        painter.end()


class ColorPreset(QToolButton):
    def __init__(self, value):
        super().__init__()
        self.value = value
        self.setFixedSize(20, 20)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("不限颜色" if not value else "灰度图片" if value == "gray" else value)
        self.setAccessibleName(self.toolTip())

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(1 if self.isChecked() or self.underMouse() else 0.8)
        if self.value == "gray":
            painter.drawPixmap(self.rect(), QPixmap(asset_path("filter.gray.preset")))
            if self.isChecked():
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor("white"), 1))
                painter.drawRoundedRect(QRectF(0.5, 0.5, 19, 19), 4, 4)
        else:
            painter.setPen(QPen(QColor("#f7f8f8") if self.isChecked() else QColor(128, 128, 128, 77), 1))
            painter.setBrush(QColor(self.value) if self.value.startswith("#") else QColor("#cccccc"))
            painter.drawRoundedRect(QRectF(0.5, 0.5, 19, 19), 4, 4)
            if not self.value:
                painter.setPen(QPen(QColor("#6a6a6a"), 1))
                painter.drawLine(2, 2, 18, 18)
        painter.end()


class ColorFilterPanel(QWidget):
    colorChanged = Signal(str)
    PRESETS = ("", "gray", "#111111", "#FFFFFF", "#9E9E9E", "#A48057", "#FC85B3",
               "#FF2727", "#FFA34B", "#FFD534", "#47C595", "#51C4C4", "#2B76E7", "#6D50ED")

    def __init__(self):
        super().__init__()
        self.setFixedWidth(200)
        self.current = ""
        self.color = QColor("#808080")
        self.delay = QTimer(self)
        self.delay.setSingleShot(True)
        self.delay.setInterval(120)
        self.delay.timeout.connect(self.commit_pending)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 16, 14, 14)
        layout.setSpacing(10)
        planes = QHBoxLayout()
        planes.setSpacing(7)
        self.plane = SaturationValuePlane()
        self.hue_strip = HueStrip()
        self.plane.changed.connect(self._sv_changed)
        self.hue_strip.changed.connect(self._hue_changed)
        planes.addWidget(self.plane)
        planes.addWidget(self.hue_strip)
        layout.addLayout(planes)
        grid = QGridLayout()
        grid.setSpacing(5)
        self.presets = {}
        for index, value in enumerate(self.PRESETS):
            button = ColorPreset(value)
            button.clicked.connect(lambda checked=False, selected=value: self.choose(selected))
            self.presets[value] = button
            grid.addWidget(button, index // 7, index % 7)
        layout.addLayout(grid)
        self.hex_edit = QLineEdit()
        self.hex_edit.setObjectName("colorHexInput")
        self.hex_edit.setFixedHeight(32)
        self.hex_edit.setPlaceholderText("#FF0000")
        self.hex_edit.setMaxLength(7)
        self.hex_edit.setTextMargins(32, 0, 33, 0)
        self.hex_edit.setToolTip("输入 HEX 色值，例如 #FF0000")
        self.hex_edit.textEdited.connect(self._hex_changed)
        self.preview = QToolButton(self.hex_edit)
        self.preview.setProperty("preserveContentColors", True)
        self.preview.setGeometry(8, 9, 14, 14)
        self.preview.clicked.connect(self._open_color_dialog)
        self.more_button = QToolButton(self.hex_edit)
        self.more_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.more_button.setGeometry(139, 1, 32, 30)
        self.more_button.setIcon(QIcon(asset_path("filter.color")))
        self.more_button.setIconSize(QSize(16, 16))
        self.more_button.setStyleSheet("QToolButton { background: transparent; border: 0; border-left: 1px solid #303134; border-radius: 0; padding: 0; }")
        self.more_button.clicked.connect(self._open_color_dialog)
        layout.addWidget(self.hex_edit)
        self.set_value("")

    def set_value(self, value, *, update_text=True):
        self.current = value
        if value.startswith("#"):
            self.color = QColor(value)
        hue, saturation, brightness, _ = self.color.getHsvF()
        if hue >= 0:
            self.plane.hue = hue
            self.hue_strip.hue = hue
        self.plane.saturation, self.plane.value = saturation, brightness
        self.plane.update()
        self.hue_strip.update()
        if update_text and not self.hex_edit.hasFocus():
            self.hex_edit.setText(value.upper() if value.startswith("#") else "")
        self.preview.setStyleSheet(f"QToolButton {{ background: {self.color.name()}; border: 0; border-radius: 3px; padding: 0; }}")
        for preset, button in self.presets.items():
            button.setChecked(preset.casefold() == value.casefold())
            button.update()

    def choose(self, value):
        self.delay.stop()
        self.set_value(value)
        self.hex_edit.setText(value.upper() if value.startswith("#") else "")
        self.colorChanged.emit(value)

    def commit_pending(self):
        self.delay.stop()
        self.colorChanged.emit(self.current)

    def _sv_changed(self, saturation, value):
        self.color = QColor.fromHsvF(self.plane.hue, saturation, value)
        self._draft_color()

    def _hue_changed(self, hue):
        self.plane.hue = hue
        self.color = QColor.fromHsvF(hue, self.plane.saturation, self.plane.value)
        self._draft_color()

    def _draft_color(self):
        value = self.color.name().upper()
        self.set_value(value)
        self.hex_edit.setText(value)
        self.delay.start()

    def _hex_changed(self, text):
        value = text.strip()
        if not value:
            self.choose("")
        elif len(value.lstrip("#")) in (3, 6):
            color = QColor(value if value.startswith("#") else "#" + value)
            if color.isValid():
                self.set_value(color.name().upper(), update_text=False)
                self.delay.start()

    def _open_color_dialog(self):
        from picklight.ui.color_picker import ColorPickerPopup
        previous = getattr(self, "color_popup", None)
        if previous is not None:
            previous.close()
            previous.deleteLater()
        self.color_popup = ColorPickerPopup(self, self.color)
        self.color_popup.colorChanged.connect(lambda color: self.choose(color.name().upper()))
        self.color_popup.open_at(self.more_button)
