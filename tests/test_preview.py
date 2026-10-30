"""RAW preview orientation matches the camera metadata without double rotation."""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import rawpy
from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QColor, QImage

from picklight.preview import _exiftool_raw_image, _orient_raw_thumbnail, _raw_image
from picklight.metadata import MetadataError


class RawPreviewTests(unittest.TestCase):
    @staticmethod
    def jpeg():
        image = QImage(8, 4, QImage.Format.Format_RGB888)
        image.fill(QColor('red'))
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, 'JPEG')
        return bytes(data)

    def test_unsupported_camera_uses_embedded_preview_without_raw_processing(self):
        with patch('picklight.preview.rawpy.imread', side_effect=rawpy.LibRawFileUnsupportedError()), \
                patch('picklight.preview._run_exiftool', side_effect=[self.jpeg(), b'[{"Orientation":8}]']) as tool:
            result = _raw_image(Path('new-camera.CR3'))
        self.assertEqual((result.width(), result.height()), (4, 8))
        self.assertIn('-JpgFromRaw', tool.call_args_list[0].args[0])
        self.assertNotIn('-overwrite_original', str(tool.call_args_list))

    def test_missing_or_invalid_embedded_preview_tries_other_tags(self):
        with patch('picklight.preview._run_exiftool',
                   side_effect=[b'not a jpeg', self.jpeg(), b'[{"Orientation":6}]']) as tool:
            result = _exiftool_raw_image(Path('camera.NEF'))
        self.assertEqual((result.width(), result.height()), (4, 8))
        self.assertIn('-PreviewImage', tool.call_args_list[1].args[0])

    def test_last_resort_thumbnail_and_missing_orientation(self):
        with patch('picklight.preview._run_exiftool',
                   side_effect=[b'', b'', self.jpeg(), b'[]']):
            result = _exiftool_raw_image(Path('legacy.CRW'))
        self.assertEqual((result.width(), result.height()), (8, 4))

    def test_unsupported_file_has_actionable_error_when_fallback_unavailable(self):
        with patch('picklight.preview.rawpy.imread', side_effect=rawpy.LibRawFileUnsupportedError()), \
                patch('picklight.preview._run_exiftool', side_effect=MetadataError('Unavailable')):
            with self.assertRaisesRegex(ValueError, '暂不支持此相机或 RAW 压缩模式'):
                _raw_image(Path('unsupported.RAF'))

    def test_corrupt_raw_and_absent_previews_fail_cleanly(self):
        with patch('picklight.preview.rawpy.imread', side_effect=rawpy.LibRawDataError()), \
                patch('picklight.preview._run_exiftool', return_value=b''):
            with self.assertRaisesRegex(ValueError, '文件可能不完整、已损坏'):
                _raw_image(Path('broken.RW2'))

    def test_camera_rotations_preserve_direction(self):
        image = QImage(8, 4, QImage.Format.Format_RGB888)
        image.fill(QColor('black'))
        image.setPixelColor(0, 0, QColor('red'))
        for flip, size, corner in ((0, (8, 4), (0, 0)), (3, (8, 4), (7, 3)),
                                   (5, (4, 8), (0, 7)), (6, (4, 8), (3, 0))):
            with self.subTest(flip=flip):
                result = _orient_raw_thumbnail(image, flip)
                self.assertEqual((result.width(), result.height()), size)
                self.assertEqual(result.pixelColor(*corner), QColor('red'))

    def test_both_embedded_formats_use_raw_orientation(self):
        image = QImage(8, 4, QImage.Format.Format_RGB888)
        image.fill(QColor('red'))
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        self.assertTrue(image.save(buffer, 'JPEG'))
        thumbnails = (
            SimpleNamespace(format=rawpy.ThumbFormat.JPEG, data=bytes(data)),
            SimpleNamespace(format=rawpy.ThumbFormat.BITMAP,
                            data=np.zeros((4, 8, 3), dtype=np.uint8)),
        )
        for thumbnail in thumbnails:
            with self.subTest(format=thumbnail.format):
                raw = MagicMock()
                raw.sizes.flip = 5
                raw.extract_thumb.return_value = thumbnail
                raw.__enter__.return_value = raw
                with patch('picklight.preview.rawpy.imread', return_value=raw):
                    with patch('picklight.preview._run_exiftool') as tool:
                        result = _raw_image(Path('portrait.ARW'))
                        tool.assert_not_called()
                self.assertEqual((result.width(), result.height()), (4, 8))
                raw.postprocess.assert_not_called()

    def test_postprocess_fallback_already_has_camera_rotation(self):
        raw = MagicMock()
        raw.sizes.flip = 5
        raw.extract_thumb.side_effect = ValueError('No embedded preview')
        raw.postprocess.return_value = np.zeros((8, 4, 3), dtype=np.uint8)
        raw.__enter__.return_value = raw
        with patch('picklight.preview.rawpy.imread', return_value=raw):
            result = _raw_image(Path('portrait.ARW'))
        self.assertEqual((result.width(), result.height()), (4, 8))
