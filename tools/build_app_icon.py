"""Build application PNG and multi-resolution Windows ICO from the brand master."""

from pathlib import Path
import struct

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage


def build_icon(assets: Path):
    image = QImage(str(assets / "branding" / "picklight-master.png"))
    if image.isNull() or image.width() != image.height() or not image.hasAlphaChannel():
        raise ValueError("The brand master must be a square PNG with transparency")
    sizes = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)
    entries, frames = [], []
    offset = 6 + 16 * len(sizes)
    for size in sizes:
        frame = image.scaled(size, size, Qt.AspectRatioMode.IgnoreAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not frame.save(buffer, "PNG"):
            raise ValueError(f"Unable to encode icon frame {size}")
        payload = bytes(data)
        entries.append(struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0,
                                   1, 32, len(payload), offset))
        frames.append(payload)
        offset += len(payload)
    (assets / "picklight.ico").write_bytes(struct.pack("<HHH", 0, 1, len(sizes))
                                           + b"".join(entries) + b"".join(frames))
    if not image.scaled(512, 512, Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.SmoothTransformation).save(str(assets / "picklight.png")):
        raise ValueError("Unable to save application PNG")


if __name__ == "__main__":
    build_icon(Path(__file__).resolve().parents[1] / "assets")
