"""Exact eleven-caption approval, fail-closed coverage and guarded application."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import english_release_gate as gate
from tools import review_internal_descriptions as internal
from tools import review_technical_descriptions as review

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "metadata/policies"


class TechnicalDescriptionGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base_catalog = gate.read_json(ROOT / "plugin/cod_hub/data/catalog.json")
        cls.base_sources = gate.read_json(ROOT / "plugin/cod_hub/data/facts-sources.json")
        for asset in cls.base_catalog["assets"].values():
            asset.pop("technical_description", None)
        cls.base_sources["sources"].pop(review.SOURCE_ID, None)
        cls.manifest = gate.read_json(review.DEFAULT_REVIEW)
        cls.catalog, cls.sources, cls.audit = review.apply_review(cls.base_catalog, cls.base_sources, cls.manifest)
        cls.result = gate.evaluate_documents(cls.catalog, cls.sources)

    def copy(self):
        return deepcopy(self.catalog), deepcopy(self.sources)

    def assert_lost(self, catalog, sources, count=1):
        result = gate.evaluate_documents(catalog, sources)
        self.assertFalse(result["ready"])
        self.assertEqual(result["total_technical_described"], 11 - count)
        return result

    def test_approval_review_source_and_all_exact_caption_records_are_pinned(self):
        manifest = self.manifest
        self.assertEqual(manifest["policy"]["review_status"], "reviewed")
        self.assertEqual(gate.canonical_digest(manifest["policy"]), gate.EXPECTED_TECHNICAL_POLICY_SHA256)
        self.assertEqual(review.canonical_sha256(manifest), review.EXPECTED_MANIFEST_SHA256)
        self.assertEqual(gate.canonical_digest(manifest["records"]), gate.EXPECTED_TECHNICAL_REVIEW_SHA256)
        self.assertEqual(gate.canonical_digest(manifest["source"]), gate.EXPECTED_TECHNICAL_SOURCE_SHA256)
        self.assertEqual(gate.ids_digest(manifest["records"]), gate.EXPECTED_TECHNICAL_IDS_SHA256)
        self.assertFalse(set(manifest["records"]) & set(gate.INTERNAL_DESCRIPTION_RECORD_HASHES))
        for asset_id, row in manifest["records"].items():
            with self.subTest(asset_id=asset_id):
                self.assertEqual(gate.canonical_digest(row), gate.TECHNICAL_DESCRIPTION_RECORD_HASHES[asset_id])
                text = row["technical_description"]["text"]
                self.assertTrue(text.startswith("Technical record \u00b7 "))
                self.assertNotIn("\u00c2", text)
        self.assertNotIn(review.QUALITY, gate.ACCEPTED_QUALITIES)
        self.assertEqual(gate.ACCEPTED_QUALITIES, review.NAME_QUALITIES)

    def test_public_policy_files_have_no_private_paths_or_conversation_fields(self):
        for filename in ("internal-descriptions.json", "technical-descriptions.json"):
            manifest = gate.read_json(EVIDENCE / filename)
            self.assertEqual(manifest["format_version"], 2)
            self.assertEqual(manifest["policy"]["classification"], "separate_descriptions_never_canonical_names")
            def visit(value):
                if isinstance(value, dict):
                    self.assertFalse(set(value) & {"approval", "user_approval", "quote", "authorization"})
                    for item in value.values():
                        visit(item)
                elif isinstance(value, list):
                    for item in value:
                        visit(item)
                elif isinstance(value, str):
                    self.assertNotIn("research-output", value)
                    self.assertNotRegex(value, r"[A-Za-z]:[/\\]")
            visit(manifest)

    def test_public_name_inventory_retains_exact_identity_and_current_hash_joins(self):
        inventory = gate.read_json(ROOT / "metadata/name-inventory.json")
        records = {row["asset_id"]: row for row in inventory["assets"]}
        self.assertEqual(set(records), set(self.base_catalog["assets"]))
        self.assertEqual(gate.ids_digest(records), gate.EXPECTED_ASSET_IDS_SHA256)
        for asset_id, asset in self.base_catalog["assets"].items():
            row = records[asset_id]
            self.assertEqual(set(row), {"asset_id", "internal_ref", "loot_id", "localize_hashes"})
            self.assertEqual(row["internal_ref"], asset.get("internal_ref"))
            self.assertEqual(row["loot_id"], asset.get("loot_id"))
            self.assertTrue(all(isinstance(value, str) and len(value) == 16 and int(value, 16) > 0
                                for value in row["localize_hashes"]))
            self.assertTrue({claim["name_hash"] for claim in asset.get("name_claims", []) if claim.get("name_hash")}
                            <= set(row["localize_hashes"]))

    def test_complete_coverage_preserves_all_original_fields_and_separate_counts(self):
        self.assertTrue(self.result["ready"], self.result["issues"])
        self.assertEqual(self.result["total_translated"], 1216)
        self.assertEqual(self.result["total_described"], 83)
        self.assertEqual(self.result["total_internal_described"], 72)
        self.assertEqual(self.result["total_technical_described"], 11)
        self.assertEqual(self.result["total_english_covered"], 1299)
        self.assertEqual(self.result["counts"]["reference_weapons_described"], 0)
        stripped = deepcopy(self.catalog)
        for asset in stripped["assets"].values():
            asset.pop("technical_description", None)
        self.assertEqual(stripped, self.base_catalog)
        stripped_sources = deepcopy(self.sources)
        stripped_sources["sources"].pop(review.SOURCE_ID)
        self.assertEqual(stripped_sources, self.base_sources)
        self.assertEqual(gate.native_identity_digest(self.catalog["weapons"]), gate.EXPECTED_NATIVE_IDENTITY_SHA256)

    def test_every_caption_is_required_and_loses_only_its_own_coverage(self):
        for asset_id in self.manifest["records"]:
            catalog, sources = self.copy()
            catalog["assets"][asset_id].pop("technical_description")
            with self.subTest(asset_id=asset_id):
                result = self.assert_lost(catalog, sources)
                self.assertIn("asset:" + asset_id, result["missing_ids"])

    def test_changed_caption_quality_language_or_proof_is_rejected(self):
        asset_id = next(iter(self.manifest["records"]))
        changes = [lambda d: d.update(text="Technical record \u00b7 An unapproved effect."),
                   lambda d: d.update(text="Dynamic Attachment"),
                   lambda d: d.update(quality="native_localization"),
                   lambda d: d.update(language="fr"),
                   lambda d: d.update(source_date="2026-02-30"),
                   lambda d: d.update(source_id="forged"),
                   lambda d: d.pop("evidence"),
                   lambda d: d["evidence"].update(asset_id="0" * 16),
                   lambda d: d["evidence"].update(historical_evidence_sha256="a" * 64),
                   lambda d: d["evidence"].update(native_reference={}),
                   lambda d: d["evidence"].update(is_canonical_name=True)]
        for change in changes:
            catalog, sources = self.copy()
            change(catalog["assets"][asset_id]["technical_description"])
            with self.subTest(change=change):
                self.assert_lost(catalog, sources)

    def test_original_base_name_identity_aliases_sources_and_claims_stay_pinned(self):
        asset_id = next(iter(self.manifest["records"]))
        changes = {"name": "An unreviewed label", "quality": "unknown", "kind": "weapon",
                   "internal_ref": "invented_ref", "loot_id": 1, "aliases": ["Invented alias"],
                   "source_ids": ["forged"], "name_claims": [], "name_ambiguous": True}
        for key, value in changes.items():
            catalog, sources = self.copy()
            catalog["assets"][asset_id][key] = value
            with self.subTest(key=key):
                self.assert_lost(catalog, sources)

    def test_policy_source_and_explicit_approval_cannot_be_forged(self):
        for key, value in {"kind": "official_reference", "source_date": "2026-02-30",
                           "input_sha256": "a" * 64, "scope_asset_count": 12,
                           "scope_asset_ids_sha256": "a" * 64, "policy_sha256": "a" * 64,
                           "policy_reference": "metadata/policies/unreviewed.json"}.items():
            catalog, sources = self.copy()
            sources["sources"][review.SOURCE_ID][key] = value
            with self.subTest(key=key):
                self.assert_lost(catalog, sources, 11)
        catalog, sources = self.copy()
        sources["sources"].pop(review.SOURCE_ID)
        self.assert_lost(catalog, sources, 11)

    def test_caption_does_not_repair_missing_or_malformed_original_sources(self):
        original = self.manifest["records"][next(iter(self.manifest["records"]))]["base"]["source_ids"][0]
        for value in (None, {}, {"title": "Forged", "source_date": "bad-date"}):
            catalog, sources = self.copy()
            sources["sources"][original] = value
            with self.subTest(value=value):
                result = self.assert_lost(catalog, sources, 11)
                self.assertTrue(any(issue["code"] == "technical_description_original_provenance" for issue in result["issues"]))
        catalog, sources = self.copy()
        sources["sources"].pop(original)
        result = self.assert_lost(catalog, sources, 11)
        self.assertTrue(any(issue["code"] == "invalid_source_refs" for issue in result["issues"]))

    def test_structural_reference_and_native_scope_errors_are_not_substituted(self):
        for change in (lambda c: c["weapons"]["P01"].update(utility=False),
                       lambda c: c["assets"].pop(next(iter(self.manifest["records"]))),
                       lambda c: c["reference_weapons"][0].update(name="A conflicting reference name")):
            catalog, sources = self.copy()
            change(catalog)
            with self.subTest(change=change):
                result = gate.evaluate_documents(catalog, sources)
                self.assertFalse(result["ready"])
                self.assertTrue(any(issue["code"] in {"native_identity_scope_changed", "required_scope_changed", "reference_name_conflict"} for issue in result["issues"]))

    def test_no_caption_exception_for_other_assets_references_or_player_records(self):
        template = deepcopy(next(iter(self.manifest["records"].values()))["technical_description"])
        other = next(key for key in self.catalog["assets"] if key not in self.manifest["records"] and key not in gate.INTERNAL_DESCRIPTION_RECORD_HASHES)
        catalog, sources = self.copy()
        catalog["assets"][other]["technical_description"] = deepcopy(template)
        result = gate.evaluate_documents(catalog, sources)
        self.assertFalse(result["ready"])
        self.assertTrue(any(issue["id"] == "asset:" + other and issue["code"] == "technical_description_scope" for issue in result["issues"]))
        catalog, sources = self.copy()
        catalog["reference_weapons"][0]["technical_description"] = deepcopy(template)
        result = gate.evaluate_documents(catalog, sources)
        self.assertFalse(result["ready"])
        self.assertTrue(any(issue["id"].startswith("reference:") and issue["code"] == "technical_description_scope" for issue in result["issues"]))
        self.assertTrue(gate._technical_description_issues("player-account", {"technical_description": template}, self.sources["sources"]))

    def test_changed_approval_scope_fails_closed(self):
        altered = dict(gate.TECHNICAL_DESCRIPTION_RECORD_HASHES)
        altered["0" * 16] = "a" * 64
        with patch.object(gate, "TECHNICAL_DESCRIPTION_RECORD_HASHES", altered):
            result = self.assert_lost(*self.copy(), count=11)
        self.assertTrue(any(issue["code"] == "technical_description_policy" for issue in result["issues"]))

    def test_future_genuine_utility_name_precedes_caption_without_double_count(self):
        catalog, sources = self.copy()
        asset_id = "0f8717576adcedb5"
        sources["sources"]["synthetic-utility-name"] = {"kind": "official_reference", "language": "en",
            "title": "Synthetic exact utility name test", "source_date": "2026-11-09", "url": "https://example.invalid/utility"}
        asset = catalog["assets"][asset_id]
        asset.update(name="Verified Utility Test Name", quality="official_reference", source_ids=["synthetic-utility-name"], name_ambiguous=False)
        updated, registered, audit = review.apply_review(catalog, sources, self.manifest)
        self.assertEqual(updated, catalog)
        self.assertEqual(registered, sources)
        self.assertEqual(audit["preserved_future_real_name_ids"], [asset_id])
        result = gate.evaluate_documents(updated, registered)
        self.assertTrue(result["ready"], result["issues"])
        self.assertEqual(result["total_translated"], 1217)
        self.assertEqual(result["total_described"], 82)
        self.assertEqual(result["total_technical_described"], 10)
        self.assertEqual(result["total_english_covered"], 1299)

    def test_all_future_real_names_cover_scope_without_any_descriptions(self):
        catalog, sources = self.copy()
        source_id = "synthetic-real-names"
        sources["sources"][source_id] = {"kind": "official_reference", "language": "en", "title": "Synthetic real names test",
            "source_date": "2026-11-09", "url": "https://example.invalid/names"}
        for index, asset in enumerate(catalog["assets"].values()):
            asset.update(name=f"Verified English Test Name {index}", quality="official_reference", source_ids=[source_id], name_ambiguous=False)
        for reference in catalog["reference_weapons"]:
            asset = catalog["assets"][reference["asset_id"]]
            for key in ("name", "quality", "source_ids", "name_ambiguous"):
                reference[key] = deepcopy(asset[key])
        result = gate.evaluate_documents(catalog, sources)
        self.assertTrue(result["ready"], result["issues"][:3])
        self.assertEqual(result["total_translated"], 1299)
        self.assertEqual(result["total_described"], 0)

    def test_pure_transform_is_idempotent_and_rejects_unreviewed_or_conflicting_inputs(self):
        before_catalog, before_sources = deepcopy(self.base_catalog), deepcopy(self.base_sources)
        updated, sources, audit = review.apply_review(before_catalog, before_sources, self.manifest)
        self.assertEqual(before_catalog, self.base_catalog)
        self.assertEqual(before_sources, self.base_sources)
        self.assertEqual(audit["added"], 11)
        again, registered, audit = review.apply_review(updated, sources, self.manifest)
        self.assertEqual(again, updated)
        self.assertEqual(registered, sources)
        self.assertEqual(audit["added"], 0)
        self.assertEqual(audit["already_present"], 11)
        asset_id = next(iter(self.manifest["records"]))
        for change in (lambda c, s: c["assets"][asset_id].update(loot_id=1),
                       lambda c, s: c["assets"][asset_id].update(name="Changed unverified name"),
                       lambda c, s: c["assets"][asset_id].update(technical_description={"text": "forged"}),
                       lambda c, s: s["sources"].update({review.SOURCE_ID: None}),
                       lambda c, s: s["sources"].update({review.SOURCE_ID: {"title": "forged"}})):
            catalog, provenance = deepcopy(self.base_catalog), deepcopy(self.base_sources)
            change(catalog, provenance)
            with self.subTest(change=change), self.assertRaises(ValueError):
                review.apply_review(catalog, provenance, self.manifest)
        changed = deepcopy(self.manifest)
        changed["policy"]["review_status"] = "unreviewed"
        with self.assertRaises(ValueError):
            review.apply_review(self.base_catalog, self.base_sources, changed)

    def fixture_plugin(self, directory):
        plugin = Path(directory) / "plugin"
        data = plugin / "cod_hub/data"
        data.mkdir(parents=True)
        (data / "catalog.json").write_bytes(internal._encoded(self.base_catalog))
        (data / "facts-sources.json").write_bytes(internal._encoded(self.base_sources))
        return plugin, data

    def test_cli_preview_and_guarded_pair_apply_are_concrete_and_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            plugin, data = self.fixture_plugin(directory)
            originals = {path: path.read_bytes() for path in data.iterdir()}
            audit = review.review_files(plugin)
            self.assertFalse(audit["applied"])
            self.assertEqual({path: path.read_bytes() for path in data.iterdir()}, originals)
            audit = review.review_files(plugin, apply=True)
            self.assertTrue(audit["applied"])
            self.assertTrue(gate.evaluate_release(plugin)["ready"])
            self.assertEqual(review.review_files(plugin, apply=True)["already_present"], 11)

    def test_guarded_pair_rolls_back_first_write_when_second_replacement_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            plugin, data = self.fixture_plugin(directory)
            originals = {path: path.read_bytes() for path in data.iterdir()}
            real_replace = internal.os.replace
            calls = []
            def fail_second(src, dst):
                calls.append(Path(dst).name)
                if len(calls) == 2:
                    raise OSError("synthetic second replacement failure")
                return real_replace(src, dst)
            with patch.object(internal.os, "replace", side_effect=fail_second):
                with self.assertRaises(OSError):
                    review.review_files(plugin, apply=True)
            self.assertEqual(calls, ["facts-sources.json", "catalog.json", "facts-sources.json"])
            self.assertEqual({path: path.read_bytes() for path in data.iterdir()}, originals)


if __name__ == "__main__":
    unittest.main()
