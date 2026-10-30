"""Lazy access to consistent in-app warnings, including startup failures."""


class MessageBox:
    @staticmethod
    def _show(parent, title, message):
        from picklight.folder_dialogs import NoticeDialog
        dialog = NoticeDialog(title, message, parent)
        try:
            return dialog.exec()
        finally:
            dialog.deleteLater()

    @staticmethod
    def warning(parent, title, message):
        return MessageBox._show(parent, title, message)

    @staticmethod
    def critical(parent, title, message):
        return MessageBox._show(parent, title, message)
