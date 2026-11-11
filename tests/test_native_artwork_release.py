"""Native render publication checks operate on immutable captured artifact bytes."""
import hashlib
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from tools import native_artwork_release as gate


class NativeArtworkReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = {name: (gate.ROOT / "plugin" / name).read_bytes()
                      for name in (gate.MANIFEST, gate.CATALOG)}
        for path in (gate.ROOT / "plugin" / gate.IMAGE_ROOT).glob("*.webp"):
            cls.source[gate.IMAGE_ROOT + path.name] = path.read_bytes()

    def fixture(self):
        captured = dict(self.source)
        manifest = json.loads(captured[gate.MANIFEST])
        return captured, manifest

    def check(self, captured, manifest=None):
        if manifest is not None:
            captured[gate.MANIFEST] = json.dumps(manifest).encode("utf8")
        return gate.evaluate_captured(captured)

    def replace_base_image(self, captured, manifest, replacement):
        asset = "320bd7829fa4bdee"
        record = manifest["base_images"][asset]
        del captured[gate.IMAGE_ROOT + record["filename"]]
        checksum = hashlib.sha256(replacement).hexdigest()
        record.update(sha256=checksum, filename=checksum + ".webp")
        captured[gate.IMAGE_ROOT + record["filename"]] = replacement
        pins = dict(gate.REVIEWED_BASE_IMAGES, **{asset: checksum})
        return pins

    def test_reviewed_weapon_image_set_and_hosted_copies_are_complete(self):
        report = self.check(dict(self.source))
        self.assertTrue(report["ready"], report["issues"])
        self.assertEqual((report["base_count"], report["build_count"], report["image_count"]), (35, 3, 38))
        self.assertEqual(report["image_bytes"], 3_694_872)
        report = gate.evaluate_release()
        self.assertTrue(report["ready"], report["issues"])
        self.assertEqual(report["hosted_copies_checked"], 38)

    def test_missing_corrupt_and_unreferenced_captured_images_block_release(self):
        image_path = next(path for path in self.source if path.startswith(gate.IMAGE_ROOT))
        for change, expected in (("missing", "missing or oversized native image"),
                                 ("corrupt", "native image hash mismatch"),
                                 ("extra", "unreferenced bundled native image")):
            with self.subTest(change=change):
                captured = dict(self.source)
                if change == "missing":
                    del captured[image_path]
                elif change == "corrupt":
                    captured[image_path] = b"corrupt"
                else:
                    captured[gate.IMAGE_ROOT + "unreviewed.webp"] = b"unreviewed"
                report = self.check(captured)
                self.assertFalse(report["ready"])
                self.assertIn(expected, [item["issue"] for item in report["issues"]])

    def test_wrong_dimensions_and_template_paths_are_rejected(self):
        for field, value, expected in (("width", 512, "native image format, dimensions or channels mismatch"),
                                       ("height", 2048, "invalid native image format declaration"),
                                       ("filename", "../template.webp", "invalid native artwork identity or content filename")):
            with self.subTest(field=field):
                captured, manifest = self.fixture()
                manifest["base_images"]["320bd7829fa4bdee"][field] = value
                report = self.check(captured, manifest)
                self.assertFalse(report["ready"])
                self.assertIn(expected, [item["issue"] for item in report["issues"]])

    def test_full_parity_unknown_fields_and_duplicate_json_keys_fail_closed(self):
        for change in ("full_parity", "extra_field", "duplicate_key", "incomplete"):
            with self.subTest(change=change):
                captured, manifest = self.fixture()
                if change == "full_parity":
                    manifest["full_game_shader_camo_parity"] = True
                elif change == "extra_field":
                    manifest["template_path"] = "private-input"
                elif change == "incomplete":
                    manifest["base_images"].pop("320bd7829fa4bdee")
                else:
                    captured[gate.MANIFEST] = b'{"format_version":1,"format_version":1}'
                    manifest = None
                report = self.check(captured, manifest)
                self.assertFalse(report["ready"])

    def test_valid_image_cannot_be_reassigned_to_a_different_build_or_weapon(self):
        for collection in ("base_images", "build_images"):
            with self.subTest(collection=collection):
                captured, manifest = self.fixture()
                first, second = list(manifest[collection].values())[:2]
                first["sha256"], first["filename"] = second["sha256"], second["filename"]
                report = self.check(captured, manifest)
                self.assertFalse(report["ready"])
                self.assertTrue(any("reviewed" in item["issue"] for item in report["issues"]))

    def test_catalog_prefix_asset_identity_is_required_but_display_name_is_not(self):
        captured, manifest = self.fixture()
        catalog = json.loads(captured[gate.CATALOG])
        catalog["assets"]["320bd7829fa4bdee"]["name"] = "Synthetic English fixture"
        captured[gate.CATALOG] = json.dumps(catalog).encode("utf8")
        self.assertTrue(self.check(captured, manifest)["ready"])
        manifest["base_images"]["320bd7829fa4bdee"]["prefix"] = "A05"
        report = self.check(captured, manifest)
        self.assertFalse(report["ready"])
        self.assertIn("native artwork prefix and catalog asset disagree", [item["issue"] for item in report["issues"]])

    def test_lossy_webp_cannot_claim_lossless_even_with_matching_content_hash(self):
        captured, manifest = self.fixture()
        record = manifest["base_images"]["320bd7829fa4bdee"]
        with Image.open(BytesIO(captured[gate.IMAGE_ROOT + record["filename"]])) as image:
            output = BytesIO()
            image.save(output, format="WEBP", quality=90)
        pins = self.replace_base_image(captured, manifest, output.getvalue())
        with patch.object(gate, "REVIEWED_BASE_IMAGES", pins):
            report = self.check(captured, manifest)
        self.assertFalse(report["ready"])
        self.assertIn("native image must be static lossless WebP without ancillary metadata", [item["issue"] for item in report["issues"]])

    def test_metadata_chunk_cannot_be_published_even_when_hashes_are_updated(self):
        captured, manifest = self.fixture()
        record = manifest["base_images"]["320bd7829fa4bdee"]
        image = captured[gate.IMAGE_ROOT + record["filename"]]
        metadata = b"synthetic-private-metadata"
        chunk = b"EXIF" + len(metadata).to_bytes(4, "little") + metadata + (b"\0" if len(metadata) % 2 else b"")
        body = image[8:] + chunk
        replacement = b"RIFF" + len(body).to_bytes(4, "little") + body
        pins = self.replace_base_image(captured, manifest, replacement)
        with patch.object(gate, "REVIEWED_BASE_IMAGES", pins):
            report = self.check(captured, manifest)
        self.assertFalse(report["ready"])
        self.assertIn("native image must be static lossless WebP without ancillary metadata", [item["issue"] for item in report["issues"]])
        self.assertNotIn(metadata.decode("ascii"), str(report))

    def test_hosted_copy_drift_and_extra_hosted_files_block_validation(self):
        with tempfile.TemporaryDirectory(prefix="cod-hub-hosted-art-test-") as temporary:
            hosted = Path(temporary)
            for path, value in self.source.items():
                if path.startswith(gate.IMAGE_ROOT):
                    (hosted / Path(path).name).write_bytes(value)
            image = next(hosted.glob("*.webp"))
            image.write_bytes(b"corrupt hosted bytes")
            (hosted / "unexpected.webp").write_bytes(b"unexpected")
            report = gate.evaluate_release(hosted_path=hosted)
            self.assertFalse(report["ready"])
            issues = [item["issue"] for item in report["issues"]]
            self.assertIn("hosted and bundled native image bytes differ", issues)
            self.assertIn("native image directory differs from the reviewed file set", issues)

    def test_hosted_manifest_cannot_keep_obsolete_weapon_image_references(self):
        with tempfile.TemporaryDirectory(prefix="cod-hub-hosted-manifest-") as temporary:
            root = Path(temporary)
            hosted = root / "v1"
            hosted.mkdir()
            for path, value in self.source.items():
                if path.startswith(gate.IMAGE_ROOT):
                    (hosted / Path(path).name).write_bytes(value)
            (root / "manifest.json").write_bytes(b'{"stale":true}')
            report = gate.evaluate_release(hosted_path=hosted)
            self.assertFalse(report["ready"])
            self.assertIn("hosted and bundled native manifests differ", [row["issue"] for row in report["issues"]])


if __name__ == "__main__":
    unittest.main()
