"""Stage only publisher-catalogued resources for the application package."""

from pathlib import Path
import shutil
import tempfile

from picklight.themes import catalog_theme_ids, read_theme


def stage_assets(project: Path) -> Path:
    source = project / "assets"
    build = project / "build"
    build.mkdir(exist_ok=True)
    target = Path(tempfile.mkdtemp(prefix="release-assets-", dir=build))
    for name in ("picklight.ico", "picklight.png"):
        shutil.copy2(source / name, target / name)
    themes_source = source / "themes"
    themes_target = target / "themes"
    themes_target.mkdir()
    shutil.copy2(themes_source / "catalog.json", themes_target / "catalog.json")
    for theme_id in catalog_theme_ids(themes_source):
        theme = read_theme(themes_source / theme_id)
        if theme_id in {"eagle", "local-eagle"} or theme.manifest.get("private") is True:
            raise ValueError("Private themes must not be listed in the release catalogue")
        root = themes_target / theme_id
        root.mkdir()
        shutil.copy2(theme.root / "theme.json", root / "theme.json")
        for relative in set(theme.assets.values()):
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(theme.root / relative, destination)
        for name in ("LICENSE", "LICENSE.txt", "LICENSE_FONT", "LICENSE_OCTICONS", "README.md"):
            if (theme.root / name).is_file():
                shutil.copy2(theme.root / name, root / name)
    return target


if __name__ == "__main__":
    print(stage_assets(Path(__file__).resolve().parents[1]))
