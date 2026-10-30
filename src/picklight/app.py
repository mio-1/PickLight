"""Application entry point."""

from __future__ import annotations

import sys

from PySide6.QtGui import QFont, QFontDatabase, QIcon
from PySide6.QtWidgets import QApplication

from picklight.paths import asset_path
from picklight.session import SessionStore
from picklight.themes import configure_theme
from picklight.theme import STYLE
from picklight.startup import StartupController


def main():
    preferences = None
    if "--startup-splash" not in sys.argv:
        from picklight.preferences import read_startup_preferences, configure_startup_scale
        preferences = read_startup_preferences()
        configure_startup_scale(preferences)
    app = QApplication(sys.argv)
    app.setApplicationName("PickLight")
    app.setStyle("Fusion")
    if not QFontDatabase.families():
        # Qt's offscreen platform can start without system font discovery.
        QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
        QFontDatabase.addApplicationFont("C:/Windows/Fonts/segoeui.ttf")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setStyleSheet(STYLE)
    app.setWindowIcon(QIcon(asset_path("picklight.ico")))
    if "--startup-splash" in sys.argv:
        from picklight.splash_process import run_splash_process
        index = sys.argv.index("--startup-splash")
        if index + 1 >= len(sys.argv):
            return 2
        return run_splash_process(app, sys.argv[index + 1])
    store = SessionStore()
    app._picklight_startup_scale = preferences.scale
    configure_theme(store.path.parent / "themes", store.data.get("icon_theme"))
    app._startup_controller = StartupController(app)
    app._startup_controller.start()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
