"""Golden identity and data-quality checks, independent of Discord/the SDK."""
import json
from pathlib import Path
import unittest

from cod_hub.codec import CodecSchema, NativeCodec


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "plugin/cod_hub/data"
FIXTURES = ROOT / "tests/fixtures"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


class CatalogDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = read(DATA / "schema.json")
        cls.catalog = read(DATA / "catalog.json")
        cls.labels = read(ROOT / "metadata/observed-labels.json")
        cls.sources = read(DATA / "facts-sources.json")

    def test_authoritative_ids_are_not_engine_array_positions(self):
        cases = [
            ("A01", "barrel", 2, "rex_bar_lgt_akilo"),
            ("A01", "stock", 3, "rex_stock_ass_akilo"),
            ("A01", "rear_grip", 3, "rex_pgrip_ass_akilo"),
            ("A01", "muzzle", 3, "rex_comp_bal_b"),
            ("A01", "muzzle", 2, "rex_comp_hoz_b"),
            ("A09", "apex", 3, "rex_rec_xar1_hyperburst"),
            ("A09", "ammunition", 6, "rex_ammo_68spc_op"),
        ]
        for prefix, slot, number, expected in cases:
            with self.subTest(prefix=prefix, slot=slot, number=number):
                identity = self.catalog["weapons"][prefix]["slots"][slot]["ids"][str(number)]["asset_id"]
                self.assertEqual(self.catalog["assets"][identity]["internal_ref"], expected)

    def test_reserved_positions_and_utility_entries_remain_explicit(self):
        self.assertEqual(len(self.catalog["weapons"]), 31)
        self.assertTrue(self.catalog["weapons"]["P01"]["utility"])
        magazine = self.catalog["weapons"]["A01"]["slots"]["magazine"]
        self.assertIn(8, magazine["reserved_ids"])
        self.assertNotIn("8", magazine["ids"])
        self.assertEqual(sum(len(c["reserved_ids"]) for c in self.schema["classes"].values()), 860)
        self.assertEqual(sum(len(s["reserved_ids"]) for w in self.catalog["weapons"].values() for s in w["slots"].values()), 17)
        self.assertEqual(sum(len(s["ids"]) for w in self.catalog["weapons"].values() for s in w["slots"].values()), 2401)

    def test_reference_and_selection_identity_closure(self):
        assets = self.catalog["assets"]
        self.assertEqual(len(self.catalog["reference_weapons"]), 35)
        self.assertEqual(sum(not r["native_supported"] for r in self.catalog["reference_weapons"]), 5)
        radices = {s["key"]: s["radix"] for s in self.schema["slots"]}
        for prefix, weapon in self.catalog["weapons"].items():
            self.assertIn(weapon["asset_id"], assets)
            for slot, group in weapon["slots"].items():
                numbers = {int(k) for k in group["ids"]}
                reserved = set(group["reserved_ids"])
                self.assertFalse(numbers & reserved)
                self.assertEqual(numbers | reserved, set(range(1, group["declared_positions"] + 1)))
                for number, selected in group["ids"].items():
                    self.assertLess(int(number), radices[slot], (prefix, slot, number))
                    self.assertIn(selected["asset_id"], assets)
                    self.assertIsInstance(selected["metadata_locked"], bool)

    def test_observed_and_internal_names_keep_their_source_quality(self):
        for identity, asset in self.catalog["assets"].items():
            self.assertIn(asset["quality"], {"user_capture", "published_fixture", "native_localization", "official_reference", "internal"})
            for source in asset["source_ids"]:
                self.assertIn(source, self.sources["sources"])
            if asset["kind"] == "attachment" and asset["quality"] in {"user_capture", "published_fixture"}:
                observed = self.labels["assets"][identity]
                self.assertEqual(asset["name"], observed["preferred"])
                self.assertEqual(asset["name_ambiguous"], observed["ambiguous"])
                self.assertTrue(observed["observations"])
            if asset["quality"] == "native_localization":
                claims = [c for c in asset.get("name_claims", []) if c.get("quality") == "native_localization"]
                self.assertTrue(claims, identity)
                for claim in claims:
                    self.assertRegex(claim["name_hash"], r"^[0-9a-f]{16}$")
                    self.assertEqual(self.sources["sources"][claim["source_id"]]["language"], "en")
        self.assertNotIn("english_decrypted", self.labels)
        self.assertEqual(self.catalog["assets"]["01ddc439e1180539"]["quality"], "native_localization")
        self.assertEqual(self.labels["assets"]["01ddc439e1180539"]["quality"], "user_capture")
        self.assertEqual(self.catalog["assets"]["01ddc439e1180539"]["name"], "Field Tac 1.4 Comp")

    def test_ui_specific_slots_are_not_mislabelled_as_generic_grips(self):
        weapons = self.catalog["weapons"]
        self.assertEqual(weapons["M03"]["ui_slot_labels"]["rear_grip"], "Bolt")
        self.assertEqual(weapons["R04"]["ui_slot_labels"]["other"], "Bolt")
        self.assertEqual(weapons["P02"]["ui_slot_labels"]["stock"], "Trigger action")
        self.assertEqual(weapons["P07"]["ui_slot_labels"]["magazine"], "Cylinder")

    def test_launch_baselines_are_dated_and_never_modified_build_stats(self):
        baselines = [a["base_stats"] for a in self.catalog["assets"].values() if "base_stats" in a]
        self.assertEqual(len(baselines), 28)
        for baseline in baselines:
            self.assertEqual(baseline["quality"], "published_launch_snapshot")
            self.assertEqual(baseline["data_date"], "2026-10-24")
            self.assertLessEqual(set(baseline["values"]), {"rpm", "magazine", "reserve", "weaponLevels", "unlockLevel", "caliber"})
            self.assertTrue(baseline["source_ids"])
            self.assertLessEqual(set(baseline["values"]), set(baseline["units"]))
        self.assertFalse(self.sources["limits"]["baseline_statistics_are_current_balance"])

    def test_packaged_data_contains_facts_without_private_paths_or_game_blobs(self):
        self.assertEqual({p.name for p in DATA.iterdir() if p.is_file()},
                         {"schema.json", "catalog.json", "facts-sources.json", "artwork.json", "native-artwork.json", "telemetry.json", "NOTICE-HashIndex.txt",
                          "item-catalog.json", "item-artwork.json", "native-guide.json", "native-guide-sources.json"})
        for path in DATA.rglob("*"):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]")
            self.assertNotIn("data_b64", text)
        self.assertIn("Copyright (c) 2024 Antoine Willerval", (DATA / "NOTICE-HashIndex.txt").read_text())

    def test_all_130_published_codes_roundtrip_with_production_schema(self):
        rows = read(FIXTURES / "native-codes.json")["codes"]
        self.assertEqual(len(rows), 130)
        codec = NativeCodec(CodecSchema.from_dict(self.schema))
        for code in rows:
            with self.subTest(code=code):
                decoded = codec.decode(code)
                self.assertEqual(decoded.unknown_bits, 0)
                self.assertEqual(codec.encode(decoded.prefix, decoded.indexes), code)


if __name__ == "__main__":
    unittest.main()
