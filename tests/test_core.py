"""Photo pairing, metadata writes and persistent library state."""

import tempfile
import unittest
import json
from pathlib import Path

from PySide6.QtGui import QImage, QImageReader

from picklight.library import scan_pairs
from picklight.metadata import (
    MetadataError, read_dng_ratings, read_pair_rating, read_raw_rating, read_photo_details_many,
    _run_exiftool, write_pair_rating,
    write_jpg_rating, write_raw_rating,
)
from picklight.session import SessionStore


# A minimal JPEG stream sufficient for exercising metadata segment handling.
JPEG = b"\xff\xd8\xff\xe0\x00\x04JF\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00PIXELS\xff\xd9"
EXISTING_XMP = (
    b'<x:xmpmeta xmlns:x="adobe:ns:meta/" '
    b'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
    b'xmlns:xmp="http://ns.adobe.com/xap/1.0/" '
    b'xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/">'
    b'<rdf:RDF><rdf:Description xmp:Rating="2" crs:Exposure2012="+0.65" />'
    b'</rdf:RDF></x:xmpmeta>'
)


class MetadataTests(unittest.TestCase):
    def test_camera_families_pair_and_rate_without_modifying_native_raw(self):
        extensions = ('CRW', 'CR2', 'CR3', 'NEF', 'NRW', 'ARW', 'RAF', 'RW2',
                      'ORF', 'ORI', 'PEF', 'PTX', 'SRW', '3FR', 'FFF', 'IIQ',
                      'MOS', 'DCR', 'KDC', 'BAY', 'CAP', 'PXN', 'RWZ', 'X3F')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, extension in enumerate(extensions):
                raw = root / f'camera-{index}.{extension}'
                raw.write_bytes(b'unchanged raw data')
                (root / f'camera-{index}.JPG').write_bytes(JPEG)
            pairs = scan_pairs(root)
            self.assertEqual(len(pairs), len(extensions))
            for pair in pairs:
                with self.subTest(format=pair.raw.suffix if pair.raw else pair.key):
                    self.assertIsNotNone(pair.raw)
                    self.assertIsNotNone(pair.jpg)
                    write_pair_rating(pair, 4)
                    self.assertEqual(read_raw_rating(pair.raw), 4)
                    self.assertEqual(pair.raw.read_bytes(), b'unchanged raw data')

    def test_bulk_photo_details_are_keyed_by_source_path(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / name for name in ("a.jpg", "b.jpg")]
            for path in paths:
                image = QImage(32, 24, QImage.Format.Format_RGB32)
                image.fill("#526e7d")
                self.assertTrue(image.save(str(path), "JPEG"))
            _run_exiftool(["-overwrite_original", "-Model=Alpha", str(paths[0])])
            _run_exiftool(["-overwrite_original", "-Model=Beta", str(paths[1])])
            details = read_photo_details_many(paths)
            self.assertEqual(details[str(paths[0])]["Model"], "Alpha")
            self.assertEqual(details[str(paths[1])]["Model"], "Beta")

    def test_pairing_and_rating_preserves_raw_and_existing_xmp_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            jpg_dir, raw_dir = root / "jpg", root / "raw"
            jpg_dir.mkdir()
            raw_dir.mkdir()
            jpg = jpg_dir / "DSC_001.JPG"
            raw = raw_dir / "dsc_001.ARW"
            jpg.write_bytes(JPEG)
            raw.write_bytes(b"RAW PIXEL DATA")
            sidecar = raw.with_suffix(".xmp")
            sidecar.write_bytes(EXISTING_XMP)
            pairs = scan_pairs(root)
            self.assertEqual(len(pairs), 1)
            pair = pairs[0]
            self.assertEqual(read_pair_rating(pair), 2)
            write_pair_rating(pair, 5)
            self.assertEqual(read_pair_rating(pair), 5)
            self.assertEqual(raw.read_bytes(), b"RAW PIXEL DATA")
            self.assertIn(b"PIXELS\xff\xd9", jpg.read_bytes())
            self.assertIn(b"Exposure2012", sidecar.read_bytes())
            self.assertIn(b"+0.65", sidecar.read_bytes())

    def test_jpg_rating_overrides_raw_including_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            jpg = root / "A.jpg"
            raw = root / "A.NEF"
            jpg.write_bytes(JPEG)
            raw.write_bytes(b"raw")
            raw.with_suffix(".xmp").write_bytes(EXISTING_XMP)
            pair = scan_pairs(root)[0]
            self.assertEqual(read_pair_rating(pair), 2)
            write_jpg_rating(jpg, 0)
            self.assertEqual(read_pair_rating(pair), 0)

    def test_real_jpeg_remains_decodable_after_rating_update(self):
        with tempfile.TemporaryDirectory() as directory:
            jpg = Path(directory) / "photo.jpg"
            image = QImage(120, 80, QImage.Format.Format_RGB32)
            image.fill("#7495aa")
            self.assertTrue(image.save(str(jpg), "JPEG"))
            before = QImageReader(str(jpg)).read()
            write_jpg_rating(jpg, 4)
            after = QImageReader(str(jpg)).read()
            self.assertFalse(after.isNull())
            self.assertEqual(after, before)

    def test_dng_rating_is_embedded_with_unicode_filename(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "测试.dng"
            image = QImage(32, 24, QImage.Format.Format_RGB32)
            image.fill("#7495aa")
            self.assertTrue(image.save(str(path), "TIFF"))
            try:
                write_raw_rating(path, 3)
            except MetadataError as exc:
                if "需要 ExifTool" in str(exc):
                    self.skipTest(str(exc))
                raise
            self.assertEqual(read_raw_rating(path), 3)
            self.assertFalse(path.with_suffix(".xmp").exists())
            self.assertEqual(read_dng_ratings([path, path]), [3, 3])

    def test_unpaired_photos_are_visible(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "one.JPG").write_bytes(JPEG)
            (root / "two.CR3").write_bytes(b"raw")
            pairs = scan_pairs(root)
            self.assertEqual([p.pairing_label for p in pairs], ["仅 JPG", "仅 RAW"])

    def test_ambiguous_duplicate_stem_is_kept_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "same.ARW").write_bytes(b"a")
            (root / "same.DNG").write_bytes(b"b")
            (root / "same.JPG").write_bytes(JPEG)
            pairs = scan_pairs(root)
            self.assertEqual(len(pairs), 3)
            self.assertTrue(all(pair.conflict for pair in pairs))
            self.assertTrue(all(not (pair.jpg and pair.raw) for pair in pairs))

    def test_recursive_pairing_uses_relative_folder_context(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for day in ("day1", "day2"):
                (root / "JPG" / day).mkdir(parents=True)
                (root / "RAW" / day).mkdir(parents=True)
                (root / "JPG" / day / "DSC_001.JPG").write_bytes(JPEG)
                (root / "RAW" / day / "DSC_001.NEF").write_bytes(b"raw")
            pairs = scan_pairs(root)
            self.assertEqual(len(pairs), 2)
            self.assertEqual({pair.key for pair in pairs}, {"day1/dsc_001", "day2/dsc_001"})
            self.assertTrue(all(pair.jpg and pair.raw for pair in pairs))

    def test_session_persists_review_state(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / "settings.json"
            store = SessionStore(settings)
            store.state_for("test")["marked"] = ["a", "b"]
            store.state_for("test")["last_key"] = "b"
            store.save()
            self.assertEqual(SessionStore(settings).state_for("test")["last_key"], "b")

    def test_legacy_folder_pair_restores_as_one_project(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            jpg, raw = root / "JPG", root / "RAW"
            jpg.mkdir()
            raw.mkdir()
            store = SessionStore(root / "settings.json")
            store.data["jpg_folder"] = str(jpg)
            store.data["raw_folder"] = str(raw)
            old_key = f"{jpg.resolve().as_posix().casefold()}|{raw.resolve().as_posix().casefold()}"
            store.state_for(old_key)["last_key"] = "dsc_001"
            self.assertEqual(store.recent_project(), str(root))
            store.migrate_legacy_session(root)
            self.assertEqual(store.state_for(store.session_key(root))["last_key"], "dsc_001")

    def test_project_catalog_preserves_names_and_existing_review_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, second = root / "first", root / "second"
            first.mkdir()
            second.mkdir()
            settings = root / "settings.json"
            settings.write_text(json.dumps({
                "project_folder": str(first),
                "sessions": {SessionStore.session_key(first): {"marked": ["photo"]}},
            }), encoding="utf-8")
            store = SessionStore(settings)
            old = store.projects()[0]
            self.assertEqual(old["folder"], str(first))
            self.assertEqual(store.state_for(store.session_key(first))["marked"], ["photo"])
            new = store.add_project(second)
            store.activate_project(new["id"])
            store.rename_project(old["id"], "春季拍摄")
            reloaded = SessionStore(settings)
            self.assertEqual(len(reloaded.projects()), 2)
            self.assertEqual(reloaded.recent_project(), str(second))
            self.assertEqual(reloaded.project_by_id(old["id"])["name"], "春季拍摄")
            self.assertEqual(reloaded.project_by_id(old["id"])["folder"], str(first))
            self.assertEqual(reloaded.state_for(reloaded.session_key(first))["marked"], ["photo"])
            reloaded.remove_project(old["id"])
            self.assertTrue(first.is_dir())

    def test_folder_delete_and_undo_preserve_source_and_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            photo = source / "photo.JPG"
            photo.write_bytes(JPEG)
            settings = root / "settings.json"
            store = SessionStore(settings)
            parent = store.add_folder("Parent")
            folder = store.add_project(source, parent["id"])
            child = store.add_folder("Child", folder["id"])
            store.rename_project(folder["id"], "Photos")
            store.set_folder_appearance(folder["id"], icon="camera", color="#00aaff")
            deletion = store.delete_folder_undoable(folder["id"])
            self.assertIsNone(store.project_by_id(folder["id"]))
            self.assertIsNone(store.project_by_id(child["id"]))
            self.assertEqual(photo.read_bytes(), JPEG)
            restored = SessionStore(settings)
            restored.undo_folder_deletion(deletion)
            revived = restored.project_by_id(folder["id"])
            self.assertEqual(revived["parent_id"], parent["id"])
            self.assertEqual(revived["name"], "Photos")
            self.assertEqual(revived["icon"], "camera")
            self.assertEqual(revived["color"], "#00aaff")
            self.assertIsNotNone(restored.project_by_id(child["id"]))
            self.assertEqual(photo.read_bytes(), JPEG)

    def test_folder_appearance_persists_without_changing_bound_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            photo = source / "photo.JPG"
            photo.write_bytes(JPEG)
            settings = root / "settings.json"
            store = SessionStore(settings)
            project = store.add_project(source)
            store.set_folder_appearance(project["id"], icon="camera", color="#FF453A")
            restored = SessionStore(settings)
            self.assertEqual(restored.project_by_id(project["id"])["icon"], "camera")
            self.assertEqual(restored.project_by_id(project["id"])["color"], "#ff453a")
            with self.assertRaises(ValueError):
                store.set_folder_appearance(project["id"], icon="../outside", color="")
            self.assertEqual(project["color"], "#ff453a")
            with self.assertRaises(ValueError):
                store.set_folder_appearance(project["id"], color="invalid")
            store.set_folder_appearance(project["id"], icon="")
            self.assertEqual(project["icon"], "")
            self.assertEqual(project["color"], "#ff453a")
            store.set_folder_appearance(project["id"], color="")
            self.assertEqual(SessionStore(settings).project_by_id(project["id"])["color"], "")
            self.assertEqual(project["folder"], str(source))
            self.assertEqual(photo.read_bytes(), JPEG)

    def test_virtual_folders_nest_without_changing_source_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "camera_import"
            source.mkdir()
            (source / "photo.JPG").write_bytes(JPEG)
            store = SessionStore(root / "settings.json")
            parent_id = None
            folders = []
            for depth in range(16):
                folder = store.add_folder(f"第 {depth} 层", parent_id)
                folders.append(folder)
                parent_id = folder["id"]
            imported = store.add_project(source, parent_id)
            self.assertEqual(imported["name"], source.name)
            store.rename_project(imported["id"], "已选照片")
            self.assertTrue(source.is_dir())
            self.assertFalse((root / "已选照片").exists())
            self.assertEqual(imported["folder"], str(source))
            with self.assertRaises(ValueError):
                store.move_project(folders[0]["id"], imported["id"])
            reloaded = SessionStore(root / "settings.json")
            self.assertEqual(reloaded.project_by_id(imported["id"])["parent_id"], folders[-1]["id"])
            reloaded.remove_project(folders[-1]["id"])
            self.assertEqual(reloaded.project_by_id(imported["id"])["parent_id"], folders[-2]["id"])
            reloaded.add_project(source, folders[0]["id"])
            self.assertEqual(reloaded.project_by_id(imported["id"])["parent_id"], folders[0]["id"])
            tree = [(folders[0]["id"], None), (imported["id"], folders[0]["id"])]
            tree.extend((folder["id"], folders[index - 1]["id"])
                        for index, folder in enumerate(folders[1:-1], 1))
            reloaded.reorder_projects(tree)
            restored = SessionStore(root / "settings.json")
            self.assertEqual(restored.project_by_id(imported["id"])["parent_id"], folders[0]["id"])
            self.assertEqual([project["id"] for project in restored.projects()],
                             [project_id for project_id, _ in tree])
            self.assertTrue((source / "photo.JPG").is_file())


if __name__ == "__main__":
    unittest.main()
