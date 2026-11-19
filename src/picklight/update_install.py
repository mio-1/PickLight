"""Launch the standalone updater only after a verified download is confirmed."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def installation_kind():
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return None
    root = Path(sys.executable).resolve().parent
    return "installer" if (root / "unins000.exe").is_file() else "portable"


def launch_update(package, asset):
    kind = installation_kind()
    if kind != asset.kind:
        raise ValueError("更新包与当前程序类型不匹配")
    root = Path(sys.executable).resolve().parent
    helper = root / "PickLightUpdater.exe"
    if not helper.is_file():
        raise OSError("更新组件缺失，请重新下载安装包")
    # The helper and all files it needs must be outside the directory it replaces.
    runner = package.parent / helper.name
    shutil.copy2(helper, runner)
    job = package.parent / "job.json"
    job.write_text(json.dumps({"target": str(root), "package": str(package),
                               "sha256": asset.sha256, "kind": kind, "pid": os.getpid()}), encoding="utf-8")
    environment = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
    process = subprocess.Popen([str(runner), str(job)], cwd=package.parent,
                               env=environment, creationflags=subprocess.CREATE_NO_WINDOW)
    return process
