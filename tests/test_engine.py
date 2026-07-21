import unittest
from pathlib import Path

from archivekey.engine import RecoveryEngine, RecoveryError


class EngineTests(unittest.TestCase):
    def test_normalizes_windows_rar5_hash(self):
        raw = r"C:\Users\Person\Desktop\data.rar:$rar5$16$abc$15$def$8$123"
        normalized, format_name = RecoveryEngine._normalize_hash(raw, Path("data.rar"))
        self.assertEqual(normalized, "data.rar:$rar5$16$abc$15$def$8$123")
        self.assertEqual(format_name, "RAR5")

    def test_detects_pkzip2_format(self):
        normalized, format_name = RecoveryEngine._normalize_hash(
            "sample.zip:$pkzip2$3*example", Path("sample.zip")
        )
        self.assertTrue(normalized.startswith("sample.zip:$pkzip2$"))
        self.assertEqual(format_name, "PKZIP")

    def test_rejects_unknown_hash(self):
        with self.assertRaises(RecoveryError):
            RecoveryEngine._normalize_hash("archive:unknown", Path("archive.rar"))
