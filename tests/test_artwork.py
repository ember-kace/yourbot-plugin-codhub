"""Exact image identity, URL validation, graceful fallback and attribution."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cod_hub import artwork


ROOT = Path(__file__).resolve().parents[1]
ASSET = "320bd7829fa4bdee"
WEAPON = {"asset_id": ASSET, "game": "mw4", "name": "Kastov 762"}


def fixture():
    return {"format_version": 1, "game": "mw4", "provider": "MetaRadar", "credit_text": "Data by MetaRadar",
            "credit_url": "https://metaradar.gg/modernwarfare4/meta", "images": {ASSET: {
                "name": "Kastov 762", "image_url": "https://metaradar.gg/icons/mw4--kastov-762.webp",
                "source_page": "https://metaradar.gg/modernwarfare4/weapons/kastov-762",
                "sha256": "a"*64, "width": 512, "height": 256, "format": "WEBP", "mode": "RGBA",
                "alpha_extrema": [0, 255]}}}


class ArtworkTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="cod-hub-artwork-test-")
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "artwork.json"
        self.data = fixture()
        self.write()
        self.patcher = patch.object(artwork, "MANIFEST_PATH", self.path)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.addCleanup(artwork.clear_cache)
        artwork.clear_cache()

    def write(self, raw=None):
        self.path.write_bytes(raw if raw is not None else json.dumps(self.data).encode("utf8"))
        artwork.clear_cache()

    def test_asset_id_only_and_untrusted_image_fields_are_ignored(self):
        weapon = dict(WEAPON, name="Some other title", prefix="A99", image_url="https://attacker.invalid/fake.png")
        art = artwork.get_weapon_art(weapon)
        self.assertEqual(art["image_url"], self.data["images"][ASSET]["image_url"])
        for candidate in ({"name": "Kastov 762", "prefix": "A01"}, {"asset_id": ASSET.upper()},
                          dict(WEAPON, game="bo7"), dict(WEAPON, game=None),
                          dict(WEAPON, kind="attachment"), None):
            self.assertIsNone(artwork.get_weapon_art(candidate), candidate)
        art["alpha_extrema"][0] = 99
        self.assertEqual(artwork.get_weapon_art(WEAPON)["alpha_extrema"], [0, 255])

    def test_bad_image_urls_and_source_slug_mismatch_are_rejected(self):
        bad = ["http://metaradar.gg/icons/mw4--kastov-762.webp",
               "https://metaradar.gg.evil.invalid/icons/mw4--kastov-762.webp",
               "https://localhost/icons/mw4--kastov-762.webp",
               "https://127.0.0.1/icons/mw4--kastov-762.webp",
               "https://user@metaradar.gg/icons/mw4--kastov-762.webp",
               "https://metaradar.gg:444/icons/mw4--kastov-762.webp",
               "https://metaradar.gg/icons/mw4--kastov-762.webp?x=1",
               "https://metaradar.gg/icons/mw4--kastov-762.webp#x",
               "https://metaradar.gg/icons/mw4--kastov-762.webp?",
               "https://metaradar.gg/icons/mw4--kastov-762.webp\n",
               "https://metaradar.gg/icons/mw4--../fake.webp",
               "https://metaradar.gg/icons/mw4--kastov-762%2f..webp",
               "https://metaradar.gg/icons/mw4--hyeon-burst.webp"]
        for url in bad:
            self.data = fixture()
            self.data["images"][ASSET]["image_url"] = url
            self.write()
            self.assertIsNone(artwork.get_weapon_art(WEAPON), url)
        self.data = fixture()
        self.data["images"][ASSET]["image_url"] = "https://metaradar.gg:443/icons/mw4--kastov-762.webp"
        self.write()
        self.assertIsNotNone(artwork.get_weapon_art(WEAPON))

    def test_manifest_credit_provider_and_record_proof_are_required(self):
        cases = [("provider", "Other"), ("game", "warzone"), ("format_version", True),
                 ("credit_text", ""), ("credit_url", "https://attacker.invalid/meta")]
        for key, value in cases:
            self.data = fixture(); self.data[key] = value; self.write()
            self.assertIsNone(artwork.get_weapon_art(WEAPON), key)
        for key, value in [("alpha_extrema", [255, 255]), ("alpha_extrema", [False, 255]),
                           ("width", 1025), ("width", True), ("height", 0),
                           ("sha256", "missing"), ("mode", "RGB"), ("format", "PNG")]:
            self.data = fixture(); self.data["images"][ASSET][key] = value; self.write()
            self.assertIsNone(artwork.get_weapon_art(WEAPON), key)

    def test_provider_cdn_requires_exact_project_bucket_game_and_matching_slug(self):
        prefix = "https://oyozmuwtlqoyrsfvyorw.supabase.co/storage/v1/object/public/weapon-icons/"
        valid = prefix + "mw4--kastov-762.webp"
        self.data["images"][ASSET]["image_url"] = valid
        self.write()
        self.assertEqual(artwork.get_weapon_art(WEAPON)["image_url"], valid)
        bad = [valid.replace("oyozmuwtlqoyrsfvyorw", "another-project"),
               valid.replace("supabase.co/", "supabase.co.evil.invalid/"),
               valid.replace("/weapon-icons/", "/other-bucket/"),
               valid.replace("/public/", "/private/"), valid.replace("mw4--", "mw3--"),
               valid.replace("kastov-762", "m4"), valid + "?download=1", valid + "#x",
               valid.replace("https://", "http://"), valid.replace("https://", "https://user@"),
               valid.replace(".co/", ".co:444/"), valid.replace("/mw4--", "/../mw4--")]
        for url in bad:
            with self.subTest(url=url):
                self.data["images"][ASSET]["image_url"] = url
                self.write()
                self.assertIsNone(artwork.get_weapon_art(WEAPON))

    def test_missing_malformed_oversized_duplicate_or_nonfinite_data_fails_closed(self):
        for raw in (b"broken", b"[]", b" " * (artwork.MAX_MANIFEST_BYTES+1),
                    b'{"provider":"MetaRadar","provider":"Other"}', b'{"value":NaN}'):
            self.write(raw)
            self.assertIsNone(artwork.get_weapon_art(WEAPON))
        self.path.unlink()
        artwork.clear_cache()
        self.assertIsNone(artwork.get_weapon_art(WEAPON))

    def test_decorated_card_is_independent_bounded_and_always_credited(self):
        original = {"title": "My build", "description": "x"*5000, "fields": [{"name": "Weapon", "value": "Kastov 762"}]}
        before = deepcopy(original)
        result = artwork.decorate_embed(original, WEAPON)
        self.assertEqual(original, before)
        self.assertLessEqual(len(result["description"]), 4096)
        self.assertIn("[Base weapon image](https://metaradar.gg/modernwarfare4/weapons/kastov-762)", result["description"])
        self.assertTrue(result["description"].endswith("[Data by MetaRadar](https://metaradar.gg/modernwarfare4/meta)"))
        self.assertEqual(result["image"]["url"], self.data["images"][ASSET]["image_url"])
        self.assertEqual(artwork.decorate_embed(result, WEAPON), result)
        result["fields"][0]["value"] = "Changed"
        self.assertEqual(original, before)

    def test_absent_art_keeps_card_identical_and_overfull_card_adds_no_art(self):
        original = {"title": "Other weapon", "description": "Its text stays available."}
        self.assertEqual(artwork.decorate_embed(original, {"asset_id": "0"*16}), original)
        full = {"title": "A", "description": "Original", "fields": [{"name": "A", "value": "x"*5999}]}
        self.assertEqual(artwork.decorate_embed(full, WEAPON), full)
        bounded = {"title": "A", "description": "x"*4000, "fields": [{"name": "A", "value": "x"*3000}]}
        result = artwork.decorate_embed(bounded, WEAPON)
        self.assertLessEqual(len(result["title"])+len(result["description"])+3001, 6000)

    def test_real_verified_metadata_has_exact_27_alpha_weapon_mappings(self):
        path = ROOT / "plugin/cod_hub/data/artwork.json"
        self.assertTrue(path.is_file())
        with patch.object(artwork, "MANIFEST_PATH", path):
            artwork.clear_cache()
            raw = json.loads(path.read_text(encoding="utf8"))
            self.assertEqual(len(raw["images"]), 27)
            for asset_id, record in raw["images"].items():
                art = artwork.get_weapon_art({"asset_id": asset_id, "game": "mw4"})
                self.assertIsNotNone(art, asset_id)
                self.assertEqual(art["image_url"], record["image_url"])
                self.assertEqual(art["alpha_extrema"], [0, 255])

    def test_published_index_addition_is_exact_gs_and_coarse_candidates_stay_out(self):
        manifest = json.loads((ROOT / "plugin/cod_hub/data/artwork.json").read_text(encoding="utf8"))
        gs = manifest["images"]["2efa8aea20d8b45d"]
        self.assertEqual(gs["name"], ".50 GS")
        self.assertEqual(gs["source_page"], "https://metaradar.gg/modernwarfare4/weapons/50-gs")
        self.assertTrue(gs["image_url"].startswith("https://oyozmuwtlqoyrsfvyorw.supabase.co/storage/v1/object/public/weapon-icons/mw4--50-gs.webp"))
        self.assertEqual(gs["sha256"], "470820ecc0a98a331f215119bcece93f87c1d26f3bb425030ab3ea406b730505")
        for asset_id in ("6cc4eea570f88e27", "66bbbb111859e8e1", "12cf1c65abc24d34"):
            self.assertNotIn(asset_id, manifest["images"])


if __name__ == "__main__":
    unittest.main()
