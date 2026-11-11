"""Public DEFAULT-name contracts preserve distinct native attachment identities."""
import json
from pathlib import Path
import unittest

from cod_hub import app, cards, catalog

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/name-regressions.json"
INVENTORY = ROOT / "metadata/name-inventory.json"


def read(path):
    return json.loads(path.read_text(encoding="utf8"))


class NativeVariantNameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = read(ROOT / "plugin/cod_hub/data/catalog.json")
        cls.sources = read(ROOT / "plugin/cod_hub/data/facts-sources.json")["sources"]
        cls.records = {key: row for key, row in read(FIXTURE)["records"].items() if "generic_asset_id" in row}

    def test_six_names_keep_exact_own_hash_raw_value_and_english_claim(self):
        self.assertEqual(len(self.records), 6)
        for asset_id, expected in self.records.items():
            with self.subTest(asset=asset_id):
                asset = self.data["assets"][asset_id]
                self.assertEqual((asset["name"], asset["quality"]), (expected["name"], "native_localization"))
                self.assertEqual((asset["internal_ref"], asset["loot_id"]), (expected["internal_ref"], expected["loot_id"]))
                self.assertNotEqual(expected["root_name_hash"], expected["nested_name_hash"])
                claims = [c for c in asset["name_claims"] if c["source_id"] == expected["source_id"]]
                self.assertEqual(len(claims), 1)
                claim = claims[0]
                self.assertEqual((claim["name_hash"], claim["raw_name"], claim["name"]),
                                 (expected["selected_name_hash"], expected["raw_name"], expected["name"]))
                self.assertEqual((claim["quality"], claim["language"]), ("native_localization", "en"))
                source = self.sources[claim["source_id"]]
                self.assertEqual((source["kind"], source["language"]), ("native_localization", "en"))
                self.assertEqual(claim["source_date"], source["source_date"])
                if asset_id == "42bc45f6b88b63e7":
                    self.assertEqual(claim["raw_name"], "FSS IS40 ")
                    self.assertEqual(claim["normalization"]["raw_name"], "FSS IS40 ")
                    self.assertEqual(claim["normalization"]["display_name"], "FSS IS40")

    def test_six_native_diagnostic_codes_resolve_original_parts_and_cards(self):
        cc = catalog.get_catalog()
        for asset_id, expected in self.records.items():
            with self.subTest(code=expected["code"]):
                native = cc.codec.decode(expected["code"])
                self.assertEqual(cc.codec.encode(native.prefix, native.indexes), expected["code"])
                build = app._named_build(catalog.resolve_build(expected["code"]))
                self.assertEqual(build["native_slots"][expected["slot"]], expected["native_id"])
                self.assertEqual(build["unknowns"], [])
                self.assertEqual(len(build["attachments"]), 1)
                item = build["attachments"][0]
                self.assertEqual((item["asset_id"], item["index"], item["slot"], item["name"]),
                                 (asset_id, expected["native_id"], expected["slot"], expected["name"]))
                embed = cards.build_embed(build)
                self.assertTrue(any(f["value"] == expected["name"] for f in embed["fields"]))
                self.assertIn("Verified English names", embed["footer"]["text"])

    def test_generic_and_variant_parts_remain_separate_native_identities(self):
        cc = catalog.get_catalog()
        for asset_id, expected in self.records.items():
            with self.subTest(asset=asset_id):
                ids = self.data["weapons"][expected["prefix"]]["slots"][expected["slot"]]["ids"]
                self.assertEqual(ids[str(expected["native_id"])]["asset_id"], asset_id)
                self.assertEqual(ids[str(expected["generic_native_id"])]["asset_id"], expected["generic_asset_id"])
                self.assertNotEqual(asset_id, expected["generic_asset_id"])
                vector = [0] * len(cc.schema.slots)
                vector[next(i for i, slot in enumerate(cc.schema.slots) if slot.key == expected["slot"])] = expected["generic_native_id"]
                generic_code = cc.codec.encode(expected["prefix"], vector)
                self.assertNotEqual(generic_code, expected["code"])
                generic = catalog.resolve_build(generic_code)["attachments"][0]
                self.assertEqual(generic["asset_id"], expected["generic_asset_id"])
                self.assertEqual(generic["name"], "AA54 V.3 Bipod" if expected["name"] == "Bipod" else expected["name"])

    def test_public_inventory_retains_each_exact_own_default_name_hash(self):
        inventory = {row["asset_id"]: row for row in read(INVENTORY)["assets"]}
        self.assertEqual(len(inventory), 1267)
        for asset_id, expected in self.records.items():
            row = inventory[asset_id]
            self.assertIn(expected["selected_name_hash"], row["localize_hashes"])
            self.assertEqual((row["internal_ref"], row["loot_id"]), (expected["internal_ref"], expected["loot_id"]))
            self.assertNotIn("internal_description", self.data["assets"][asset_id])
            self.assertNotIn("technical_description", self.data["assets"][asset_id])


if __name__ == "__main__":
    unittest.main()
