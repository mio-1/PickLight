"""Build PickLight's GitHub-inspired theme from vendored MIT Octicons.

No network or installed private theme is used. The pinned upstream revision and
unmodified SVGs live in theme_sources/octicons; custom illustrations are original.
"""

from pathlib import Path
import json
import sys
import xml.etree.ElementTree as ET

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1] / "assets/themes/github"
SOURCES = Path(__file__).resolve().parent / "theme_sources/octicons"

ICONS = {
    "photo.menu.explorer": "file-directory", "photo.menu.location": "search",
    "photo.menu.rename": "pencil", "photo.menu.copy_path": "file-code", "photo.menu.delete": "trash",
    "preferences.general": "gear", "preferences.dropdown": "chevron-down", "import.cancel": "x",
    "app.menu": "three-bars", "check": "check", "filter.check": "check",
    "filter": "filter", "toolbar.filter": "filter", "filter.clear": "filter-remove",
    "filter.rating": "star", "filter.format": "file-code", "folder.closed": "file-directory", "folder.open": "file-directory-open-fill",
    "photo.keep": "shield-check", "photo.reject": "shield-x",
    "photo.badge.keep": "check", "photo.badge.reject": "x",
    "photo.none": "circle", "filter.status": "flag",
    "notification.success": "check-circle-fill", "modal.info": "info",
    "filter.facet.clear": "x-circle-fill", "hand": "grabber",
    "inspector.expand": "chevron-down", "layout.grid": "apps", "layout.waterfall": "columns",
    "loupe.back": "arrow-left", "loupe.fit": "screen-full", "loupe.rotate": "undo",
    "menu.emoji": "smiley",
    "menu.expand": "unfold", "menu.expand.same": "fold-down", "menu.expand.all": "unfold",
    "menu.folder.move": "file-moved", "menu.folder.new.folder": "file-directory",
    "menu.folder.new.sub.folder": "file-directory-symlink", "menu.folder.remove": "trash",
    "menu.rename": "pencil", "modal.close": "x", "modal.warning": "alert",
    "plus": "plus", "search.clear": "x-circle-fill", "search.dropdown": "chevron-down",
    "search": "search", "search.image": "image", "search.scope.name": "typography",
    "search.scope.description": "note", "search.scope.extension": "file-code",
    "sidebar.all": "inbox", "toggle.sidebar": "sidebar-collapse",
    "toolbar.back": "chevron-left", "toolbar.forward": "chevron-right",
    "toolbar.layout": "rows", "toolbar.zoom.in": "plus", "toolbar.zoom.out": "dash",
    "tree.arrow": "triangle-right", "rating.on": "star-fill", "rating.off": "star",
    "filter.star": "star-fill",
}
FOLDERS = {
    "camera": "device-camera", "image": "image", "star": "star", "heart": "heart",
    "travel": "globe", "mountain": "image", "portrait": "person", "city": "organization",
    "sun": "sun", "moon": "moon", "leaf": "light-bulb", "flower": "sparkle",
    "work": "briefcase", "archive": "archive", "bookmark": "bookmark", "tag": "tag",
    "video": "video", "music": "unmute", "palette": "paintbrush", "layers": "stack",
    "grid": "apps", "clock": "clock", "check": "check-circle", "flag": "flag",
}

# Colors are applied to UI paint only, then the user's separate color scheme.
COLORS = {}
for target, originals in {
    "#0d1117": "18191c 17181b 191a1c 131416 121316 1b1c1f 1a1a1d",
    "#151b23": "1f2023 202124 202024 20272e 1b1c20",
    "#212830": "242528 252529 2c2d30 26272a 292a2e 292a2d 27282c",
    "#2a313b": "303134 303136 333439 36373b 38393d 303135 303c4d",
    "#3d444d": "343538 34353a 37383c 393a3e 3b3c40 3b3b40 3c3d41 404145 414246 45454b 45454c",
    "#484f58": "4a4b4e 4b4c52 53565e 62626a 696a6e",
    "#f0f6fc": "ffffff f7f8f8 f7f7f8 f2f2f4 f0f0f2 e7e7eb e4e4e8 dedee2 dcdee2",
    "#b1bac4": "cbcbcc b6b7bb bdbec0 a7a8ad a6a7ad a5a6ac",
    "#8b949e": "77797e 797980 85868b 898a8e 929397 999a9e",
    "#58a6ff": "2ea8f4 229cff",
    "#1f6feb": "3297ff 2f98ff 2f8fe8",
    "#388bfd": "42a2ff 4ba6ff",
}.items():
    COLORS.update({"#" + value: target for value in originals.split()})


def icon(name, color="#F7F8F8"):
    source = (SOURCES / (name + "-16.svg")).read_text("utf-8")
    # Octicons are filled outlines, carefully hinted for a 16px grid.
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    root = ET.fromstring(source)
    root.set("fill", color)
    for element in root.iter():
        for name, value in list(element.attrib.items()):
            if value == "currentColor":
                element.set(name, color)
    return ET.tostring(root, encoding="unicode")


def inset_icon(source, inset=3):
    """Balance full 16px Octicons inside our existing 24px toolbar slots."""
    return source.replace('viewBox="0 0 16 16"', f'viewBox="-{inset} -{inset} {16+2*inset} {16+2*inset}"')


def raster(text, destination):
    image = QImage(704, 288, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    QSvgRenderer(QByteArray(text.encode())).render(painter, QRectF(0, 0, 704, 288))
    painter.end()
    if not image.save(str(destination)):
        raise RuntimeError(f"Could not write {destination}")


def illustration(search=False):
    badge = ('<circle cx="235" cy="101" r="15" fill="#161b22" stroke="#58a6ff" stroke-width="2"/>'
             '<path d="m246 112 11 11" stroke="#58a6ff" stroke-width="4" stroke-linecap="round"/>') if search else (
             '<circle cx="236" cy="102" r="17" fill="#1c3553" stroke="#58a6ff"/>'
             '<path d="M229 102h14 M236 95v14" stroke="#79c0ff" stroke-width="2" stroke-linecap="round"/>')
    return '''<svg xmlns="http://www.w3.org/2000/svg" width="352" height="144" viewBox="0 0 352 144">
    <ellipse cx="176" cy="128" rx="82" ry="5" fill="#0d1117" opacity=".5"/>
    <rect x="98" y="29" width="134" height="87" rx="8" fill="#161b22" stroke="#30363d" transform="rotate(-7 165 72)"/>
    <rect x="113" y="19" width="128" height="94" rx="8" fill="#161b22" stroke="#484f58"/>
    <path d="M113 40h128" stroke="#30363d"/>
    <circle cx="125" cy="30" r="2" fill="#484f58"/><circle cx="133" cy="30" r="2" fill="#484f58"/>
    <circle cx="141" cy="30" r="2" fill="#484f58"/>
    <rect x="127" y="51" width="99" height="47" rx="4" fill="#0d1117" stroke="#30363d"/>
    <circle cx="146" cy="65" r="4" fill="#58a6ff"/>
    <path d="m133 90 23-20 21 16 15-11 27 18" fill="none" stroke="#79c0ff" stroke-width="1.5" stroke-linejoin="round"/>
    <path d="M84 62h6 M87 59v6 M263 56h6 M266 53v6" stroke="#484f58" stroke-linecap="round"/>
    ''' + badge + '</svg>'


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    for directory in ("icons", "illustrations"):
        (ROOT / directory).mkdir(parents=True, exist_ok=True)
    assets = {}
    for key, name in ICONS.items():
        relative = f'icons/{key.replace(".", "-")}.svg'
        color = {"rating.on": "#e3b341", "rating.off": "#484f58", "filter.star": "black",
                 "notification.success": "#3fb950"}.get(key, "#F7F8F8")
        source = icon(name, color)
        if key == "photo.badge.reject":
            source = source.replace('viewBox="0 0 16 16"', 'viewBox="2 2 12 12"')
        elif key not in {"photo.badge.keep", "modal.close", "import.cancel", "preferences.dropdown", "inspector.expand", "search.dropdown", "tree.arrow", "check", "filter.check"}:
            source = inset_icon(source, 1 if key.startswith("rating.") else 3)
        (ROOT / relative).write_text(source, encoding="utf-8")
        assets[key] = relative
    for name, source in FOLDERS.items():
        relative = f"icons/folder-{name}.svg"
        (ROOT / relative).write_text(inset_icon(icon(source), 1), encoding="utf-8")
        assets["folder.icon." + name] = relative
    for key, name in {"sidebar.all": "sidebar-repository", "toolbar.layout": "layout-table",
                      "layout.grid": "layout-grid", "layout.waterfall": "layout-waterfall"}.items():
        relative = f'icons/{key.replace(".", "-")}.svg'
        (ROOT / relative).write_bytes((SOURCES.parent / "picklight" / (name + ".svg")).read_bytes())
        assets[key] = relative
    (ROOT / "folder-icons.json").write_text(json.dumps(list(FOLDERS), indent=2), encoding="utf-8")
    assets["folder.icons.index"] = "folder-icons.json"
    relative = "icons/loupe-auto-advance.svg"
    (ROOT / relative).write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">'
        '<g fill="none" stroke="#F7F8F8" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="m3 3 7 5-7 5z M12.5 2.5v11"/></g></svg>', encoding="utf-8")
    assets["loupe.auto.advance"] = relative
    relative = "icons/preferences-shortcuts.svg"
    (ROOT / relative).write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        '<g fill="none" stroke="#F7F8F8" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">'
        '<rect x="2.5" y="5" width="19" height="14" rx="2"/>'
        '<path d="M6 9h1m4 0h1m4 0h1M6 12h1m4 0h1m4 0h1M8 15.5h8"/></g></svg>', encoding="utf-8")
    assets["preferences.shortcuts"] = relative
    for kind in ("folder", "search"):
        text = illustration(kind == "search")
        relative = f"illustrations/empty-{kind}.png"
        raster(text, ROOT / relative)
        assets["empty." + kind] = relative
    # Keep the accepted hand silhouette and physical cursor sizing.
    for name in ("cursor-grab", "cursor-grabbing", "cursor-drag-move", "loading-spinner",
                 "filter-color", "filter-gray", "filter-gray-preset", "color-eyedropper", "color-mode"):
        relative = f"icons/{name}.svg"
        (ROOT / relative).write_bytes((SOURCES.parent / "picklight" / (name + ".svg")).read_bytes())
        assets[name.replace("-", ".")] = relative
    manifest = {"format_version": 1, "id": "github", "name": "GitHub", "version": "1.1.0",
                "publisher": "PickLight", "description": "Primer 深灰层次、仓库与目录图标、绿色主操作和系统字体。",
                "license": "MIT", "accent": "#58a6ff", "assets": assets,
                "style": {"colors": COLORS, "typography": {
                    "ui": ["Segoe UI Variable Text", "Segoe UI", "Microsoft YaHei UI"], "mono": ["Consolas", "Cascadia Mono"],
                    "heading_weight": 600}, "icons": {
                    "normal": "#a6adb5", "active": "#f0f6fc", "disabled": "#545d68", "folder": "#58a6ff"},
                    "primary": {"background": "#238636", "hover": "#2ea043", "border": "#2ea043", "text": "#ffffff"}}}
    (ROOT / "theme.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    catalog = ROOT.parent / "catalog.json"
    if not catalog.exists():
        catalog.write_text(json.dumps({"default": "github", "themes": ["github"]}, indent=2) + "\n", encoding="utf-8")
    license_text = (ROOT.parents[2] / "LICENSE").read_text("utf-8")
    (ROOT / "LICENSE").write_text(license_text + "\n\nOcticons — GitHub Inc.\n\n" +
                                  (SOURCES / "LICENSE").read_text("utf-8"), encoding="utf-8")
    print(f"Built {len(assets)} theme assets in {ROOT}")


if __name__ == "__main__":
    main()
