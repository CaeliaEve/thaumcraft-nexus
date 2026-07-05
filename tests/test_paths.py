import tempfile
import unittest
from pathlib import Path

from thaum_nexus import paths


class PathsTests(unittest.TestCase):
    def test_source_mode_roots_point_at_repository(self):
        root = Path(__file__).resolve().parents[1]

        self.assertEqual(paths.source_root(), root)
        self.assertEqual(paths.app_root(), root)
        self.assertEqual(paths.resource_root(), root)
        self.assertEqual(paths.data_dir(), root / "data")
        self.assertEqual(paths.image_dir(), root / "image")

    def test_explicit_project_root_controls_all_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()

            self.assertEqual(paths.app_root(root), root)
            self.assertEqual(paths.resource_root(root), root)
            self.assertEqual(paths.runtime_root(root), root / "runtime")
            self.assertEqual(paths.resource_path("image/icon.png", root), root / "image" / "icon.png")


if __name__ == "__main__":
    unittest.main()
