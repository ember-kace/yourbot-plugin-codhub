"""Item artwork stays on a fixed image host and cannot replace build renders."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cod_hub import item_artwork


class ItemArtworkTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="cod-hub-item-art-test-")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.asset, self.image, self.digest = "1" * 16, "2" * 16, "3" * 64
        self.document = {"format_version": 1, "game": "mw4", "by_asset": {self.asset: self.image},
            "images": {self.image: {"image_asset_id": self.image, "sha256": self.digest,
                "filename": self.digest + ".webp", "width": 256, "height": 256, "format": "WEBP", "lossless": True}}}
        for name, value in (("DATA", self.root), ("INDEX_PATH", self.root / "item-artwork.json")):
            patcher = patch.object(item_artwork, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(item_artwork.clear_cache)
        self.write()

    def write(self):
        (self.root / "item-artwork.json").write_text(json.dumps(self.document), encoding="utf8")
        item_artwork.clear_cache()

    def test_native_identity_returns_only_the_fixed_content_addressed_url(self):
        direct = item_artwork.get_art({"image_asset_id": self.image})
        fallback = item_artwork.get_art({"asset_id": self.asset})
        self.assertEqual(direct, fallback)
        self.assertEqual(direct["url"], item_artwork.HOST + self.digest + ".webp")
        self.assertEqual(direct["scope"], "native_item_artwork")
        self.assertIsNone(item_artwork.get_art({"asset_id": self.asset, "image_asset_id": "4" * 16}))
        self.assertIsNone(item_artwork.get_art({"asset_id": "4" * 16}))
        self.assertIsNone(item_artwork.get_art(None))

    def test_item_kind_controls_presentation_and_leaves_build_rendering_out_of_scope(self):
        for kind, destination in (("camo", "thumbnail"), ("attachment", "thumbnail"), ("playercards", "image")):
            embed = {"title": "Synthetic native item"}
            self.assertIs(item_artwork.decorate_embed(embed, {"asset_id": self.asset, "kind": kind}), embed)
            self.assertEqual(embed[destination]["url"], item_artwork.HOST + self.digest + ".webp")

    def test_missing_or_invalid_metadata_has_no_external_or_substitute_image(self):
        original = self.document["images"][self.image].copy()
        for key, value in (("filename", "https://example.invalid/image.webp"), ("sha256", "../escape"),
                           ("width", True), ("width", 100000), ("height", 0), ("lossless", False)):
            self.document["images"][self.image] = {**original, key: value}
            self.write()
            with self.subTest(key=key, value=value):
                self.assertIsNone(item_artwork.get_art({"asset_id": self.asset}))
        (self.root / "item-artwork.json").unlink()
        item_artwork.clear_cache()
        self.assertIsNone(item_artwork.get_art({"asset_id": self.asset}))

    def test_layered_artwork_keeps_an_explicit_static_preview_caption(self):
        self.document["images"][self.image].update(scope="native_part_preview", canonical_full_image=False, part_index=0)
        self.write()
        embed = item_artwork.decorate_embed({"title": "Synthetic calling card", "description": "Reference."},
                                          {"asset_id": self.asset, "kind": "playercards"})
        self.assertIn("Static native artwork preview.", embed["description"])
        self.assertIn("image", embed)
        for override in ({"canonical_full_image": True}, {"part_index": 1}, {"scope": "complete_animation"}):
            self.document["images"][self.image].update(override)
            self.write()
            self.assertIsNone(item_artwork.get_art({"asset_id": self.asset}))


if __name__ == "__main__":
    unittest.main()
