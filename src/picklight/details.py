"""Asynchronous capture metadata for the inspector."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from picklight.loading import CachedLoader
from picklight.metadata import read_photo_details


class DetailsLoader(CachedLoader):
    ready = Signal(str, object)
    failed = Signal(str, str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent, name="picklight-details")

    def request(self, path: Path) -> None:
        key = str(path)
        self._request(key, read_photo_details, path, cancel=lambda old: old != key)
