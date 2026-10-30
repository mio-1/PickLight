"""Local themes remain data-only and resolve every UI asset consistently."""

import json
import os
import shutil
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from picklight.themes import ThemeError, ThemeManager, read_theme


SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><rect width="16" height="16" fill="#ff0000"/></svg>'


def write_local_theme(directory, *, theme_id="test-theme", **overrides):
    root = directory / theme_id
    (root / "icons").mkdir(parents=True, exist_ok=True)
    manifest = {"format_version": 1, "id": theme_id, "name": "Test theme",
                "assets": {"app.menu": "icons/menu.svg"}}
    manifest.update(overrides)
    (root / "theme.json").write_text(json.dumps(manifest), encoding="utf8")
    (root / "icons/menu.svg").write_text(SVG, encoding="utf8")
    (directory / "catalog.json").write_text(json.dumps({"themes": [theme_id]}), encoding="utf8")
    return root


class ThemeTests(unittest.TestCase):
    def test_legacy_private_choices_resolve_to_elgae_without_changing_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_local_theme(root, theme_id="elgae", name="Elgae", private=True)
            original = (root / "catalog.json").read_bytes()
            manager = ThemeManager(root)
            for selected in ("elgae", "local-eagle", "eagle"):
                manager.select(selected)
                self.assertEqual(manager.active.id, "elgae")
                self.assertEqual(manager.active.name, "Elgae")
            self.assertEqual((root / "catalog.json").read_bytes(), original)

    def test_registered_private_theme_overrides_assets_and_inherits_missing_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = ThemeManager(Path(directory) / "themes")
            write_local_theme(manager.directory)
            manager.select("test-theme")
            self.assertEqual(manager.resolve("app.menu").read_text(), SVG)
            self.assertEqual(manager.resolve("icons/app-menu.svg"), manager.resolve("app.menu"))
            self.assertEqual(manager.resolve("toolbar.back"), manager.default.asset("toolbar.back"))

    def test_invalid_theme_manifests_are_rejected_and_omitted(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = ThemeManager(Path(directory) / "themes")
            cases = [
                {"assets": {"app.menu": "missing.svg"}},
                {"assets": {"app.menu": "../escaped.svg"}},
                {"format_version": 99},
                {"id": "../bad"},
                {"style": {"qss": "QWidget { width: 0; }"}},
                {"style": {"colors": {"#ffffff": "url(secret)"}}},
                {"style": {"typography": {"ui": ['Arial"; image: url(secret)']}}},
                {"style": {"icons": {"normal": "red"}}},
                {"style": {"primary": {"background": "url(secret)"}}},
                {"style": {"primary": {"padding": "0"}}},
            ]
            for values in cases:
                with self.subTest(values=values):
                    root = write_local_theme(manager.directory, **values)
                    with self.assertRaises(ThemeError):
                        read_theme(root)
                    self.assertEqual([theme.id for theme in manager.themes()], ["elgae", "github"])

    def test_missing_theme_falls_back_without_rewriting_registered_files(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = ThemeManager(Path(directory) / "themes", "missing")
            self.assertTrue(manager.active.bundled)
            root = write_local_theme(manager.directory)
            before = (root / "theme.json").read_bytes()
            manager.select("test-theme")
            manager.select("missing")
            self.assertEqual(manager.active.id, "elgae")
            self.assertEqual((root / "theme.json").read_bytes(), before)

    def test_only_catalogued_themes_are_offered_and_app_has_no_installer(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = ThemeManager(Path(directory) / "themes")
            write_local_theme(manager.directory)
            (manager.directory / "catalog.json").unlink()
            self.assertEqual([theme.id for theme in manager.themes()], ["elgae", "github"])
            self.assertFalse(hasattr(manager, "install"))
            self.assertFalse(hasattr(manager, "export"))

    def test_release_staging_excludes_unlisted_themes_and_unrelated_files(self):
        from tools.stage_release_assets import stage_assets
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assets = root / "assets"
            github = assets / "themes" / "github"
            github.mkdir(parents=True)
            for name in ("picklight.ico", "picklight.png"):
                (assets / name).write_bytes(b"branding")
            (assets / "private-art.svg").write_text(SVG)
            (github / "theme.json").write_text(json.dumps({
                "format_version": 1, "id": "github", "name": "GitHub",
                "assets": {"app.menu": "menu.svg"}}))
            (github / "menu.svg").write_text(SVG)
            (github / "unlisted.svg").write_text(SVG)
            (assets / "themes" / "catalog.json").write_text(json.dumps({
                "default": "github", "themes": ["github"]}))
            (assets / "themes" / "private").mkdir()
            staged = stage_assets(root)
            files = {path.relative_to(staged).as_posix() for path in staged.rglob("*") if path.is_file()}
            self.assertEqual(files, {"picklight.ico", "picklight.png", "themes/catalog.json",
                                     "themes/github/theme.json", "themes/github/menu.svg"})

    def test_original_default_has_complete_renderable_assets_and_license(self):
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QImage
        from PySide6.QtSvg import QSvgRenderer
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory:
            manager = ThemeManager(Path(directory))
            self.assertEqual(manager.default.id, "elgae")
            self.assertTrue((manager.default.root / "LICENSE_FONT").is_file())
            for theme in manager.themes():
                self.assertTrue((theme.root / "LICENSE").is_file())
                if theme.id == "github":
                    self.assertEqual(theme.manifest["license"], "MIT")
                    self.assertNotIn("inspector.mono", theme.assets)
                for key in theme.assets:
                    path = theme.asset(key)
                    if path.suffix == ".svg":
                        self.assertTrue(QSvgRenderer(str(path)).isValid(), key)
                    elif path.suffix == ".png":
                        self.assertFalse(QImage(str(path)).isNull(), key)

    def test_release_contains_default_elgae_resources_and_licenses(self):
        from tools.stage_release_assets import stage_assets
        source = Path(__file__).resolve().parents[1] / "assets"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assets = root / "assets"
            assets.mkdir()
            for name in ("picklight.ico", "picklight.png"):
                shutil.copy2(source / name, assets / name)
            shutil.copytree(source / "themes", assets / "themes")
            staged = stage_assets(root)
            catalog = json.loads((staged / "themes/catalog.json").read_text("utf-8"))
            self.assertEqual(catalog["default"], "elgae")
            theme = read_theme(staged / "themes/elgae")
            self.assertTrue(theme.asset("inspector.mono").is_file())
            for name in ("LICENSE", "LICENSE_FONT", "LICENSE_OCTICONS"):
                self.assertTrue((theme.root / name).is_file(), name)
            self.assertTrue(all(theme.asset(key).is_file() for key in theme.assets))
            self.assertFalse(any(path.suffix.lower() in (".cmd", ".ps1", ".py", ".exe")
                                 for path in staged.rglob("*")))

    def test_live_switch_rebuilds_widgets_and_persists_choice(self):
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QIcon, QImage
        from picklight.window import MainWindow
        from picklight.preferences_dialog import PreferencesDialog
        from picklight.themes import theme_manager
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, {"PICKLIGHT_SETTINGS": str(root / "settings.json")}):
                original = MainWindow()
                replacement = None
                try:
                    write_local_theme(theme_manager().directory, style={
                        "colors": {"#1f2023": "#252a30", "#18191c": "#101317"},
                        "typography": {"ui": ["Consolas", "Microsoft YaHei UI"], "heading_weight": 500}})
                    dialog = PreferencesDialog(original)
                    self.assertEqual(dialog.icon_theme.count(), 3)
                    self.assertGreaterEqual(dialog.icon_theme.findText("Test theme"), 0)
                    dialog.close()
                    source = root / "photos"
                    source.mkdir()
                    image = QImage(64, 48, QImage.Format.Format_RGB32)
                    image.fill("#526e7d")
                    image.save(str(source / "unique-select.JPG"), "JPEG")
                    image.save(str(source / "other.JPG"), "JPEG")
                    original.open_project(source)
                    original._open_sidebar_view("all")
                    original.filters.path_contains = "unique-select"
                    original._apply_filter()
                    original.filter_button.setChecked(True)
                    original._show_loupe()
                    original._apply_icon_theme("test-theme")
                    replacement = app._main_window
                    self.assertIsNot(replacement, original)
                    self.assertTrue(original.loader.closed)
                    self.assertEqual(replacement.store.data["icon_theme"], "test-theme")
                    self.assertEqual(theme_manager().active.id, "test-theme")
                    self.assertEqual(replacement._sidebar_selection, "collection")
                    self.assertEqual(len(replacement.visible), 1)
                    self.assertEqual(replacement._current_preview_path().name, "unique-select.JPG")
                    self.assertEqual(replacement.center_stack.currentIndex(), 1)
                    self.assertTrue(replacement.filter_bar.isHidden())
                    pixmap = replacement.menu_button.icon().pixmap(16, 16, QIcon.Mode.Normal)
                    color = pixmap.toImage().pixelColor(8, 8)
                    self.assertEqual(color.name(), "#ff0000")
                    self.assertTrue(replacement.sidebar_toggle.icon().isNull() is False)
                    app.processEvents()
                    from picklight.appearance import ui_color, theme_font
                    self.assertEqual(ui_color("#18191c").name(), "#101317")
                    self.assertEqual(theme_font().families()[0], "Consolas")
                    self.assertEqual(replacement.file_label.font().family(), "Consolas")
                    self.assertEqual(json.loads((root / "settings.json").read_text("utf-8"))["icon_theme"], "test-theme")
                finally:
                    if replacement:
                        replacement.close()
                    if not original.loader.closed:
                        original.close()


if __name__ == "__main__":
    unittest.main()
