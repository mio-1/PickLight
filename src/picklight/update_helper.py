"""Standalone Windows updater. This process runs outside the application directory."""

import ctypes
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile


MANAGED = {"PickLight.exe", "PickLightUpdater.exe", "_internal", "assets", "docs", "LICENSE", "README.md"}


def verify_package(package, expected):
    digest = hashlib.sha256()
    with package.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise ValueError("Update checksum mismatch")


def extract_portable(package, directory):
    """Reject traversal, links and unexpected roots before extracting anything."""
    with zipfile.ZipFile(package) as archive:
        names, size = set(), 0
        for entry in archive.infolist():
            name = entry.filename.replace("\\", "/")
            path = PurePosixPath(name)
            if (path.is_absolute() or ".." in path.parts or ":" in name
                    or not path.parts or path.parts[0] != "PickLight"
                    or (len(path.parts) > 1 and path.parts[1] not in MANAGED)
                    or (entry.external_attr >> 16) & 0o170000 == 0o120000):
                raise ValueError("Invalid portable package path")
            key = name.rstrip("/").casefold()
            if key in names:
                raise ValueError("Duplicate portable package entry")
            names.add(key)
            size += entry.file_size
            if size > 4 * 1024 ** 3:
                raise ValueError("Portable package is too large")
        if not {"picklight/picklight.exe", "picklight/picklightupdater.exe"} <= names:
            raise ValueError("Incomplete portable package")
        if not any(name.startswith("picklight/_internal/") for name in names):
            raise ValueError("Missing application runtime")
        archive.extractall(directory)
    return directory / "PickLight"


def apply_portable(staged, target, backup):
    """Replace managed roots and restore them if any move fails."""
    backup.mkdir()
    saved, placed = [], []
    try:
        for path in staged.iterdir():
            destination = target / path.name
            if destination.exists():
                destination.rename(backup / path.name)
                saved.append(path.name)
            path.rename(destination)
            placed.append(path.name)
    except Exception:
        restore_portable(staged, target, backup, saved, placed)
        raise
    return saved, placed


def restore_portable(staged, target, backup, saved, placed):
    # Move new files aside before restoring originals; retain backup on failure.
    for name in reversed(placed):
        (target / name).rename(staged / name)
    for name in reversed(saved):
        (backup / name).rename(target / name)


def install_package(package, target, log):
    args = [str(package), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
            "/SP-", "/CLOSEAPPLICATIONS", "/NORESTARTAPPLICATIONS",
            f"/DIR={target}", f"/LOG={log}"]
    result = subprocess.run(args, cwd=package.parent, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Installer exited with code {result.returncode}")


def wait_for_exit(process_id, cancelled, timeout=120):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_uint32]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x00100000, False, process_id)
    if not handle:
        if ctypes.get_last_error() == 87:  # The process has already exited.
            return
        raise OSError("Cannot wait for the application to exit")
    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if cancelled.exists():
                raise RuntimeError("Update cancelled")
            state = kernel.WaitForSingleObject(handle, 200)
            if state == 0:
                return
            if state != 258:
                raise OSError("Cannot wait for the application to exit")
        raise TimeoutError("The application is still running")
    finally:
        kernel.CloseHandle(handle)


def run_job(job_path):
    work = job_path.parent.resolve()
    job = json.loads(job_path.read_text(encoding="utf-8"))
    target = Path(job["target"]).resolve(strict=True)
    package = Path(job["package"]).resolve(strict=True)
    executable = target / "PickLight.exe"
    if (package.parent != work or not executable.is_file() or work.is_relative_to(target)
            or target == Path(target.anchor) or target == Path.home()
            or target.is_symlink() or job["kind"] not in ("installer", "portable")):
        raise ValueError("Invalid update destination")
    verify_package(package, job["sha256"])
    staging = None
    exited = False
    replacement = None
    try:
        if job["kind"] == "portable":
            staging = Path(tempfile.mkdtemp(prefix=".picklight-update-", dir=target))
            staged = extract_portable(package, staging)
        (work / "ready").touch()
        wait_for_exit(int(job["pid"]), work / "cancel")
        exited = True
        if (work / "cancel").exists():
            raise RuntimeError("Update cancelled")
        if job["kind"] == "installer":
            install_package(package, target, work / "installer.log")
        else:
            replacement = apply_portable(staged, target, staging / "backup")
        subprocess.Popen([str(executable)], cwd=target)
        (work / "complete").touch()
    except Exception:
        if replacement is not None:
            restore_portable(staged, target, staging / "backup", *replacement)
        if exited:
            # A failed replacement restores the previous version before restarting.
            subprocess.Popen([str(executable)], cwd=target)
        raise
    finally:
        if staging is not None:
            backup = staging / "backup"
            # Never remove a backup that still contains files after rollback failed.
            if not backup.exists() or not any(backup.iterdir()) or (work / "complete").exists():
                shutil.rmtree(staging, ignore_errors=True)


def main():
    if len(sys.argv) != 2:
        return 2
    job = Path(sys.argv[1]).resolve()
    try:
        run_job(job)
    except Exception as error:
        (job.parent / "error").write_text(str(error), encoding="utf-8")
        if (job.parent / "ready").exists() and not (job.parent / "cancel").exists():
            ctypes.windll.user32.MessageBoxW(None,
                "更新未能完成，已尝试恢复原版本。请重新打开 PickLight 后重试。\n"
                f"日志：{job.parent}", "PickLight 更新", 0x10)
        return 1
    # Windows releases keep the running helper locked. Remove downloads but leave
    # the small helper/log directory available for troubleshooting.
    try:
        package = Path(json.loads(job.read_text(encoding="utf-8"))["package"])
        package.unlink(missing_ok=True)
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
