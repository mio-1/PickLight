"""ICC/EXIF preview conversion is consistent, bounded and source-preserving."""

import hashlib
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
from threading import get_ident
import time
import unittest
from unittest.mock import MagicMock, patch

import numpy as np
import rawpy
from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QColor, QColorSpace, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from picklight.color_management import file_color_space, space_from_tags, to_srgb
from picklight.palette import extract_palette
from picklight.preview import PreviewLoader, decode


def exif_tiff(color_space=65535, interop="R03", endian="<", orientation=None):
    def entry(tag, kind, count, value):
        return struct.pack(endian + "HHI", tag, kind, count) + value

    def number(value):
        return struct.pack(endian + "I", value)

    def directory(entries):
        return struct.pack(endian + "H", len(entries)) + b"".join(entries) + number(0)

    root_count = 1 if orientation is None else 2
    exif_offset = 8 + 2 + 12 * root_count + 4
    exif_count = 1 if interop is None else 2
    interop_offset = exif_offset + 2 + exif_count * 12 + 4
    root = [entry(0x8769, 4, 1, number(exif_offset))]
    if orientation is not None:
        root.insert(0, entry(0x112, 3, 1, struct.pack(endian + "H", orientation) + b"\0\0"))
    exif = [entry(0xA001, 3, 1, struct.pack(endian + "H", color_space) + b"\0\0")]
    tail = b""
    if interop is not None:
        exif.append(entry(0xA005, 4, 1, number(interop_offset)))
        tail = directory([entry(1, 2, 4, interop.encode("ascii") + b"\0")])
    return (b"II" if endian == "<" else b"MM") + struct.pack(endian + "HI", 42, 8) + directory(root) + directory(exif) + tail


def jpeg_bytes(image):
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "JPEG", 100):
        raise AssertionError("Unable to create JPEG fixture")
    return bytes(data)


def with_segment(jpeg, marker, payload):
    return jpeg[:2] + b"\xff" + bytes([marker]) + struct.pack(">H", len(payload) + 2) + payload + jpeg[2:]


class ColorManagementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def image(self, space=None, alpha=255):
        image = QImage(40, 20, QImage.Format.Format_RGBA8888)
        image.fill(QColor(100, 150, 200, alpha))
        if space is not None:
            image.setColorSpace(QColorSpace(space))
        return image

    def assert_rgb(self, image, expected, tolerance=2):
        actual = image.pixelColor(0, 0).getRgb()[:3]
        self.assertTrue(all(abs(a - b) <= tolerance for a, b in zip(actual, expected)), (actual, expected))
        self.assertEqual(image.colorSpace(), QColorSpace(QColorSpace.NamedColorSpace.SRgb))

    def test_wide_gamut_pixels_match_independent_matrix_gamma_reference(self):
        # D65 RGB->XYZ->sRGB matrix/transfer reference for source (100, 150, 200).
        for space, expected in ((QColorSpace.NamedColorSpace.AdobeRgb, (66, 151, 203)),
                                (QColorSpace.NamedColorSpace.DisplayP3, (83, 152, 205))):
            with self.subTest(space=space):
                original = self.image(space, alpha=123)
                result = to_srgb(original)
                self.assert_rgb(result, expected)
                self.assertEqual(result.pixelColor(0, 0).alpha(), 123)
                self.assertEqual(original.colorSpace(), QColorSpace(space))
                self.assertEqual(original.pixelColor(0, 0), QColor(100, 150, 200, 123))
                self.assertEqual(to_srgb(result).cacheKey(), result.cacheKey())

    def test_icc_jpeg_thumbnail_and_hero_share_srgb_colors_without_rewriting_source(self):
        for name, space, expected in (("adobe", QColorSpace.NamedColorSpace.AdobeRgb, (66, 151, 203)),
                                      ("p3", QColorSpace.NamedColorSpace.DisplayP3, (83, 152, 205))):
            path = self.root / f"{name}.jpg"
            path.write_bytes(jpeg_bytes(self.image(space)))
            before = hashlib.sha256(path.read_bytes()).digest()
            outputs = [decode(path, width) for width in (20, 420, 2200)]
            for output in outputs:
                self.assert_rgb(output, expected)
            self.assertEqual(extract_palette(outputs[0]), extract_palette(outputs[-1]))
            self.assertEqual(hashlib.sha256(path.read_bytes()).digest(), before)

    def test_exif_only_adobe_rgb_and_orientation_work_in_both_byte_orders(self):
        for endian in ("<", ">"):
            path = self.root / f"exif-{ord(endian)}.jpg"
            payload = b"Exif\0\0" + exif_tiff(endian=endian, orientation=6)
            path.write_bytes(with_segment(jpeg_bytes(self.image()), 0xE1, payload))
            output = decode(path, 420)
            self.assertEqual((output.width(), output.height()), (20, 40))
            self.assert_rgb(output, (66, 151, 203))

    def test_valid_embedded_icc_has_priority_over_conflicting_exif(self):
        path = self.root / "priority.jpg"
        source = jpeg_bytes(self.image(QColorSpace.NamedColorSpace.SRgb))
        path.write_bytes(with_segment(source, 0xE1, b"Exif\0\0" + exif_tiff()))
        with patch("picklight.color_management.file_color_space", side_effect=AssertionError("ICC already known")):
            output = decode(path, 420)
        self.assert_rgb(output, (100, 150, 200))

    def test_missing_unknown_and_damaged_metadata_keep_preview_readable(self):
        source = jpeg_bytes(self.image())
        payloads = [source,
                    with_segment(source, 0xE1, b"Exif\0\0" + exif_tiff(interop=None)),
                    with_segment(source, 0xE1, b"Exif\0\0II*\0\xff\xff\xff\xff"),
                    with_segment(source, 0xE2, b"ICC_PROFILE\0\x01\x01not-an-icc-profile")]
        for index, data in enumerate(payloads):
            path = self.root / f"fallback-{index}.jpg"
            path.write_bytes(data)
            self.assert_rgb(decode(path, 420), (100, 150, 200))
        self.assertIsNone(space_from_tags(65535))
        self.assertEqual(space_from_tags(2), QColorSpace(QColorSpace.NamedColorSpace.AdobeRgb))
        self.assertTrue(to_srgb(QImage()).isNull())
        image = self.image()
        to_srgb(image)
        self.assertFalse(image.colorSpace().isValid())

    def test_bounded_tiff_reader_handles_invalid_offsets_counts_and_missing_files(self):
        path = self.root / "metadata.ARW"
        path.write_bytes(exif_tiff())
        self.assertEqual(file_color_space(path), QColorSpace(QColorSpace.NamedColorSpace.AdobeRgb))
        for data in (b"", b"II*\0" + struct.pack("<I", 8) + struct.pack("<H", 65535),
                     b"II*\0" + struct.pack("<I", 0xFFFFFFFF),
                     b"\xff\xd8\xff\xe1\x00\x01", b"not an image"):
            path.write_bytes(data)
            self.assertIsNone(file_color_space(path))
        self.assertIsNone(file_color_space(self.root / "missing.jpg"))

    def test_raw_embedded_icc_is_normalized_and_orientation_is_retained(self):
        path = self.root / "embedded.ARW"
        path.write_bytes(exif_tiff(1, None))
        raw = MagicMock()
        raw.__enter__.return_value = raw
        raw.sizes.flip = 5
        raw.extract_thumb.return_value = SimpleNamespace(
            format=rawpy.ThumbFormat.JPEG,
            data=jpeg_bytes(self.image(QColorSpace.NamedColorSpace.AdobeRgb)))
        with patch("picklight.preview.rawpy.imread", return_value=raw), \
                patch("picklight.preview._run_exiftool") as external:
            output = decode(path, 420)
        external.assert_not_called()
        raw.postprocess.assert_not_called()
        self.assertEqual((output.width(), output.height()), (20, 40))
        self.assert_rgb(output, (66, 151, 203))

    def test_raw_decoded_srgb_is_not_reinterpreted_as_camera_adobe_rgb(self):
        path = self.root / "decoded.ARW"
        path.write_bytes(exif_tiff())
        raw = MagicMock()
        raw.__enter__.return_value = raw
        raw.extract_thumb.side_effect = ValueError("No thumbnail")
        raw.postprocess.return_value = np.full((8, 12, 3), [100, 150, 200], dtype=np.uint8)
        with patch("picklight.preview.rawpy.imread", return_value=raw):
            output = decode(path, 420)
        self.assertEqual(raw.postprocess.call_args.kwargs["output_color"], rawpy.ColorSpace.sRGB)
        self.assertEqual(raw.postprocess.call_args.kwargs["gamma"], (2.4, 12.92))
        self.assert_rgb(output, (100, 150, 200), tolerance=0)

    def test_exiftool_reuses_its_metadata_call_for_color_hints(self):
        path = self.root / "fallback.CR3"
        path.write_bytes(b"raw placeholder")
        metadata = b'[{"Orientation":6,"ColorSpace":65535,"InteropIndex":"R03"}]'
        with patch("picklight.preview.rawpy.imread", side_effect=rawpy.LibRawFileUnsupportedError()), \
                patch("picklight.preview._run_exiftool", side_effect=[jpeg_bytes(self.image()), metadata]) as tool:
            output = decode(path, 420)
        self.assertEqual(tool.call_count, 2)
        self.assertIn("-EXIF:ColorSpace", tool.call_args.args[0])
        self.assert_rgb(output, (66, 151, 203))

    def test_palette_normalizes_external_images_and_cached_preview_avoids_reconversion(self):
        image = self.image(QColorSpace.NamedColorSpace.DisplayP3)
        self.assertEqual(extract_palette(image), extract_palette(to_srgb(image)))
        loader = PreviewLoader()
        self.addCleanup(loader.shutdown)
        path = self.root / "cached.jpg"
        path.write_bytes(jpeg_bytes(image))
        received = []
        threads = []
        loader.ready.connect(lambda path, width, image:
                             (loader.remember(path, width, image), received.append(image)))

        def normalize(image):
            threads.append(get_ident())
            return to_srgb(image)

        with patch("picklight.preview.to_srgb", side_effect=normalize):
            loader.request(path, 420)
            deadline = time.monotonic() + 3
            while not received and time.monotonic() < deadline:
                QTest.qWait(5)
            self.assertTrue(received)
            self.assertEqual(len(threads), 1)
            self.assertNotEqual(threads[0], get_ident())
            self.assert_rgb(received[0], (83, 152, 205))
            with patch.object(loader.thumb_pool, "submit") as submit:
                loader.request(path, 420)
            submit.assert_not_called()
            self.assertEqual(len(threads), 1)
        self.assertEqual(received[0].cacheKey(), received[1].cacheKey())

    def test_failed_transform_falls_back_without_losing_the_preview(self):
        source = self.image(QColorSpace.NamedColorSpace.DisplayP3)
        with patch.object(QImage, "convertedToColorSpace", return_value=QImage()):
            result = to_srgb(source)
        self.assert_rgb(result, (100, 150, 200), tolerance=0)
