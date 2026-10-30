"""Explicit source-file operations, coordinated with metadata readers/writers."""

import re

from PySide6.QtCore import QFile

from picklight.file_access import path_key, photo_files


def group_files(pairs, *, sidecars=False):
    paths = {}
    for pair in pairs:
        for path in (pair.jpg, pair.raw):
            if path is None:
                continue
            paths[path_key(path)] = path
            if sidecars:
                for sidecar in (path.with_suffix(".xmp"), path.with_suffix(".XMP")):
                    if sidecar.is_file():
                        paths[path_key(sidecar)] = sidecar
    return list(paths.values())


def file_identity(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"文件不存在或不是普通文件：{path}")
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def capture_files(paths):
    return {path: file_identity(path) for path in paths}


def _validate_files(files):
    for path, identity in files.items():
        if file_identity(path) != identity:
            raise ValueError(f"文件已发生变化，请重新选择：{path.name}")


def _rename_file(old, new):
    file = QFile(str(old))
    if not file.rename(str(new)):
        raise OSError(f"无法重命名 {old.name}：{file.errorString()}")


def rename_files(files, stem):
    """Rename one photo group without overwrites, rolling back partial failure."""
    if (not stem or stem != stem.strip() or stem.endswith(".") or len(stem) > 200
            or re.search(r'[<>:"/\\|?*\x00-\x1f]', stem)
            or re.fullmatch(r"(?i:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", stem)):
        raise ValueError("文件名无效，请勿使用路径、特殊字符或 Windows 保留名称")
    mapping = {path: path.with_name(stem + path.suffix) for path in files}
    with photo_files(list(files) + list(mapping.values())):
        _validate_files(files)
        for old, new in mapping.items():
            if old != new and new.exists() and path_key(old) != path_key(new):
                raise FileExistsError(f"目标文件已存在：{new.name}")
        moved = {}
        try:
            for old, new in mapping.items():
                if old == new:
                    continue
                _rename_file(old, new)
                moved[old] = new
        except Exception as error:
            failures = []
            for old, new in reversed(list(moved.items())):
                try:
                    _rename_file(new, old)
                except OSError:
                    failures.append(f"{new} → {old}")
            if failures:
                raise OSError(f"{error}\n以下文件未能恢复名称：\n" + "\n".join(failures)) from error
            raise
    return moved


def recycle_files(files):
    """Use the OS trash API only; never fall back to permanent deletion."""
    failures = []
    with photo_files(list(files)):
        _validate_files(files)
        for path in files:
            try:
                if file_identity(path) != files[path]:
                    raise ValueError("文件已变化")
                file = QFile(str(path))
                if not file.moveToTrash():
                    raise OSError(file.errorString())
            except Exception as error:
                failures.append(f"{path.name}：{error}")
    return failures
