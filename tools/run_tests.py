"""Run focused or full regression tests with isolated Qt state and timings."""

import argparse
import json
import os
from pathlib import Path
import sys
import time
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
FAST_MODULES = (
    "test_core", "test_preview", "test_loading", "test_palette",
    "test_color_management", "test_photo_menu.PhotoFileTests",
    "test_preferences.PreferenceDataTests", "test_photo_badges",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("names", nargs="*", help="Optional test modules, classes or methods")
    parser.add_argument("--suite", choices=("fast", "full"), default="fast")
    parser.add_argument("--report", type=Path, help="Write per-test durations as JSON")
    args = parser.parse_args()
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    temporary = tempfile.TemporaryDirectory(prefix="picklight-tests-")
    os.environ["PICKLIGHT_SETTINGS"] = str(Path(temporary.name) / "settings.json")
    sys.path[:0] = [str(ROOT), str(ROOT / "src"), str(ROOT / "tests")]
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    for font in ("msyh.ttc", "segoeui.ttf"):
        path = Path("C:/Windows/Fonts") / font
        if path.is_file():
            QFontDatabase.addApplicationFont(str(path))
    timings = []

    class Result(unittest.TextTestResult):
        def startTest(self, test):
            self.started = time.perf_counter()
            self.active_test = test
            self.previous_hook = sys.excepthook
            sys.excepthook = self.qt_error
            super().startTest(test)

        def qt_error(self, kind, error, traceback):
            self.addError(self.active_test, (kind, error, traceback))

        def stopTest(self, test):
            # Drain queued zero-delay layout work while its receiver still exists.
            for _ in range(3):
                app.processEvents()
            # close() stops workers, but retained Qt trees otherwise accumulate
            # across tests and are restyled by every later QApplication sheet.
            for window in app.topLevelWidgets():
                loader = getattr(window, "loader", None)
                if loader is not None and loader.closed:
                    window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            sys.excepthook = self.previous_hook
            timings.append({"test": test.id(), "seconds": round(time.perf_counter() - self.started, 4)})
            super().stopTest(test)

    loader = unittest.TestLoader()
    if args.names:
        suite = loader.loadTestsFromNames(args.names)
    elif args.suite == "full":
        suite = loader.discover(str(ROOT / "tests"))
    else:
        suite = loader.loadTestsFromNames(FAST_MODULES)
    print(f"Running {suite.countTestCases()} tests ({'focused' if args.names else args.suite})", flush=True)
    try:
        result = unittest.TextTestRunner(verbosity=2, resultclass=Result).run(suite)
    finally:
        temporary.cleanup()
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(timings, indent=2), encoding="utf-8")
    print("\nSlowest tests:")
    for item in sorted(timings, key=lambda value: value["seconds"], reverse=True)[:8]:
        print(f"{item['seconds']:7.3f}s  {item['test']}")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
