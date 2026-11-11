"""Technical descriptions cover only the exact user-approved hidden 72 records."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tools import english_release_gate as gate
from tools import import_english_names as importer

ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "metadata/policies/internal-descriptions.json"
TECHNICAL_REVIEW = ROOT / "metadata/policies/technical-descriptions.json"


class InternalDescriptionGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.review = json.loads(REVIEW.read_text(encoding="utf8"))
        cls.original_catalog = gate.read_json(ROOT / "plugin/cod_hub/data/catalog.json")
        cls.original_sources = gate.read_json(ROOT / "plugin/cod_hub/data/facts-sources.json")
        technical = json.loads(TECHNICAL_REVIEW.read_text(encoding="utf8"))
        named_controls = [key for key, asset in sorted(cls.original_catalog["assets"].items())
                          if key not in cls.review["records"] and key not in technical["records"]
                          and asset["quality"] in gate.ACCEPTED_QUALITIES][:8]
        cls.remaining = sorted(technical["records"]) + named_controls
        cls.catalog = deepcopy(cls.original_catalog)
        for asset in cls.catalog["assets"].values():
            asset.pop("internal_description", None)
            # Exercise the original 72-record policy independently of the
            # separately approved eleven technical captions.
            asset.pop("technical_description", None)
        cls.sources = deepcopy(cls.original_sources)
        cls.sources["sources"][gate.INTERNAL_DESCRIPTION_SOURCE_ID] = deepcopy(cls.review["source"])
        for asset_id, reviewed in cls.review["records"].items():
            asset = cls.catalog["assets"][asset_id]
            for key, value in reviewed["base"].items():
                if value is None:
                    asset.pop(key, None)
                else:
                    asset[key] = deepcopy(value)
            asset["internal_description"] = deepcopy(reviewed["internal_description"])
        cls.baseline = gate.evaluate_documents(cls.catalog, cls.sources)

    def copy(self):
        return deepcopy(self.catalog), deepcopy(self.sources)

    def assert_description_loss(self, catalog, sources, lost=1):
        result = gate.evaluate_documents(catalog, sources)
        self.assertEqual(result["total_described"], 72 - lost)
        self.assertFalse(result["ready"])
        return result

    def test_exact_review_scope_source_and_every_record_are_pinned(self):
        self.assertEqual(len(self.review["records"]), 72)
        self.assertEqual(gate.ids_digest(self.review["records"]), gate.EXPECTED_INTERNAL_IDS_SHA256)
        self.assertEqual(gate.canonical_digest(self.review["records"]), gate.EXPECTED_INTERNAL_REVIEW_SHA256)
        self.assertEqual(gate.canonical_digest(self.review["source"]), gate.EXPECTED_INTERNAL_SOURCE_SHA256)
        for asset_id, reviewed in self.review["records"].items():
            self.assertEqual(gate.canonical_digest(reviewed), gate.INTERNAL_DESCRIPTION_RECORD_HASHES[asset_id])
            self.assertEqual(reviewed["base"]["kind"], "attachment")
            self.assertTrue(reviewed["internal_description"]["text"].startswith("Internal · "))
        self.assertNotIn("reviewed_internal_description", gate.ACCEPTED_QUALITIES)
        self.assertNotIn("reviewed_internal_description", importer.ACCEPTED_QUALITIES)

    def test_descriptions_increase_coverage_without_claiming_translated_names(self):
        plain, sources = self.copy()
        for record in plain["assets"].values():
            record.pop("internal_description", None)
        before = gate.evaluate_documents(plain, sources)
        result = self.baseline
        self.assertEqual(result["required"], 1302)
        self.assertEqual(result["total_translated"], before["total_translated"])
        self.assertEqual(result["total_described"], 72)
        self.assertEqual(result["total_english_covered"], before["total_translated"] + 72)
        self.assertEqual(result["counts"]["assets_described"], 72)
        self.assertEqual(result["counts"]["reference_weapons_described"], 0)
        self.assertEqual(len(result["described_ids"]), 72)
        self.assertEqual(gate.native_identity_digest(self.catalog["weapons"]), gate.EXPECTED_NATIVE_IDENTITY_SHA256)

    def test_changed_text_metadata_or_evidence_loses_only_its_approval(self):
        asset_id = next(iter(self.review["records"]))
        changes = [lambda d: d.update(text="Internal · A different description."),
                   lambda d: d.update(text="Optic component"),
                   lambda d: d.update(quality="official_reference"),
                   lambda d: d.update(language="fr"),
                   lambda d: d.update(source_id="forged-source"),
                   lambda d: d.update(source_date="2026-02-30"),
                   lambda d: d.pop("evidence"),
                   lambda d: d["evidence"].update(source_proven_nonselectable=False),
                   lambda d: d["evidence"].update(asset_id="0" * 16),
                   lambda d: d["evidence"].update(historical_evidence_sha256="a" * 64),
                   lambda d: d["evidence"].update(finding="A new unsupported claim."),
                   lambda d: d["evidence"].update(native_references=[])]
        for change in changes:
            catalog, sources = self.copy()
            change(catalog["assets"][asset_id]["internal_description"])
            with self.subTest(change=change):
                result = self.assert_description_loss(catalog, sources)
                self.assertIn("asset:" + asset_id, result["missing_ids"])

    def test_original_name_identity_aliases_and_claims_cannot_be_rewritten(self):
        asset_id = next(iter(self.review["records"]))
        changes = {"name": "A rewritten internal label", "quality": "unknown", "kind": "weapon",
                   "internal_ref": "different_internal_ref", "loot_id": 1, "aliases": ["Invented alias"],
                   "source_ids": ["forged-source"], "name_claims": [], "name_ambiguous": True}
        for key, value in changes.items():
            catalog, sources = self.copy()
            catalog["assets"][asset_id][key] = value
            with self.subTest(key=key):
                result = self.assert_description_loss(catalog, sources)
                self.assertTrue(any(i["code"] == "internal_description_review_changed" for i in result["issues"]))

    def test_missing_description_or_missing_forged_source_fails_closed(self):
        catalog, sources = self.copy()
        catalog["assets"][next(iter(self.review["records"]))].pop("internal_description")
        self.assert_description_loss(catalog, sources)
        catalog, sources = self.copy()
        sources["sources"].pop(gate.INTERNAL_DESCRIPTION_SOURCE_ID)
        self.assert_description_loss(catalog, sources, lost=72)
        for key, value in {"scope_asset_count": 73, "scope_asset_ids_sha256": "a" * 64,
                           "canonical_review_sha256": "a" * 64, "input_sha256": "a" * 64,
                           "language": "fr", "source_date": "2026-02-30", "kind": "official_reference"}.items():
            catalog, sources = self.copy()
            sources["sources"][gate.INTERNAL_DESCRIPTION_SOURCE_ID][key] = value
            with self.subTest(key=key):
                self.assert_description_loss(catalog, sources, lost=72)

    def test_review_does_not_replace_missing_original_source_registration(self):
        catalog, sources = self.copy()
        asset_id = next(iter(self.review["records"]))
        original_source = catalog["assets"][asset_id]["source_ids"][0]
        sources["sources"].pop(original_source)
        result = gate.evaluate_documents(catalog, sources)
        self.assertNotIn("asset:" + asset_id, result["described_ids"])
        self.assertFalse(result["ready"])
        self.assertTrue(any(i["id"] == "asset:" + asset_id and i["code"] == "invalid_source_refs"
                            for i in result["issues"]))

    def test_other_nineteen_selectable_item_utility_and_references_are_not_exempt(self):
        self.assertEqual(len(self.remaining), 19)
        utility = self.catalog["weapons"]["P01"]["asset_id"]
        self.assertIn(utility, self.remaining)
        named = next(key for key, record in self.catalog["assets"].items()
                     if key not in self.review["records"] and record["quality"] in gate.ACCEPTED_QUALITIES)
        template = next(iter(self.review["records"].values()))["internal_description"]
        for asset_id in self.remaining + [named]:
            catalog, sources = self.copy()
            catalog["assets"][asset_id]["internal_description"] = deepcopy(template)
            result = gate.evaluate_documents(catalog, sources)
            with self.subTest(asset_id=asset_id):
                self.assertEqual(result["total_described"], 72)
                self.assertFalse(result["ready"])
                self.assertTrue(any(i["id"] == "asset:" + asset_id and i["code"] == "internal_description_scope"
                                    for i in result["issues"]))
        catalog, sources = self.copy()
        catalog["reference_weapons"][0]["internal_description"] = deepcopy(template)
        result = gate.evaluate_documents(catalog, sources)
        self.assertFalse(result["ready"])
        self.assertTrue(any(i["id"].startswith("reference:") and i["code"] == "internal_description_scope"
                            for i in result["issues"]))

    def test_true_verified_name_takes_precedence_without_double_counting(self):
        catalog, sources = self.copy()
        asset = catalog["assets"][next(iter(self.review["records"]))]
        sources["sources"]["synthetic-actual-name"] = {"title": "Synthetic exact English-name test only",
            "kind": "official_reference", "language": "en", "source_date": "2026-11-09",
            "url": "https://example.invalid/exact-name-test"}
        asset.update(name="Verified English Test Name", quality="official_reference",
                     source_ids=["synthetic-actual-name"], name_ambiguous=False)
        result = gate.evaluate_documents(catalog, sources)
        self.assertEqual(result["total_described"], 71)
        self.assertEqual(result["total_translated"], self.baseline["total_translated"] + 1)
        self.assertEqual(result["total_english_covered"], self.baseline["total_english_covered"])

    def test_all_true_names_can_complete_scope_without_using_descriptions(self):
        catalog, sources = self.copy()
        sources["sources"]["synthetic-complete-names"] = {"title": "Synthetic complete-name test only",
            "kind": "official_reference", "language": "en", "source_date": "2026-11-09",
            "url": "https://example.invalid/complete-name-test"}
        for number, asset in enumerate(catalog["assets"].values()):
            asset.update(name=f"Verified English Test Name {number}", quality="official_reference",
                         source_ids=["synthetic-complete-names"], name_ambiguous=False)
        for reference in catalog["reference_weapons"]:
            asset = catalog["assets"][reference["asset_id"]]
            for key in ("name", "quality", "source_ids", "name_ambiguous"):
                reference[key] = deepcopy(asset[key])
        result = gate.evaluate_documents(catalog, sources)
        self.assertTrue(result["ready"], result["issues"][:3])
        self.assertEqual(result["total_translated"], 1302)
        self.assertEqual(result["total_described"], 0)
        self.assertEqual(result["total_english_covered"], 1302)

    def test_changed_pinned_approval_scope_fails_closed(self):
        altered = dict(gate.INTERNAL_DESCRIPTION_RECORD_HASHES)
        altered["0" * 16] = "a" * 64
        with patch.object(gate, "INTERNAL_DESCRIPTION_RECORD_HASHES", altered):
            self.assert_description_loss(*self.copy(), lost=72)


if __name__ == "__main__":
    unittest.main()
