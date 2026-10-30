"""Searchable shortcut groups with draft editing and explicit save/apply."""

from PySide6.QtCore import QEvent, QPoint, QSignalBlocker, QTimer, Qt, Signal
from PySide6.QtGui import QIcon, QKeySequence, QPainter
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QKeySequenceEdit, QLabel,
    QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from picklight.shortcuts import DEFAULTS, SHORTCUTS, display_shortcut, shortcut_conflicts, validate
from picklight.ui.graphics import theme_icon


class PreferencesSearchEdit(QLineEdit):
    def __init__(self):
        super().__init__(objectName="preferencesSearch")
        self.setFixedHeight(32)
        self.setPlaceholderText("搜索...")
        self.setTextMargins(30, 0, 10, 2)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        theme_icon("search", 14).paint(painter, 10, (self.height() - 14) // 2, 14, 14,
                                       Qt.AlignmentFlag.AlignCenter, QIcon.Mode.Active)
        painter.end()


class ShortcutEditor(QKeySequenceEdit):
    focusChanged = Signal(bool)
    clearRequested = Signal()

    def __init__(self, sequence):
        super().__init__(sequence)
        self.setClearButtonEnabled(False)
        self.findChild(QLineEdit).installEventFilter(self)
        self._format_timer = QTimer(self)
        self._format_timer.setSingleShot(True)
        self._format_timer.timeout.connect(self._format_display)
        self.keySequenceChanged.connect(lambda *_: self._format_timer.start(0))
        self._format_display()

    def _format_display(self, force=False):
        line = self.findChild(QLineEdit)
        line.setPlaceholderText("记录快捷键")
        if force or (not line.hasFocus() and not self.hasFocus()):
            text = self.keySequence().toString(QKeySequence.SequenceFormat.NativeText)
            line.setText(text.replace("+", " + "))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Backspace:
            self.clearRequested.emit()
            self.clear()
            self._format_display(force=True)
            event.accept()
            return
        super().keyPressEvent(event)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Backspace:
            self.keyPressEvent(event)
            return True
        if event.type() == QEvent.Type.FocusIn:
            self._format_timer.start(0)
            self.focusChanged.emit(True)
        elif event.type() == QEvent.Type.FocusOut:
            self._format_timer.start(0)
            self.focusChanged.emit(False)
        return super().eventFilter(watched, event)


class ShortcutPreferences(QWidget):
    changed = Signal()

    def __init__(self, values):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 4, 16, 16)
        layout.setSpacing(10)
        self.search = PreferencesSearchEdit()
        self.search.setAccessibleName("搜索快捷键")
        layout.addWidget(self.search)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        cards = QVBoxLayout(body)
        cards.setContentsMargins(0, 0, 2, 0)
        cards.setSpacing(12)
        self.editors, self.rows, self.groups = {}, {}, {}
        group_order = ("文件夹", "显示", "浏览", "查找", "评分", "标记")
        for spec in sorted(SHORTCUTS, key=lambda item: group_order.index(item.group)):
            if spec.group not in self.groups:
                card = QFrame(objectName="preferencesCard")
                group_layout = QVBoxLayout(card)
                group_layout.setContentsMargins(8, 10, 8, 8)
                group_layout.setSpacing(2)
                heading = QLabel(objectName="preferencesHeading")
                group_layout.addWidget(heading)
                self.groups[spec.group] = (card, group_layout, heading)
                cards.addWidget(card)
            card, group_layout, heading = self.groups[spec.group]
            row = QFrame(objectName="shortcutRow")
            row.setProperty("alternate", (group_layout.count() - 1) % 2 == 0)
            line = QHBoxLayout(row)
            line.setContentsMargins(8, 0, 6, 0)
            line.setSpacing(12)
            label = QLabel(spec.title)
            label.setWordWrap(True)
            line.addWidget(label, 1)
            editor = ShortcutEditor(QKeySequence(values[spec.id]))
            editor.setObjectName("shortcutEditor")
            editor.setAccessibleName(spec.title + "快捷键")
            editor.setMaximumSequenceLength(1)
            editor.setMinimumHeight(32)
            editor.setToolTip("按下新的按键组合，或清空以取消绑定")
            editor.findChild(QLineEdit).setPlaceholderText("记录快捷键")
            editor.keySequenceChanged.connect(lambda *_args, key=spec.id: self._edited(key))
            editor.focusChanged.connect(lambda focused, key=spec.id: self._show_conflict(key, focused))
            editor.clearRequested.connect(self._clear_conflict)
            line.addWidget(editor, 1)
            group_layout.addWidget(row)
            self.rows[spec.id], self.editors[spec.id] = row, editor
        self.empty = QLabel("没有匹配的快捷键", objectName="preferencesHint")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cards.addWidget(self.empty)
        self.restore_button = QPushButton("恢复默认", objectName="shortcutsRestore")
        self.restore_button.setAutoDefault(False)
        self.restore_button.clicked.connect(self.restore_defaults)
        cards.addWidget(self.restore_button)
        cards.addStretch()
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)
        self.conflict_hint = QLabel(self, objectName="shortcutConflict")
        self.conflict_hint.hide()
        scroll.verticalScrollBar().valueChanged.connect(lambda *_: self.conflict_hint.hide())
        self.search.textChanged.connect(self._filter)
        self._updating = False
        self._accepted_values = self.values()
        self.conflicts = {}
        self._filter()

    def values(self):
        return {key: editor.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
                for key, editor in self.editors.items()}

    def error(self):
        try:
            validate(self.values())
        except ValueError as error:
            return str(error)
        return ""

    def matches(self, query):
        query = query.strip().casefold()
        values = self.values()
        return any(query in (item.group + " " + item.title + " " + display_shortcut(values, item.id)).casefold()
                   for item in SHORTCUTS)

    def _filter(self, *_):
        query = self.search.text().strip().casefold()
        values = self.values()
        counts = dict.fromkeys(self.groups, 0)
        for item in SHORTCUTS:
            shown = not query or query in (item.group + " " + item.title + " " + display_shortcut(values, item.id)).casefold()
            self.rows[item.id].setVisible(shown)
            counts[item.group] += shown
        for group, (card, _, heading) in self.groups.items():
            card.setVisible(bool(counts[group]))
            heading.setText(f"{group} ({counts[group]})")
        self.empty.setVisible(not any(counts.values()))

    def _update_conflicts(self):
        for key, editor in self.editors.items():
            line = editor.findChild(QLineEdit)
            conflict = key in self.conflicts
            if line.property("conflict") != conflict:
                line.setProperty("conflict", conflict)
                line.style().unpolish(line)
                line.style().polish(line)

    def _show_conflict(self, key, focused=True):
        self.conflict_hint.hide()
        if not focused or key not in self.conflicts:
            return
        editor = self.editors[key]
        if not editor.isVisible():
            return
        self.conflict_hint.setText(self.conflicts[key])
        self.conflict_hint.adjustSize()
        position = editor.mapTo(self, QPoint(0, -self.conflict_hint.height() - 4))
        position.setX(max(0, min(position.x(), self.width() - self.conflict_hint.width())))
        self.conflict_hint.move(position)
        self.conflict_hint.show()
        self.conflict_hint.raise_()

    def _clear_conflict(self):
        self.conflicts.clear()
        self._update_conflicts()
        self.conflict_hint.hide()

    def _edited(self, key):
        if not self._updating:
            values = self.values()
            error = shortcut_conflicts(values).get(key)
            if error:
                editor = self.editors[key]
                with QSignalBlocker(editor):
                    editor.setKeySequence(QKeySequence(self._accepted_values[key]))
                editor._format_display(force=True)
                self.conflicts = {key: error}
                self._update_conflicts()
                self._show_conflict(key)
                return
            self._accepted_values[key] = values[key]
            self.conflicts.clear()
            self._update_conflicts()
            self._filter()
            self._show_conflict(key)
            self.changed.emit()

    def restore_defaults(self):
        self._updating = True
        for key, editor in self.editors.items():
            editor.setKeySequence(QKeySequence(DEFAULTS[key]))
        self._updating = False
        self._accepted_values = self.values()
        self.conflicts.clear()
        self._update_conflicts()
        self.conflict_hint.hide()
        self._filter()
        self.changed.emit()
