"""Extract representative preview colors with weighted median cuts."""

from __future__ import annotations

from colorsys import rgb_to_hls
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from functools import cmp_to_key, lru_cache
from threading import Event

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QImage

from picklight.preview import decode
from picklight.loading import CachedLoader
from picklight.color_management import to_srgb


@dataclass(frozen=True, slots=True)
class PaletteColor:
    rgb: tuple[int, int, int]
    ratio: float

    @property
    def detail(self) -> str:
        return "#{:02X}{:02X}{:02X} ({:.1f}%)".format(*self.rgb, self.ratio)


@lru_cache(maxsize=4096)
def _lab(rgb):
    linear = [((value / 255 + 0.055) / 1.055) ** 2.4 if value / 255 > 0.04045
              else value / 255 / 12.92 for value in rgb]
    red, green, blue = linear
    xyz = ((0.4124564 * red + 0.3575761 * green + 0.1804375 * blue) / 0.95047,
           0.2126729 * red + 0.7151522 * green + 0.0721750 * blue,
           (0.0193339 * red + 0.1191920 * green + 0.9503041 * blue) / 1.08883)
    x, y, z = [value ** (1 / 3) if value > 0.008856 else 7.787 * value + 16 / 116
               for value in xyz]
    return 116 * y - 16, 500 * (x - y), 200 * (y - z)


def matches_palette(colors, rgb=None, gray=False):
    if not colors:
        return False
    if gray:
        return sum(color.ratio for color in colors
                   if max(color.rgb) - min(color.rgb) <= 25) >= 85
    target = _lab(tuple(rgb))
    return any(color.ratio >= 0.25 and sum((a - b) ** 2 for a, b in
               zip(_lab(color.rgb), target)) <= 25 ** 2 for color in colors)


class _ColorBox:
    def __init__(self, points):
        self.points = points
        self.count = sum(point[3] for point in points)
        self.ranges = [max(p[axis] for p in points) - min(p[axis] for p in points)
                       for axis in range(3)]
        self.volume = (self.ranges[0] + 1) * (self.ranges[1] + 1) * (self.ranges[2] + 1)

    def split(self):
        axis = max(range(3), key=self.ranges.__getitem__)
        points = sorted(self.points, key=lambda point: point[axis])
        cumulative = 0
        candidates = []
        for index in range(1, len(points)):
            cumulative += points[index - 1][3]
            if points[index - 1][axis] != points[index][axis]:
                candidates.append((abs(cumulative - self.count / 2), index))
        cut = min(candidates)[1]
        return _ColorBox(points[:cut]), _ColorBox(points[cut:])

    def representative(self, total):
        rgb = tuple(min(255, round(sum((p[axis] * 8 + 4) * p[3]
                                     for p in self.points) / self.count)) for axis in range(3))
        return PaletteColor(rgb, round(self.count / total * 100, 2))


def extract_palette(image: QImage, max_colors: int = 12) -> list[PaletteColor]:
    if image.isNull():
        return []
    preview = (image.scaled(480, 480, Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation)
               if max(image.width(), image.height()) > 480 else image)
    preview = to_srgb(preview).convertToFormat(QImage.Format.Format_RGBA8888)
    data = bytes(preview.constBits())
    # Sampling keeps this work bounded even for very large decoded previews.
    step = 4 * (1 if len(data) < 100_000 else 10)
    histogram = {}
    for offset in range(0, len(data), step):
        if data[offset + 3] < 170:
            continue
        key = (data[offset] >> 3, data[offset + 1] >> 3, data[offset + 2] >> 3)
        histogram[key] = histogram.get(key, 0) + 1
    if not histogram:
        return []
    boxes = [_ColorBox([(*rgb, count) for rgb, count in histogram.items()])]
    total = boxes[0].count
    target = max(1, min(12, max_colors))
    while len(boxes) < target:
        candidates = [box for box in boxes if len(box.points) > 1]
        if not candidates:
            break
        # First preserve common colors, then spend the remaining boxes on variety.
        box = max(candidates, key=lambda value: value.count *
                  (1 if len(boxes) < target * 0.75 else value.volume))
        boxes.remove(box)
        boxes.extend(box.split())
    colors = [box.representative(total) for box in boxes]
    return sorted((color for color in colors if color.ratio >= 0.25),
                  key=lambda color: color.ratio, reverse=True)


def display_palette(colors: list[PaletteColor]) -> list[PaletteColor]:
    colors = sorted(colors, key=lambda color: color.ratio, reverse=True)[:10]
    if not colors:
        return []

    def hsl(color):
        h, lightness, saturation = rgb_to_hls(*(channel / 255 for channel in color.rgb))
        return h * 360, saturation * 100, lightness * 100

    dominant = hsl(colors[0])

    def compare(first, second):
        a = [abs(value - base) for value, base in zip(hsl(first), dominant)]
        b = [abs(value - base) for value, base in zip(hsl(second), dominant)]
        axis = 0 if abs(a[0] - b[0]) >= 30 else 1 if abs(a[1] - b[1]) >= 10 else 2
        return a[axis] - b[axis]

    return [colors[0], *sorted(colors[1:], key=cmp_to_key(compare))]


class PaletteLoader(CachedLoader):
    ready = Signal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent, name="picklight-palette", workers=1)

    def request(self, path: str, image: QImage, *, from_source=False):
        if from_source:
            # Color codes/filtering remain canonical sRGB, independent of display clipping.
            self._request(path, _source_palette, Path(path), cancel=lambda old: old != path)
        else:
            self._request(path, extract_palette, QImage(image), cancel=lambda old: old != path)

    def _failed(self, signal_args, error):
        self.ready.emit(*signal_args, [])


def _source_palette(path):
    return extract_palette(decode(path, 480))


class ColorIndexLoader(QObject):
    ready = Signal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="picklight-color-index")
        self.stop_event = Event()
        self.closed = False

    def request(self, token, paths):
        if self.closed:
            return
        self.stop_event.set()
        self.stop_event = Event()
        stop = self.stop_event

        def analyze():
            colors = {}
            for path in paths:
                if stop.is_set():
                    return
                try:
                    colors[str(path)] = extract_palette(decode(path, 480))
                except Exception:
                    colors[str(path)] = []
            if not stop.is_set() and not self.closed:
                self.ready.emit(token, colors)

        self.pool.submit(analyze)

    def cancel(self):
        self.stop_event.set()

    def shutdown(self):
        self.closed = True
        self.cancel()
        self.pool.shutdown(wait=True, cancel_futures=True)
