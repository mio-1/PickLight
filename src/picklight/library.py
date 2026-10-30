"""Discover photos beneath one imported folder without changing source files."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


JPEG_EXTENSIONS = {".jpg", ".jpeg"}
RAW_EXTENSIONS = {
    ".3fr", ".arw", ".bay", ".cap", ".cr2", ".cr3", ".crw", ".dcr", ".dng", ".erf", ".fff",
    ".iiq", ".k25", ".kdc", ".mef", ".mos", ".mrw", ".nef",
    ".nrw", ".orf", ".ori", ".pef", ".ptx", ".pxn", ".raf", ".raw", ".rw2", ".rwl", ".rwz",
    ".sr2", ".srf", ".srw", ".x3f",
}
FORMAT_FOLDERS = {"jpg", "jpeg", "jpegs", "raw", "raws"}


@dataclass(frozen=True, slots=True)
class PhotoPair:
    key: str
    jpg: Path | None
    raw: Path | None
    conflict: bool = False

    @property
    def display_path(self) -> Path:
        return self.jpg or self.raw  # type: ignore[return-value]

    @property
    def pairing_label(self) -> str:
        if self.jpg and self.raw:
            return "JPG + RAW"
        status = "仅 JPG" if self.jpg else "仅 RAW"
        return f"配对冲突 · {status}" if self.conflict else status


def _context(path: Path, root: Path) -> str:
    """Treat format-only folders as transparent when comparing relative paths."""
    parts = [part.casefold() for part in path.relative_to(root).parent.parts
             if part.casefold() not in FORMAT_FOLDERS]
    return "/".join(parts)


def scan_pairs(project_folder: Path) -> list[PhotoPair]:
    """Pair matching stems under one source folder without importing its tree."""
    if not project_folder.is_dir():
        raise ValueError(f"工程文件夹不存在：{project_folder}")
    groups: dict[str, dict[str, list[Path]]] = defaultdict(lambda: {"jpg": [], "raw": []})
    for path in project_folder.rglob("*"):
        if not path.is_file():
            continue
        extension = path.suffix.casefold()
        kind = "jpg" if extension in JPEG_EXTENSIONS else "raw" if extension in RAW_EXTENSIONS else None
        if kind:
            groups[path.stem.casefold()][kind].append(path)

    result: list[PhotoPair] = []
    for stem, files in groups.items():
        jpg = sorted(files["jpg"], key=lambda path: path.as_posix().casefold())
        raw = sorted(files["raw"], key=lambda path: path.as_posix().casefold())
        used_jpg: set[Path] = set()
        used_raw: set[Path] = set()
        jpg_contexts: dict[str, list[Path]] = defaultdict(list)
        raw_contexts: dict[str, list[Path]] = defaultdict(list)
        for path in jpg:
            jpg_contexts[_context(path, project_folder)].append(path)
        for path in raw:
            raw_contexts[_context(path, project_folder)].append(path)
        for context in sorted(jpg_contexts.keys() & raw_contexts.keys()):
            candidates_jpg, candidates_raw = jpg_contexts[context], raw_contexts[context]
            if len(candidates_jpg) == len(candidates_raw) == 1:
                result.append(PhotoPair(f"{context}/{stem}".lstrip("/"), candidates_jpg[0], candidates_raw[0]))
                used_jpg.add(candidates_jpg[0])
                used_raw.add(candidates_raw[0])

        remaining_jpg = [path for path in jpg if path not in used_jpg]
        remaining_raw = [path for path in raw if path not in used_raw]
        if len(remaining_jpg) == len(remaining_raw) == 1:
            result.append(PhotoPair(
                f"{_context(remaining_jpg[0], project_folder)}/{stem}".lstrip("/"),
                remaining_jpg[0], remaining_raw[0],
            ))
            continue
        conflict = bool(remaining_jpg and remaining_raw)
        for kind, paths in (("jpg", remaining_jpg), ("raw", remaining_raw)):
            for path in paths:
                relative = path.relative_to(project_folder).as_posix().casefold()
                key = f"{kind}:{relative}"
                result.append(PhotoPair(key, path if kind == "jpg" else None,
                                        path if kind == "raw" else None, conflict))
    return sorted(result, key=lambda pair: (pair.display_path.stem.casefold(), pair.key))
