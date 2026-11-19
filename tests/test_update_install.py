"""Verified downloads, portable replacement and updater process handoff."""

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
from threading import Thread
import time
import unittest
from unittest.mock import patch, Mock
import zipfile

from PySide6.QtCore import QStandardPaths
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from picklight.update_download import UpdateDownload
from picklight.update_helper import apply_portable, extract_portable, install_package, run_job, verify_package
from picklight.update_install import installation_kind, launch_update
from picklight.updates import UpdateAsset, parse_release


class UpdateInstallTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def package(self, entries=None):
        path = self.root / "update.zip"
        with zipfile.ZipFile(path, "w") as archive:
            for name, value in (entries or {"PickLight/PickLight.exe": b"new",
                    "PickLight/PickLightUpdater.exe": b"helper",
                    "PickLight/_internal/runtime.dll": b"runtime"}).items():
                archive.writestr(name, value)
        return path

    def test_release_only_accepts_official_assets_with_checksums(self):
        asset = {"name": "PickLight-0.2.0-win-x64.zip", "digest": "sha256:" + "a" * 64,
                 "size": 100, "state": "uploaded",
                 "browser_download_url": "https://github.com/mio-1/PickLight/releases/download/v0.2.0/PickLight-0.2.0-win-x64.zip"}
        release = parse_release(json.dumps({"tag_name": "v0.2.0", "assets": [asset]}))
        self.assertEqual(release.assets[0].sha256, "a" * 64)
        for changes in ({"digest": None}, {"size": 0}, {"state": "new"},
                        {"browser_download_url": "http://example.com/file.zip"}):
            with self.subTest(changes=changes):
                result = parse_release(json.dumps({"tag_name": "v0.2.0", "assets": [dict(asset, **changes)]}))
                self.assertEqual(result.assets, ())

    def test_portable_job_updates_runtime_and_preserves_unmanaged_files(self):
        target = self.root / "程序目录 with spaces"
        target.mkdir()
        (target / "PickLight.exe").write_bytes(b"old")
        (target / "_internal").mkdir()
        (target / "_internal" / "obsolete.dll").write_bytes(b"old")
        (target / "my-photos").mkdir()
        (target / "my-photos" / "one.jpg").write_bytes(b"photo")
        package = self.package()
        job = self.root / "job.json"
        digest = hashlib.sha256(package.read_bytes()).hexdigest()
        job.write_text(json.dumps({"target": str(target), "package": str(package),
                                  "sha256": digest, "kind": "portable", "pid": 123}), encoding="utf-8")
        with patch("picklight.update_helper.wait_for_exit") as wait, \
                patch("picklight.update_helper.subprocess.Popen") as start:
            run_job(job)
        wait.assert_called_once()
        start.assert_called_once_with([str(target / "PickLight.exe")], cwd=target)
        self.assertEqual((target / "PickLight.exe").read_bytes(), b"new")
        self.assertFalse((target / "_internal" / "obsolete.dll").exists())
        self.assertEqual((target / "my-photos" / "one.jpg").read_bytes(), b"photo")
        self.assertTrue((self.root / "complete").exists())
        self.assertEqual(list(target.glob(".picklight-update-*")), [])

    def test_failed_replacement_restores_original_runtime_and_executable(self):
        staged, target, backup = (self.root / name for name in ("new", "app", "backup"))
        for folder in (staged, target):
            folder.mkdir()
            (folder / "PickLight.exe").write_bytes(folder.name.encode())
            (folder / "_internal").mkdir()
            (folder / "_internal" / "runtime.dll").write_bytes(folder.name.encode())
        rename = Path.rename

        def fail_runtime(path, destination):
            if path == staged / "_internal":
                raise PermissionError("runtime in use")
            return rename(path, destination)

        with patch.object(Path, "rename", fail_runtime), self.assertRaises(PermissionError):
            apply_portable(staged, target, backup)
        self.assertEqual((target / "PickLight.exe").read_bytes(), b"app")
        self.assertEqual((target / "_internal" / "runtime.dll").read_bytes(), b"app")
        self.assertEqual(list(backup.iterdir()), [])

    def test_failed_restart_restores_previous_version(self):
        target = self.root / "app"
        target.mkdir()
        (target / "PickLight.exe").write_bytes(b"previous")
        package = self.package()
        job = self.root / "job.json"
        job.write_text(json.dumps({"target": str(target), "package": str(package),
                                  "sha256": hashlib.sha256(package.read_bytes()).hexdigest(),
                                  "kind": "portable", "pid": 123}), encoding="utf-8")
        with patch("picklight.update_helper.wait_for_exit"), \
                patch("picklight.update_helper.subprocess.Popen", side_effect=[OSError("cannot start"), Mock()]) as start, \
                self.assertRaises(OSError):
            run_job(job)
        self.assertEqual(start.call_count, 2)
        self.assertEqual((target / "PickLight.exe").read_bytes(), b"previous")
        self.assertFalse((self.root / "complete").exists())
        self.assertEqual(list(target.glob(".picklight-update-*")), [])

    def test_invalid_zip_paths_are_rejected_before_extraction(self):
        destination = self.root / "extract"
        for name in ("../outside", "PickLight/../outside", "PickLight/_internal/../../outside",
                     "C:/outside", "PickLight/unknown.exe"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                extract_portable(self.package({name: b"invalid"}), destination)
            self.assertFalse(destination.exists())

    def test_incomplete_package_and_bad_digest_never_replace_files(self):
        package = self.package({"PickLight/PickLight.exe": b"new"})
        with self.assertRaises(ValueError):
            extract_portable(package, self.root / "extract")
        with self.assertRaises(ValueError):
            verify_package(package, "0" * 64)

    def test_installer_uses_original_directory_and_blocks_system_restart(self):
        package = self.root / "setup.exe"
        target = self.root / "应用 程序"
        with patch("picklight.update_helper.subprocess.run", return_value=Mock(returncode=0)) as run:
            install_package(package, target, self.root / "installer.log")
            args = run.call_args.args[0]
            self.assertIn(f"/DIR={target}", args)
            self.assertIn("/NORESTART", args)
            self.assertIn("/NORESTARTAPPLICATIONS", args)
            self.assertNotIn("shell", run.call_args.kwargs)
        with patch("picklight.update_helper.subprocess.run", return_value=Mock(returncode=1)), \
                self.assertRaises(RuntimeError):
            install_package(package, target, self.root / "installer.log")

    def test_launch_copies_helper_outside_app_and_passes_paths_as_arguments(self):
        target = self.root / "应用 程序"
        target.mkdir()
        exe = target / "PickLight.exe"
        exe.touch()
        (target / "PickLightUpdater.exe").write_bytes(b"helper")
        work = self.root / "下载 目录"
        work.mkdir()
        package = work / "update.zip"
        package.touch()
        asset = UpdateAsset(package.name, "", 1, "a" * 64, "portable")
        with patch("picklight.update_install.sys.frozen", True, create=True), \
                patch("picklight.update_install.sys.executable", str(exe)), \
                patch("picklight.update_install.subprocess.Popen") as popen:
            self.assertEqual(installation_kind(), "portable")
            launch_update(package, asset)
            self.assertEqual(popen.call_args.args[0], [str(work / "PickLightUpdater.exe"), str(work / "job.json")])
            self.assertEqual(popen.call_args.kwargs["env"]["PYINSTALLER_RESET_ENVIRONMENT"], "1")
            job = json.loads((work / "job.json").read_text(encoding="utf-8"))
            self.assertEqual(job["target"], str(target))
            (target / "unins000.exe").touch()
            self.assertEqual(installation_kind(), "installer")
            with self.assertRaises(ValueError):
                launch_update(package, asset)


class DownloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.content = b"update-content" * 10000
        content = cls.content

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(500 if self.path == "/error" else 200)
                self.end_headers()
                self.wfile.write(content)

            def log_message(self, *args):
                pass

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_streaming_success_corruption_truncation_and_http_failure(self):
        for route, digest, size, expected in (
                ("ok", hashlib.sha256(self.content).hexdigest(), len(self.content), True),
                ("ok", "0" * 64, len(self.content), False),
                ("ok", "0" * 64, len(self.content) + 1, False),
                ("ok", "0" * 64, len(self.content) - 1, False),
                ("error", "0" * 64, len(self.content), False)):
            with self.subTest(route=route, size=size, expected=expected), tempfile.TemporaryDirectory() as cache, \
                    patch.object(QStandardPaths, "writableLocation", return_value=cache):
                download = UpdateDownload(self.app)
                self.addCleanup(download.deleteLater)
                ready, errors, progress = [], [], []
                download.ready.connect(ready.append)
                download.failed.connect(errors.append)
                download.progress.connect(lambda done, total: progress.append((done, total)))
                asset = UpdateAsset("update.zip", f"http://127.0.0.1:{self.server.server_port}/{route}", size, digest, "portable")
                download.start(asset)
                deadline = time.monotonic() + 5
                while not ready and not errors and time.monotonic() < deadline:
                    QTest.qWait(10)
                if expected:
                    self.assertEqual(ready[0].read_bytes(), self.content)
                    self.assertEqual(progress[-1], (size, size))
                    self.assertEqual(errors, [])
                else:
                    self.assertTrue(errors)
                    self.assertEqual(ready, [])
                    self.assertEqual(list(Path(cache).rglob("*.part")), [])
                download.cancel()
                self.assertEqual(list(Path(cache).rglob("update.zip")), [])

    def test_cancel_aborts_request_and_removes_partial_file(self):
        with tempfile.TemporaryDirectory() as cache, \
                patch.object(QStandardPaths, "writableLocation", return_value=cache):
            download = UpdateDownload(self.app)
            self.addCleanup(download.deleteLater)
            errors = []
            download.failed.connect(errors.append)
            download.start(UpdateAsset("update.zip", f"http://127.0.0.1:{self.server.server_port}/ok",
                                       len(self.content), "0" * 64, "portable"))
            download.cancel()
            self.app.processEvents()
            self.assertEqual(errors, [])
            self.assertIsNone(download.reply)
            self.assertEqual(list(Path(cache).rglob("*.part")), [])
