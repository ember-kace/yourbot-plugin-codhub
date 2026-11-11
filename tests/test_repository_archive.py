"""Archive downloads preserve the plugin while omitting only hosted bulk images."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import check_repository_archive as policy


class RepositoryArchiveTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="cod-hub-archive-test-")
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "source.zip"
        self.files = {"plugin/manifest.json": b'{"name":"Synthetic plugin"}',
                      "plugin/cod_hub/images/native/synthetic.webp": b"synthetic bundled bytes",
                      "metadata/proof.json": b'{"synthetic":true}'}
        self.tracked = {name: policy.blob_id(body) for name, body in self.files.items()}
        self.tracked[policy.HOSTED_ARTWORK + "synthetic.webp"] = policy.blob_id(b"hosted artwork")

    def write(self, files=None):
        with zipfile.ZipFile(self.path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, body in (self.files if files is None else files).items():
                archive.writestr(name, body)

    def test_only_hosted_artwork_is_omitted_and_bundled_images_stay_identical(self):
        self.write()
        report = policy.inspect_archive(self.path, self.tracked)
        self.assertTrue(report["ready"])
        self.assertEqual(report["plugin_files_verified"], 2)
        self.assertEqual(report["hosted_artwork_files_omitted"], 1)

    def test_missing_plugin_file_or_extra_payload_cannot_pass(self):
        for change in ("missing", "extra"):
            files = dict(self.files)
            if change == "missing":
                files.pop("plugin/manifest.json")
            else:
                files["unreviewed.txt"] = b"extra"
            self.write(files)
            with self.subTest(change=change), self.assertRaises(ValueError):
                policy.inspect_archive(self.path, self.tracked)

    def test_same_path_with_changed_bytes_cannot_pass(self):
        files = dict(self.files)
        files["plugin/cod_hub/images/native/synthetic.webp"] = b"changed pixels"
        self.write(files)
        with self.assertRaisesRegex(ValueError, "committed bytes"):
            policy.inspect_archive(self.path, self.tracked)

    def test_compressed_and_expanded_budgets_are_both_enforced(self):
        files = {"plugin/data.json": b"0" * 10000}
        tracked = {name: policy.blob_id(body) for name, body in files.items()}
        self.write(files)
        with patch.object(policy, "LIMIT_BYTES", 1000), self.assertRaisesRegex(ValueError, "Expanded"):
            policy.inspect_archive(self.path, tracked)
        with patch.object(policy, "LIMIT_BYTES", 50), self.assertRaisesRegex(ValueError, "Repository ZIP"):
            policy.inspect_archive(self.path, tracked)
