"""Modal folder deletion and destination selection surfaces."""

from html import escape

from PySide6.QtCore import QEvent, QPersistentModelIndex, QSize, Qt
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPalette
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QToolButton,
    QTreeWidgetItem,
    QVBoxLayout,
)

from picklight.paths import asset_path
from picklight.ui.graphics import theme_icon


class FolderModal(QDialog):
    def __init__(self, parent):
        super().__init__(parent, Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setModal(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.surface = QFrame(objectName="folderModalSurface")
        layout.addWidget(self.surface)
        self._shade = None

    def showEvent(self, event):
        super().showEvent(event)
        parent = self.parentWidget()
        if parent is not None:
            self.move(parent.mapToGlobal(parent.rect().center()) - self.rect().center())
        elif QGuiApplication.primaryScreen() is not None:
            self.move(QGuiApplication.primaryScreen().availableGeometry().center() - self.rect().center())
        if self._shade is None and parent is not None:
            root = parent.centralWidget() if hasattr(parent, "centralWidget") else getattr(parent, "surface", parent)
            self._shade = QFrame(root)
            self._shade.setProperty("preserveContentColors", True)
            self._shade.setStyleSheet("background: rgba(0, 0, 0, 140);")
            self._shade.setGeometry(root.rect())
            self._shade.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            self._shade.show()
            self._shade.raise_()
            root.installEventFilter(self)
        self.raise_()

    def eventFilter(self, watched, event):
        if self._shade is not None and event.type() == QEvent.Type.Resize:
            self._shade.setGeometry(watched.rect())
        return super().eventFilter(watched, event)

    def hideEvent(self, event):
        if self._shade is not None:
            self._shade.parentWidget().removeEventFilter(self)
            self._shade.hide()
            self._shade.deleteLater()
            self._shade = None
        super().hideEvent(event)


class FolderConfirmation(FolderModal):
    """Shared warning layout; each operation supplies its text and extra controls."""

    def __init__(self, title, message, parent, *, warning="modal.warning"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setFixedWidth(400)
        layout = QHBoxLayout(self.surface)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        icon = QLabel()
        icon.setPixmap(theme_icon(warning, 36).pixmap(36, 36))
        icon.setFixedSize(36, 36)
        layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        self.content = QVBoxLayout()
        self.content.setSpacing(10)
        self.content.addWidget(QLabel(title, objectName="folderModalTitle"))
        self.message = QLabel(message, objectName="folderModalBody")
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setWordWrap(True)
        self.content.addWidget(self.message)
        layout.addLayout(self.content, 1)

    def add_buttons(self, title, *, spacing=6, cancel_default=False):
        self.content.addSpacing(spacing)
        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        self.cancel_button = QPushButton("取消", objectName="folderModalCancel")
        self.confirm_button = QPushButton(title, objectName="folderModalPrimary")
        for button in (self.cancel_button, self.confirm_button):
            button.setFixedHeight(32)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_button.clicked.connect(self.reject)
        self.confirm_button.clicked.connect(self.accept)
        buttons.addWidget(self.cancel_button, 3)
        buttons.addWidget(self.confirm_button, 5)
        self.content.addLayout(buttons)
        self.adjustSize()
        if cancel_default:
            self.cancel_button.setDefault(True)
            self.cancel_button.setFocus()

    def add_confirmation(self, title="确定"):
        self.content.addSpacing(6)
        self.confirm_button = QPushButton(title, objectName="folderModalPrimary")
        self.confirm_button.setFixedHeight(32)
        self.confirm_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.confirm_button.setDefault(True)
        self.confirm_button.clicked.connect(self.accept)
        self.content.addWidget(self.confirm_button)
        self.adjustSize()


class NoticeDialog(FolderConfirmation):
    def __init__(self, title, message, parent=None, *, icon="modal.warning"):
        super().__init__(title, message, parent, warning=icon)
        self.add_confirmation()


class InputDialog:
    @staticmethod
    def getText(parent, title, label, *, text=""):
        dialog = FolderConfirmation(title, label, parent, warning="menu.rename")
        field = QLineEdit(text, objectName="folderDestinationSearch")
        field.setFixedHeight(32)
        dialog.content.addWidget(field)
        dialog.add_buttons("确定")
        field.selectAll()
        field.setFocus()
        try:
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
            return field.text(), accepted
        finally:
            dialog.deleteLater()


class DeleteFolderDialog(FolderConfirmation):
    def __init__(self, name, parent):
        super().__init__("删除文件夹", f'这个操作无法复原，确认删除“{name}”文件夹吗？', parent)
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        hint = QHBoxLayout()
        hint.setSpacing(6)
        icon = QLabel()
        icon.setFixedSize(14, 14)
        icon.setPixmap(theme_icon("modal.info", 14).pixmap(14, 14))
        hint.addWidget(icon, 0, Qt.AlignmentFlag.AlignVCenter)
        self.photo_hint = QLabel("原始照片将保留在源目录中", objectName="folderModalHint")
        self.photo_hint.setStyleSheet("font-size: 11px; color: #929397;")
        self.photo_hint.setWordWrap(True)
        hint.addWidget(self.photo_hint, 1)
        self.content.addLayout(hint)
        self.add_buttons("确认删除", cancel_default=True)


class DeleteFilesDialog(FolderConfirmation):
    def __init__(self, groups, jpg, raw, sidecars, parent):
        super().__init__("删除文件", f"将删除所选的 {groups} 组图片原始文件", parent)
        self.surface.layout().setContentsMargins(22, 22, 22, 20)
        self.surface.layout().setSpacing(14)
        self.content.setSpacing(8)
        self.content.itemAt(0).widget().setFixedHeight(22)
        self.counts = {"JPG": jpg, "RAW": raw}
        if sidecars:
            self.counts["XMP"] = sidecars
        summary = QGridLayout()
        summary.setContentsMargins(0, 4, 0, 4)
        summary.setHorizontalSpacing(16)
        summary.setVerticalSpacing(5)
        for row, (kind, count) in enumerate(self.counts.items()):
            label = QLabel(kind, objectName="folderModalBody")
            label.setFixedWidth(36)
            summary.addWidget(label, row, 0)
            summary.addWidget(QLabel(f"{count} 个文件", objectName="fileDeleteCount"), row, 1)
        summary.setColumnStretch(1, 1)
        self.content.addLayout(summary)
        hint = QHBoxLayout()
        hint.setContentsMargins(0, 2, 0, 2)
        hint.setSpacing(6)
        icon = QLabel()
        icon.setFixedSize(14, 14)
        icon.setPixmap(theme_icon("modal.info", 14).pixmap(14, 14))
        hint.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        self.recovery_hint = QLabel("原始文件将移入 Windows 回收站\n可在系统回收站中恢复", objectName="fileDeleteHint")
        self.recovery_hint.setWordWrap(True)
        hint.addWidget(self.recovery_hint, 1)
        self.content.addLayout(hint)
        self.add_buttons("删除文件", spacing=8, cancel_default=True)


class MoveFolderConfirmation(FolderConfirmation):
    def __init__(self, source_name, target_name, relation, parent):
        source = f'<span style="color:#3297ff">{escape(source_name)}</span>'
        target = f'<span style="color:#3297ff">{escape(target_name)}</span>'
        ending = {"inside": "里面，作为子文件夹吗？", "before": "上面吗？", "after": "下面吗？"}[relation]
        super().__init__("移动文件夹", f'确定要将“{source}”移动至“{target}”{ending}', parent)
        self.message.setTextFormat(Qt.TextFormat.RichText)
        self.add_buttons("移动文件夹")


class MoveFolderDialog(FolderModal):
    def __init__(self, projects, source_id, tree, parent):
        super().__init__(parent)
        self.setWindowTitle("移动文件夹")
        self.resize(440, min(760, max(420, parent.height() - 70)))
        self.selected_parent_id = None
        self.selected_target_id = None
        self.selected_relation = "inside"
        self.source_id = source_id
        self.projects = {project["id"]: project for project in projects}
        layout = QVBoxLayout(self.surface)
        layout.setContentsMargins(0, 0, 0, 12)
        layout.setSpacing(12)
        header = QHBoxLayout()
        header.setContentsMargins(14, 10, 10, 0)
        header.addWidget(QLabel("移动文件夹", objectName="folderMoveTitle"))
        header.addStretch()
        close = QToolButton()
        close.setObjectName("folderModalClose")
        close.setIcon(QIcon(asset_path("modal.close")))
        close.setIconSize(QSize(16, 16))
        close.setFixedSize(24, 24)
        close.setAccessibleName("关闭")
        close.clicked.connect(self.reject)
        header.addWidget(close)
        layout.addLayout(header)
        separator = QFrame(objectName="folderModalSeparator")
        separator.setFixedHeight(1)
        layout.addWidget(separator)
        body = QVBoxLayout()
        body.setContentsMargins(12, 0, 12, 0)
        body.setSpacing(14)
        self.search = QLineEdit()
        self.search.setObjectName("folderDestinationSearch")
        self.search.setPlaceholderText("搜索")
        self.search.addAction(QIcon(asset_path("search")), QLineEdit.ActionPosition.LeadingPosition)
        self.search.setFixedHeight(30)
        self.search.setClearButtonEnabled(True)
        body.addWidget(self.search)
        body.addWidget(QLabel("在下方列表选择移动的位置：", objectName="folderModalHint"))
        self.tree = tree
        tree.setObjectName("projectList")
        palette = tree.palette()
        palette.setColor(QPalette.ColorRole.Highlight, QColor(0, 0, 0, 0))
        tree.setPalette(palette)
        tree.setHeaderHidden(True)
        tree.setIndentation(20)
        tree.setRootIsDecorated(True)
        tree.setDragEnabled(False)
        tree.setAcceptDrops(False)
        tree.setExpandsOnDoubleClick(False)
        tree.destination_picking = True
        body.addWidget(tree, 1)
        layout.addLayout(body, 1)
        forbidden = {source_id}
        while True:
            children = {p["id"] for p in projects if p.get("parent_id") in forbidden}
            if children <= forbidden:
                break
            forbidden |= children
        self.items = {}
        for project in projects:
            item = QTreeWidgetItem([project["name"]])
            item.setData(0, Qt.ItemDataRole.UserRole, project["id"])
            item.setData(0, Qt.ItemDataRole.UserRole + 4, project.get("icon", ""))
            item.setData(0, Qt.ItemDataRole.UserRole + 5, project.get("color", ""))
            if project["id"] in forbidden:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled & ~Qt.ItemFlag.ItemIsSelectable)
            self.items[project["id"]] = item
        for project in projects:
            item = self.items[project["id"]]
            ancestor = self.items.get(project.get("parent_id"))
            if ancestor is not None:
                ancestor.addChild(item)
            else:
                tree.addTopLevelItem(item)
        tree.expandAll()
        self.search.textChanged.connect(self._filter)
        tree.destinationChosen.connect(self._choose)
        self.search.setFocus()

    def _filter(self, text):
        self.tree._insertion_target = QPersistentModelIndex()
        self.tree._drop_target = QPersistentModelIndex()
        query = text.strip().casefold()
        def visit(item):
            children = [visit(item.child(i)) for i in range(item.childCount())]
            visible = not query or query in item.text(0).casefold() or any(children)
            item.setHidden(not visible)
            if query and any(children):
                item.setExpanded(True)
            return visible
        for i in range(self.tree.topLevelItemCount()):
            visit(self.tree.topLevelItem(i))

    def _choose(self, item, relation="inside"):
        if not item.flags() & Qt.ItemFlag.ItemIsEnabled:
            return
        target_id = item.data(0, Qt.ItemDataRole.UserRole)
        target = self.projects[target_id]
        source = self.projects[self.source_id]
        confirmation = MoveFolderConfirmation(source["name"], target["name"], relation, self)
        result = confirmation.exec()
        confirmation.deleteLater()
        if result != QDialog.DialogCode.Accepted:
            self.tree._drop_target = QPersistentModelIndex()
            self.tree.viewport().update()
            return
        self.selected_target_id = target_id
        self.selected_relation = relation
        self.selected_parent_id = target_id if relation == "inside" else target.get("parent_id")
        self.accept()
