"""Validated application preferences and Windows login integration."""

from dataclasses import asdict, dataclass
from pathlib import Path
import json
import os
import subprocess
import sys

from picklight.session import default_settings_path


APPEARANCES = (("auto", "跟随系统", "#ffffff"), ("light", "浅色", "#f5f5f5"),
               ("lightgray", "浅灰", "#b8b8bb"), ("gray", "深灰", "#494a4e"),
               ("dark", "深色", "#18191c"), ("blue", "深蓝", "#303342"),
               ("purple", "深紫", "#343141"))
SCALES = (50, 75, 80, 90, 100, 110, 125, 150, 175, 200)


@dataclass(frozen=True)
class Preferences:
    appearance: str = "dark"
    language: str = "zh_CN"
    scale: int = 100
    transparency: bool = True
    sidebar_counts: bool = True
    launch_at_login: bool = False
    gpu: bool = True

    @classmethod
    def from_data(cls, data):
        data = data if isinstance(data, dict) else {}
        defaults = asdict(cls())
        values = {key: value for key, value in data.items() if key in defaults}
        for key, default in defaults.items():
            if type(values.get(key)) is not type(default):
                values[key] = default
        if values["appearance"] not in {item[0] for item in APPEARANCES}:
            values["appearance"] = defaults["appearance"]
        if values["scale"] not in SCALES:
            values["scale"] = 100
        values["language"] = "zh_CN"  # Only advertise translations that actually exist.
        return cls(**values)


def read_startup_preferences():
    """Read without bootstrapping projects or writing the session file."""
    try:
        data = json.loads(default_settings_path().read_text(encoding="utf-8"))
        return Preferences.from_data(data.get("preferences") if isinstance(data, dict) else None)
    except (OSError, ValueError):
        return Preferences()


def configure_startup_scale(preferences):
    # Qt has no public, live per-application widget geometry scale API. Apply
    # before QApplication; multiply the caller's factor, never the OS setting.
    base = os.environ.get("PICKLIGHT_BASE_QT_SCALE")
    if base is None:
        base = os.environ.get("QT_SCALE_FACTOR", "1")
        os.environ["PICKLIGHT_BASE_QT_SCALE"] = base
    try:
        base_factor = float(base)
        if not 0.1 <= base_factor <= 8:
            base_factor = 1.0
    except ValueError:
        base_factor = 1.0
    os.environ["QT_SCALE_FACTOR"] = str(base_factor * preferences.scale / 100)


def launch_command():
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).resolve())]
    python = Path(sys.executable)
    windowless = python.with_name("pythonw.exe")
    return [str(windowless if windowless.exists() else python), "-m", "picklight.app"]


class LoginStartup:
    """Only manage PickLight's own HKCU Run value; never require admin rights."""
    key = r"Software\Microsoft\Windows\CurrentVersion\Run"
    name = "PickLight"

    @staticmethod
    def available():
        return sys.platform == "win32"

    def read(self):
        if not self.available():
            return None
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.key) as key:
                value, _ = winreg.QueryValueEx(key, self.name)
                return value
        except FileNotFoundError:
            return None

    def write(self, value):
        import winreg
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, self.key, 0, winreg.KEY_SET_VALUE) as key:
            if value is None:
                try:
                    winreg.DeleteValue(key, self.name)
                except FileNotFoundError:
                    pass
            else:
                winreg.SetValueEx(key, self.name, 0, winreg.REG_SZ, value)

    def set_enabled(self, enabled):
        if not self.available():
            if enabled:
                raise OSError("当前系统不支持开机自动启动")
            return
        self.write(subprocess.list2cmdline(launch_command()) if enabled else None)


def save_preferences(store, preferences, *, login=None, shortcuts=None):
    """Do not lose unrelated session data; roll back a failed settings write."""
    login = login or LoginStartup()
    previous = store.data.get("preferences")
    previous_shortcuts = store.data.get("shortcuts")
    if shortcuts is not None:
        from picklight.shortcuts import DEFAULTS, validate
        shortcuts = validate(shortcuts)
    old = Preferences.from_data(previous)
    changed_login = old.launch_at_login != preferences.launch_at_login
    old_login = login.read() if changed_login else None
    if changed_login:
        login.set_enabled(preferences.launch_at_login)
    # Preserve unrecognized future preference fields too.
    store.data["preferences"] = {**(previous if isinstance(previous, dict) else {}), **asdict(preferences)}
    if shortcuts is not None:
        stored = dict(previous_shortcuts) if isinstance(previous_shortcuts, dict) else {}
        for key, value in shortcuts.items():
            stored.pop(key, None)
            if value != DEFAULTS[key]:
                stored[key] = value
        store.data["shortcuts"] = stored
    try:
        store.save()
    except OSError:
        if previous is None:
            store.data.pop("preferences", None)
        else:
            store.data["preferences"] = previous
        if previous_shortcuts is None:
            store.data.pop("shortcuts", None)
        else:
            store.data["shortcuts"] = previous_shortcuts
        if changed_login:
            login.write(old_login)
        raise
