"""Search and visual facets: OR within each selection, AND between facets."""

from dataclasses import dataclass, field

from picklight.library import PhotoPair
from picklight.palette import matches_palette

SEARCH_SCOPES = ("name", "folder.name", "folder.description", "extension")
FORMAT_LABELS = {"jpg": "仅有 JPG", "raw": "仅有 RAW", "both": "JPG+RAW 配对"}


@dataclass
class PhotoFilter:
    rating_min: int | None = None
    rating_max: int | None = None
    rating_values: set[int] = field(default_factory=set)
    states: set[str] = field(default_factory=set)
    format_mode: str | None = None
    color_rgb: tuple[int, int, int] | None = None
    color_gray: bool = False
    path_contains: str = ""
    search_scopes: set[str] = field(default_factory=lambda: set(SEARCH_SCOPES))

    @property
    def active(self) -> bool:
        return bool(self.rating_min is not None or self.rating_max is not None or
                    self.rating_values or self.color_rgb is not None or self.color_gray or
                    self.path_contains or self.states or self.format_mode is not None)

    def clear(self) -> None:
        self.rating_min = None
        self.rating_max = None
        self.rating_values.clear()
        self.states.clear()
        self.format_mode = None
        self.color_rgb = None
        self.color_gray = False
        self.path_contains = ""

    def paths(self, pair: PhotoPair) -> tuple:
        mode = "both" if pair.jpg and pair.raw else "jpg" if pair.jpg else "raw"
        if self.format_mode is not None and self.format_mode != mode:
            return ()
        return tuple(path for path in (pair.jpg, pair.raw) if path is not None)

    def matches(self, pair: PhotoPair, rating: int, marked: bool, *,
                except_facet: str | None = None, palettes=None,
                folder_description: str = "", kept: bool = False, candidate_paths=None) -> bool:
        if except_facet != "format" and not self.paths(pair):
            return False
        if except_facet != "status" and self.states:
            state = "reject" if marked else "keep" if kept else "none"
            if state not in self.states:
                return False
        if except_facet != "rating":
            if self.rating_values and rating not in self.rating_values:
                return False
            if self.rating_min is not None and rating < self.rating_min:
                return False
            if self.rating_max is not None and rating > self.rating_max:
                return False
        if except_facet != "color" and (self.color_rgb is not None or self.color_gray):
            if not matches_palette(palettes, self.color_rgb, self.color_gray):
                return False
        query = self.path_contains.casefold()
        if not query:
            return True
        paths = (candidate_paths if candidate_paths is not None else
                 tuple(path for path in (pair.jpg, pair.raw) if path) if except_facet == "format"
                 else self.paths(pair))
        values = []
        if "name" in self.search_scopes:
            values.extend(path.stem for path in paths)
        if "folder.name" in self.search_scopes:
            values.extend(part for path in paths for part in path.parent.parts[1:])
        if "folder.description" in self.search_scopes:
            values.append(folder_description)
        if "extension" in self.search_scopes:
            values.extend(value for path in paths
                          for value in (path.suffix, path.suffix.lstrip(".")))
            if "name" in self.search_scopes:
                values.extend(path.name for path in paths)
        return any(query in value.casefold() for value in values)
