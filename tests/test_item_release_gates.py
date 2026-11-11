"""Captured resources and hosted item pixels cannot drift after review."""
from copy import deepcopy
import hashlib
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from tests.test_item_catalog_release import candidate
from tools import item_artwork_release as art, item_catalog_release as catalog


class ItemReleaseGateTests(unittest.TestCase):
    def test_shard_mutation_and_missing_resources_fail_after_a_manifest_is_reviewed(self):
        resources = catalog.build_resources(candidate())
        captured = {"cod_hub/data/" + name: raw for name, raw in resources.items()}
        pin = hashlib.sha256(captured[catalog.MANIFEST]).hexdigest()
        with patch.object(catalog, "REVIEWED_MANIFEST_SHA256", pin):
            self.assertTrue(catalog.evaluate_captured(captured)["ready"])
            shard = next(name for name in captured if "/items/" in name)
            original = captured[shard]
            rows = json.loads(original)
            rows[0]["name"] = "Another synthetic name"
            captured[shard] = catalog.canonical(rows)
            self.assertFalse(catalog.evaluate_captured(captured)["ready"])
            captured[shard] = original
            del captured[shard]
            self.assertFalse(catalog.evaluate_captured(captured)["ready"])

    def test_manifest_cannot_redirect_packaging_to_an_unreviewed_path(self):
        resources = catalog.build_resources(candidate())
        raw = resources["item-catalog.json"]
        pin = hashlib.sha256(raw).hexdigest()
        document = json.loads(raw)
        document["categories"]["attachment"]["shards"][0]["file"] = "../../unreviewed.json"
        with patch.object(catalog, "REVIEWED_MANIFEST_SHA256", pin):
            with self.assertRaises(ValueError):
                catalog.required_files(catalog.canonical(document))

    def test_hosted_native_image_pixels_and_scope_are_both_reviewed(self):
        image = Image.new("RGBA", (8, 8), (90, 160, 120, 180))
        stream = BytesIO()
        image.save(stream, "WEBP", lossless=True, exact=True)
        raw = stream.getvalue()
        digest = hashlib.sha256(raw).hexdigest()
        identity = "1" * 16
        record = {"image_asset_id": identity, "filename": digest + ".webp", "sha256": digest,
                  "width": 8, "height": 8, "alpha_extrema": [180, 180],
                  "rgba_sha256": hashlib.sha256(image.tobytes()).hexdigest(), "format": "WEBP",
                  "lossless": True, "scope": "native_part_preview", "canonical_full_image": False, "part_index": 0}
        document = {"format_version": 1, "game": "mw4", "snapshot_date": "2026-11-11",
                    "source_id": art.SOURCE_ID, "maximum_delivery_edge": 768,
                    "images": {identity: record}, "by_asset": {"2" * 16: identity}}
        body = catalog.canonical(document)
        with tempfile.TemporaryDirectory(prefix="cod-hub-item-release-") as folder:
            root = Path(folder)
            plugin = root / "plugin"
            target = plugin / art.RESOURCE
            target.parent.mkdir(parents=True)
            target.write_bytes(body)
            hosted = root / "hosted"
            hosted.mkdir()
            (hosted / record["filename"]).write_bytes(raw)
            with patch.object(art, "REVIEWED_INDEX_SHA256", hashlib.sha256(body).hexdigest()):
                self.assertTrue(art.evaluate_release(plugin, hosted)["ready"])
                (hosted / record["filename"]).write_bytes(b"corrupt")
                self.assertFalse(art.evaluate_release(plugin, hosted)["ready"])
                changed = deepcopy(document)
                changed["images"][identity]["canonical_full_image"] = True
                self.assertFalse(art.evaluate_captured({art.RESOURCE: catalog.canonical(changed)})["ready"])


if __name__ == "__main__":
    unittest.main()
