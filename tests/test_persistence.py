import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from thaum_nexus.persistence import atomic_write_json, read_settings_json


class PersistenceTests(unittest.TestCase):
    def test_missing_settings_use_defaults_without_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(read_settings_json(Path(tmp) / "absent.json"), ({}, None))

    def test_round_trip_unicode_and_parent_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "settings.json"
            atomic_write_json(path, {"label": "研究", "speed": 0})
            self.assertEqual(read_settings_json(path), ({"label": "研究", "speed": 0}, None))
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_invalid_settings_are_preserved_with_warning(self):
        for original in (b'{"unfinished":', b'[1, 2]', b'null', b'\xff'):
            with self.subTest(original=original), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "settings.json"
                path.write_bytes(original)
                payload, warning = read_settings_json(path)
                self.assertEqual(payload, {})
                self.assertEqual(warning.code, "settings_invalid")
                self.assertIn(str(path), warning.details)
                self.assertEqual(path.read_bytes(), original)

    def test_read_permissions_have_distinct_warning(self):
        with patch.object(Path, "read_text", side_effect=PermissionError("denied")):
            payload, warning = read_settings_json(Path("settings.json"))
        self.assertEqual(payload, {})
        self.assertEqual(warning.code, "settings_permission")
        self.assertIn("denied", warning.details)

    def test_other_read_errors_have_distinct_warning(self):
        with patch.object(Path, "read_text", side_effect=OSError("device unavailable")):
            _, warning = read_settings_json(Path("settings.json"))
        self.assertEqual(warning.code, "settings_read_error")
        self.assertIn("device unavailable", warning.details)

    def test_replace_failure_preserves_old_file_and_cleans_temporary_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text('{"old": true}', encoding="utf-8")
            with patch("thaum_nexus.persistence.os.replace", side_effect=PermissionError("locked")):
                with self.assertRaises(PermissionError):
                    atomic_write_json(path, {"new": True})
            self.assertEqual(json.loads(path.read_text()), {"old": True})
            self.assertEqual(list(Path(tmp).iterdir()), [path])

    def test_flush_failure_preserves_old_file_and_cleans_temporary_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text('{"old": true}', encoding="utf-8")
            with patch("thaum_nexus.persistence.os.fsync", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    atomic_write_json(path, {"new": True})
            self.assertEqual(json.loads(path.read_text()), {"old": True})
            self.assertEqual(list(Path(tmp).iterdir()), [path])

    def test_serialization_failure_preserves_old_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text('{"old": true}', encoding="utf-8")
            with self.assertRaises(TypeError):
                atomic_write_json(path, {"bad": object()})
            self.assertEqual(json.loads(path.read_text()), {"old": True})
            self.assertEqual(list(Path(tmp).iterdir()), [path])
