"""Legacy slash search must use the same verified names as the card browser."""
import unittest

from cod_hub import catalog


class LegacyCatalogQualityTests(unittest.TestCase):
    def test_all_untranslated_exact_attachment_refs_stay_out_of_search(self):
        source = catalog.get_catalog()
        unnamed = [asset for asset in source.assets.values()
                   if asset.get("kind") == "attachment" and asset.get("internal_ref")
                   and asset.get("quality") not in catalog.ENGLISH_QUALITIES]
        # Genuine name recoveries reduce this set; keep the filtering regression
        # non-vacuous without pinning successfully recovered names as unknown.
        self.assertTrue(unnamed)
        for asset in unnamed:
            with self.subTest(ref=asset["internal_ref"]):
                rows = source.search_attachments(asset["internal_ref"], limit=25)
                self.assertNotIn(asset["internal_ref"], [row["internal_ref"] for row in rows])
                self.assertTrue(all(row["quality"] in catalog.ENGLISH_QUALITIES for row in rows))

    def test_verified_exact_ref_and_captured_name_remain_searchable(self):
        for query in ("rex_comp_bal_b", "FIELD TAC 1.4 COMP"):
            rows = catalog.search_attachments(query, weapon="A01", limit=25)
            self.assertTrue(rows)
            self.assertEqual(rows[0]["asset_id"], "01ddc439e1180539")
            self.assertEqual(rows[0]["name"], "Field Tac 1.4 Comp")
            self.assertEqual(rows[0]["quality"], "native_localization")

    def test_partial_slot_queries_only_return_verified_english_results(self):
        for query in ("laser", "stock", "tuning", "thermal", "all"):
            for row in catalog.search_attachments(query, limit=25):
                self.assertIn(row["quality"], catalog.ENGLISH_QUALITIES)
                self.assertFalse(row["name"].startswith("Untranslated"))

    def test_rejected_historical_label_cannot_select_a_different_attachment(self):
        source = catalog.get_catalog()
        bruen = "09627259be35efa1"
        real_cronen = {"109862abaa6f17ac", "5f03c03e4b7f2cce"}
        self.assertIn("Cronen R808", source.assets[bruen]["aliases"])
        self.assertTrue(source.assets[bruen]["name_claims"])
        for query in ("Cronen R808", "r808"):
            rows = source.search_attachments(query, limit=25)
            self.assertNotIn(bruen, {row["asset_id"] for row in rows})
            self.assertTrue(real_cronen <= {row["asset_id"] for row in rows})
            page = source.browse_attachments("A01", query=query)
            self.assertNotIn(bruen, {row["asset_id"] for row in page["items"]})
            self.assertIn("5f03c03e4b7f2cce", {row["asset_id"] for row in page["items"]})
        self.assertEqual(source.search_attachments("Bruen THRM-60 Optic", weapon="A01")[0]["asset_id"], bruen)
        self.assertEqual(source.browse_attachments("A01", query="Bruen THRM-60 Optic")["items"][0]["asset_id"], bruen)
        self.assertNotIn("Cronen R808", source.get_attachment("A01", bruen)["aliases"])

    def test_rejected_alias_filter_also_applies_to_weapon_and_shared_rank_helpers(self):
        from copy import deepcopy
        original = catalog.get_catalog()
        fixture = catalog.Catalog(deepcopy(original.schema_data), deepcopy(original.data))
        weapon = fixture.assets[fixture.weapons["A01"]["asset_id"]]
        weapon["aliases"].append("M4")
        weapon.setdefault("name_claims", []).append({"preference_review": {"decision": "prefer_native", "current_name": "M4"}})
        self.assertNotIn("A01", {row["prefix"] for row in fixture.search("M4", limit=25)})
        self.assertNotIn("A01", {row["prefix"] for row in fixture.browse_weapons(query="M4")["items"]})
        self.assertIsNone(catalog._browse_rank("m4", weapon, ("name",)))
        weapon["name"] = "M4"  # A later preferred name must always be searchable.
        self.assertEqual(catalog._browse_rank("m4", weapon, ("name",)), 0)

    def test_rejected_reference_alias_is_not_searched_or_exposed(self):
        from copy import deepcopy
        original = catalog.get_catalog()
        fixture = catalog.Catalog(deepcopy(original.schema_data), deepcopy(original.data))
        reference = next(row for row in fixture.data["reference_weapons"]
                         if row.get("native_prefix") not in fixture.weapons)
        rejected = "Wrong Historical Weapon"
        reference["aliases"].append({"name": rejected, "source_id": "test-only"})
        reference.setdefault("name_claims", []).append({
            "preference_review": {"decision": "prefer_native", "current_name": rejected}})
        self.assertFalse(fixture.search(rejected))
        self.assertFalse(fixture.browse_weapons(query=rejected)["items"])
        self.assertEqual(fixture.search(reference["name"])[0]["asset_id"], reference["asset_id"])
        named = fixture.get_weapon(reference["asset_id"])
        self.assertNotIn(rejected, [a.get("name") if isinstance(a, dict) else a
                                    for a in named["aliases"]])
        self.assertIn({"name": rejected, "source_id": "test-only"}, reference["aliases"])


if __name__ == "__main__":
    unittest.main()
