"""Resolve bundled and registered local themes; installation is a separate tool."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import json
import re

from picklight.paths import resource_root


ALLOWED_SUFFIXES = {".svg", ".png", ".jpg", ".jpeg", ".webp", ".ico", ".ttf", ".otf", ".json"}


class ThemeError(ValueError):
    pass


def _validate_style(style):
    """A small data-only visual contract; themes never execute CSS or code."""
    if not isinstance(style, dict) or set(style) - {"colors", "typography", "icons", "primary"}:
        raise ThemeError("主题样式字段无效。")
    colors = style.get("colors", {})
    if not isinstance(colors, dict) or len(colors) > 256 or any(
            not isinstance(key, str) or not isinstance(value, str) or
            not re.fullmatch(r"#[0-9a-fA-F]{6}", key) or
            not re.fullmatch(r"#[0-9a-fA-F]{6}", value) for key, value in colors.items()):
        raise ThemeError("主题颜色必须使用六位十六进制色值。")
    typography = style.get("typography", {})
    if not isinstance(typography, dict) or set(typography) - {"ui", "mono", "heading_weight"}:
        raise ThemeError("主题文字样式无效。")
    for role in ("ui", "mono"):
        families = typography.get(role, [])
        if not isinstance(families, list) or len(families) > 6 or any(
                not isinstance(name, str) or not re.fullmatch(r"[\w -]{1,80}", name)
                for name in families):
            raise ThemeError("主题字体名称无效。")
    if "heading_weight" in typography and (
            type(typography["heading_weight"]) is not int or
            typography["heading_weight"] not in (400, 500, 600, 700)):
        raise ThemeError("主题标题字重无效。")
    icons = style.get("icons", {})
    if not isinstance(icons, dict) or set(icons) - {"normal", "active", "disabled", "folder"} or any(
            not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color)
            for color in icons.values()):
        raise ThemeError("主题图标颜色无效。")
    primary = style.get("primary", {})
    if (not isinstance(primary, dict) or set(primary) - {"background", "hover", "border", "text"}
            or any(not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color)
                   for color in primary.values())):
        raise ThemeError("主题主按钮颜色无效。")


def _relative_path(value: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ThemeError("主题资源路径无效。")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in (".", "..") or
            re.search(r'[<>:"|?*\x00-\x1f]', part) or part.endswith((".", " ")) or
            re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?", part)
            for part in value.split("/")):
        raise ThemeError("主题资源必须使用包内的相对路径。")
    return Path(*path.parts)


@dataclass(frozen=True)
class IconTheme:
    id: str
    name: str
    root: Path
    manifest: dict
    bundled: bool = False

    @property
    def assets(self):
        return self.manifest["assets"]

    def asset(self, key: str) -> Path | None:
        value = self.assets.get(key)
        return self.root / _relative_path(value) if value else None


def read_theme(root: Path, *, bundled=False) -> IconTheme:
    try:
        manifest_path = root / "theme.json"
        if manifest_path.stat().st_size > 1024 * 1024:
            raise ThemeError("主题清单过大。")
        data = json.loads(manifest_path.read_text("utf-8"))
        if not isinstance(data, dict) or data.get("format_version") != 1:
            raise ThemeError("不支持此主题格式，请使用 format_version: 1。")
        theme_id, name = data.get("id"), data.get("name")
        if not isinstance(theme_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", theme_id):
            raise ThemeError("主题 ID 只能包含小写字母、数字、横线和下划线。")
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise ThemeError("主题名称无效。")
        assets = data.get("assets")
        _validate_style(data.get("style", {}))
        if not isinstance(assets, dict) or not assets or len(assets) > 2048:
            raise ThemeError("主题需要提供有效的 assets 资源清单。")
        for key, value in assets.items():
            if not re.fullmatch(r"[a-zA-Z0-9_.-]+", key):
                raise ThemeError("主题资源名称无效。")
            path = root / _relative_path(value)
            if (not path.resolve().is_relative_to(root.resolve()) or path.is_symlink() or
                    path.suffix.lower() not in ALLOWED_SUFFIXES or not path.is_file()):
                raise ThemeError(f"主题资源不可用：{key}")
        if "folder.icons.index" in assets:
            names = json.loads((root / _relative_path(assets["folder.icons.index"])).read_text("utf-8"))
            if (not isinstance(names, list) or len(names) > 1024 or
                    any(not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9_-]+", name) or
                        "folder.icon." + name not in assets for name in names)):
                raise ThemeError("文件夹图标索引必须列出主题提供的图标名称。")
        return IconTheme(theme_id, name.strip(), root, data, bundled)
    except (OSError, ValueError, TypeError) as exc:
        if isinstance(exc, ThemeError):
            raise
        raise ThemeError(f"无法读取主题：{exc}") from exc


def catalog_theme_ids(root: Path) -> list[str]:
    """Only catalogued themes are offered; loose folders are never auto-discovered."""
    try:
        data = json.loads((root / "catalog.json").read_text("utf-8"))
        values = data.get("themes", [])
        if not isinstance(values, list):
            return []
        return list(dict.fromkeys(value for value in values if isinstance(value, str) and
                                  re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", value)))
    except (OSError, ValueError, AttributeError):
        return []


class ThemeManager:
    def __init__(self, directory: Path, selected: str | None = None):
        self.directory = directory
        self.bundled_root = resource_root() / "assets" / "themes"
        catalog = json.loads((self.bundled_root / "catalog.json").read_text("utf-8"))
        default_id = catalog["default"]
        if default_id not in catalog_theme_ids(self.bundled_root):
            raise ThemeError("内置主题目录缺少默认主题。")
        self.default = read_theme(self.bundled_root / default_id, bundled=True)
        self.active = self.default
        self.select(selected)

    def themes(self):
        result, seen = [self.default], {self.default.id}
        for root, bundled in ((self.bundled_root, True), (self.directory, False)):
            for theme_id in catalog_theme_ids(root):
                if theme_id in seen:
                    continue
                path = root / theme_id
                if path.is_symlink():
                    continue
                try:
                    theme = read_theme(path, bundled=bundled)
                    if theme.id == theme_id:
                        result.append(theme)
                        seen.add(theme_id)
                except ThemeError:
                    continue
        return result

    def select(self, theme_id):
        available = self.themes()
        if theme_id in {"eagle", "local-eagle"}:
            theme_id = "elgae" if any(theme.id == "elgae" for theme in available) else "local-eagle"
        self.active = next((theme for theme in available if theme.id == theme_id), self.default)
        self.aliases = {value: key for theme in (self.default, self.active)
                        for key, value in theme.assets.items()}

    def resolve(self, key: str) -> Path:
        key = self.aliases.get(key, key)
        path = self.active.asset(key)
        if path is not None and path.is_file():
            return path
        fallback = self.default.asset(key)
        if fallback is not None:
            return fallback
        raise ThemeError(f"未注册的主题资源：{key}")


_manager: ThemeManager | None = None


def theme_manager() -> ThemeManager:
    global _manager
    if _manager is None:
        from picklight.session import default_settings_path
        _manager = ThemeManager(default_settings_path().parent / "themes")
    return _manager


def configure_theme(directory: Path, selected: str | None = None):
    global _manager
    _manager = ThemeManager(directory, selected)


def theme_asset_path(key: str) -> str:
    """Resolve a semantic key; omitted custom assets inherit the current default."""
    return str(theme_manager().resolve(key))
