"""Locate bundled resources in source runs and frozen Windows builds."""

from pathlib import Path
import sys


def resource_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))


def asset_path(name: str) -> str:
    """Resolve semantic theme keys, legacy asset aliases, or fixed branding."""
    from picklight.themes import theme_manager, theme_asset_path
    if (name in theme_manager().aliases or name in theme_manager().default.assets or
            name in theme_manager().active.assets):
        return theme_asset_path(name)
    return str(resource_root() / "assets" / name)
