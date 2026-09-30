from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import release_tools
from thaum_nexus.version import get_build_info, get_version_label


class ReleaseToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "ThaumcraftNexus"
        for name in ("ThaumcraftNexus.exe", "LICENSE", "THIRD_PARTY_NOTICES.md", "README_CN.txt",
                     "_internal/data/aspects.json", "_internal/data/combinations.json",
                     "_internal/data/adjacency.json", "_internal/data/manifest.json",
                     "_internal/image/icons8-github-50.png", "_internal/image/thaumonomicon_bg_clean.png",
                     "_internal/java-agent/thaum-nexus-agent.jar"):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fixture")
        self.metadata = {"version": "1.2.3", "commit": "a" * 40, "dirty": False}
        (self.root / "_internal/build-info.json").write_text(json.dumps(self.metadata))

    def test_package_creates_zip_with_single_root_and_verifiable_checksum(self):
        archive = release_tools.package_release(self.root, self.root.parent / "release.zip")
        with zipfile.ZipFile(archive) as zipped:
            self.assertIn("ThaumcraftNexus/_internal/build-info.json", zipped.namelist())
            self.assertTrue(all(n.startswith("ThaumcraftNexus/") for n in zipped.namelist()))
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        self.assertEqual(archive.with_suffix(".zip.sha256").read_text(), f"{digest}  release.zip\n")

    def test_missing_resource_rejects_package(self):
        (self.root / "_internal/data/aspects.json").unlink()
        with self.assertRaisesRegex(ValueError, "aspects.json"):
            release_tools.verify_package(self.root)

    def test_background_and_instructions_are_required(self):
        for name in ("README_CN.txt", "_internal/image/thaumonomicon_bg_clean.png"):
            path = self.root / name
            path.unlink()
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "Missing required file"):
                release_tools.verify_package(self.root)
            path.write_bytes(b"fixture")

    def test_dirty_metadata_ignores_only_generated_dist_and_omx(self):
        repo = self.root.parent / "repo"
        repo.mkdir()
        def git(*args):
            subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
        git("init")
        git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "--allow-empty", "-m", "fixture")
        for folder in ("dist", ".omx"):
            (repo / folder).mkdir()
            (repo / folder / "local.txt").write_text("generated")
        self.assertFalse(release_tools.build_metadata(repo)["dirty"])
        (repo / "source.py").write_text("changed source")
        self.assertTrue(release_tools.build_metadata(repo)["dirty"])

    def test_unwanted_runtime_and_scientific_libraries_rejected(self):
        for name in ("runtime/settings.json", "_internal/numpy/lib.dll", "_internal/cv2/cv2.pyd"):
            with self.subTest(name=name):
                path = self.root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"unwanted")
                with self.assertRaisesRegex(ValueError, "Unwanted"):
                    release_tools.verify_package(self.root)
                shutil.rmtree(self.root / name.split("/")[0] if name.startswith("runtime") else path.parent)

    def test_file_over_size_limit_rejected(self):
        with self.assertRaisesRegex(ValueError, "size limit"):
            release_tools.verify_package(self.root, max_file_bytes=3)

    def test_metadata_loads_for_gui(self):
        info = get_build_info(self.root / "_internal")
        self.assertEqual(info, self.metadata)
        self.assertEqual(get_version_label(self.root / "_internal"), "1.2.3 (aaaaaaaaaaaa)")

    def test_metadata_validates_tag_and_records_commit(self):
        info = release_tools.build_metadata(Path(__file__).resolve().parents[1], "v2.4.0")
        self.assertEqual(info["version"], "2.4.0")
        self.assertRegex(info["commit"], r"^[0-9a-f]{40}$")
        with self.assertRaises(ValueError):
            release_tools.build_metadata(self.root, "../../bad")

    def test_malformed_metadata_has_safe_source_fallback(self):
        (self.root / "build-info.json").write_text("{broken")
        self.assertIn("version", get_build_info(self.root))
        self.assertIn("unknown", get_version_label(self.root))

    def test_build_environment_rejects_missing_wrong_and_extra_packages(self):
        requirements = self.root / "requirements.txt"
        requirements.write_text("Pillow==12.3.0\n")
        release_tools.validate_environment(requirements, {"pillow": "12.3.0", "pip": "26.0"})
        for installed in ({}, {"pillow": "10.0"}, {"pillow": "12.3.0", "numpy": "2.0"}):
            with self.subTest(installed=installed), self.assertRaises(ValueError):
                release_tools.validate_environment(requirements, installed)


@unittest.skipUnless(shutil.which("powershell"), "Windows PowerShell required")
class JavaBuildFailureTests(unittest.TestCase):
    def test_child_failure_rejects_existing_jar(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            child = folder / "fail.ps1"
            child.write_text("param([string]$OutputDir)\nexit 7\n")
            (folder / "thaum-nexus-agent.jar").write_bytes(b"stale")
            helper = Path(__file__).resolve().parents[1] / "scripts/build_helpers.ps1"
            quote = lambda path: "'" + str(path).replace("'", "''") + "'"
            result = subprocess.run(["powershell", "-NoProfile", "-Command",
                f"$ErrorActionPreference='Stop'; . {quote(helper)}; Invoke-JavaAgentBuild {quote(child)} {quote(folder)}"],
                capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Java Agent build failed", result.stderr)


class PortableSelfTestTests(unittest.TestCase):
    def test_self_test_decodes_background_and_renders_real_tk_view(self):
        from tools.thaum_nexus_gui import self_test
        from PIL import UnidentifiedImageError
        source = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(source / "data", root / "data")
            (root / "image").mkdir()
            shutil.copy(source / "image/icons8-github-50.png", root / "image/icons8-github-50.png")
            (root / "java-agent").mkdir()
            (root / "java-agent/thaum-nexus-agent.jar").write_bytes(b"fixture")
            background = root / "image/thaumonomicon_bg_clean.png"
            background.write_bytes(b"not a PNG")
            with patch("thaum_nexus.paths.resource_root", return_value=root):
                with self.assertRaises(UnidentifiedImageError):
                    self_test()
                shutil.copy(source / "image/thaumonomicon_bg_clean.png", background)
                self.assertEqual(self_test(), 0)
            self.assertFalse((root / "runtime").exists(), "Smoke test must not create game/settings output")


if __name__ == "__main__":
    unittest.main()
