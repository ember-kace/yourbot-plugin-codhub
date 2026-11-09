"""Release cannot substitute internal IDs for English names or lose evidence."""
import copy
import csv
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools import english_release_gate as gate
from tools import import_english_names as importer

ROOT = Path(__file__).resolve().parents[1]


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


class EnglishReleaseGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_catalog = gate.read_json(ROOT / "plugin/cod_hub/data/catalog.json")
        cls.original_sources = gate.read_json(ROOT / "plugin/cod_hub/data/facts-sources.json")
        # Reconstruct an intentionally partial synthetic snapshot from archived
        # observed labels, so legitimate future production imports do not make
        # tests depend on production remaining incomplete forever.
        cls.partial_catalog = copy.deepcopy(cls.original_catalog)
        for record in cls.partial_catalog["assets"].values():
            record.pop("internal_description", None)
            record.pop("technical_description", None)
            record.update(name="Untranslated synthetic asset", quality="internal", aliases=[],
                          source_ids=["local-item-catalog"], name_ambiguous=False)
            record.pop("name_claims", None)
        observed = gate.read_json(ROOT / "metadata/observed-labels.json")["assets"]
        for asset_id, label in observed.items():
            cls.partial_catalog["assets"][asset_id].update(name=label["preferred"], quality=label["quality"],
                                                        aliases=label["variants"], source_ids=label["source_ids"])
        for reference in cls.partial_catalog["reference_weapons"]:
            original = next(r for r in cls.original_catalog["reference_weapons"] if r["asset_id"] == reference["asset_id"])
            if "codloadout-launch" in original.get("source_ids", []):
                cls.partial_catalog["assets"][reference["asset_id"]].update(
                    name=(original.get("aliases") or [original["name"]])[0], quality="published_fixture",
                    source_ids=["codloadout-launch"])
            asset = cls.partial_catalog["assets"][reference["asset_id"]]
            for key in ["name", "quality", "aliases", "source_ids"]:
                reference[key] = copy.deepcopy(asset[key])
            reference.pop("name_claims", None)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.plugin = self.root / "plugin"
        self.data = self.plugin / "cod_hub/data"
        self.data.mkdir(parents=True)
        self.catalog = copy.deepcopy(self.partial_catalog)
        self.sources = copy.deepcopy(self.original_sources)
        self.inventory = {"assets": []}
        for index, (asset_id, record) in enumerate(self.catalog["assets"].items(), 1):
            self.inventory["assets"].append({"asset_id": asset_id, "internal_ref": record.get("internal_ref"),
                "loot_id": record.get("loot_id"), "localize_hashes": [f"{index:016x}"],
                "status": "encrypted_english_resource"})
        # Synthetic copies explicitly exercise the two unclassified source cases.
        self.inventory["assets"][0].update(localize_hashes=[], status="missing_info_definition")
        self.inventory["assets"][1].update(localize_hashes=[], status="name_field_absent_or_not_localize")
        self.inventory_path = self.root / "inventory.json"
        self.inventory_path.write_bytes(encoded(self.inventory))
        self.write_documents()

    def write_documents(self):
        (self.data / "catalog.json").write_bytes(encoded(self.catalog))
        (self.data / "facts-sources.json").write_bytes(encoded(self.sources))
        (self.data / "schema.json").write_bytes(b'{"do_not_change": true}\n')

    def file_state(self):
        return {p.name: p.read_bytes() for p in self.data.iterdir() if p.is_file()}

    def run_import(self, path, **kwargs):
        options = {"language": "en", "quality": "native_localization", "source_id": "synthetic-english-test",
                   "source_title": "Synthetic test fixture, not production evidence", "source_date": "2026-11-09"}
        options.update(kwargs)
        return importer.import_names(self.plugin, path, self.inventory_path, **options)

    def input_json(self, value):
        path = self.root / "names.json"
        path.write_bytes(encoded(value))
        return path

    def input_csv(self, rows, headers=("asset_id", "name_hash", "name")):
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
        path = self.root / "names.csv"
        path.write_text(stream.getvalue(), encoding="utf-8", newline="")
        return path

    def review_file(self, input_path, decisions, filename="review.json", status="approved"):
        path = self.root / filename
        path.write_bytes(encoded({"status": status, "language": "en", "input_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
                                  "reviewed_by": "Synthetic evidence review, test only", "reviewed_on": "2026-11-09", "decisions": decisions}))
        return path

    def preference(self, asset_id, name_hash, incoming, decision):
        asset = self.catalog["assets"][asset_id]
        return {"asset_id": asset_id, "name_hash": name_hash, "raw_name": incoming, "display_name": incoming,
                "current_name": asset["name"], "current_quality": asset["quality"], "decision": decision,
                "reason": "Synthetic per-asset evidence comparison", "evidence": "Temporary test fixture, not production evidence."}

    def untranslated(self):
        return next(r for r in self.inventory["assets"][2:] if self.catalog["assets"][r["asset_id"]]["quality"] == "internal")

    def complete_fixture(self):
        self.sources["sources"]["synthetic-complete"] = {
            "title": "Synthetic complete test fixture", "kind": "official_reference",
            "source_date": "2026-11-09", "url": "https://example.invalid/synthetic-test", "language": "en"}
        for index, record in enumerate(self.catalog["assets"].values()):
            record.update(name="Verified English Name " + str(index), quality="official_reference",
                          name_ambiguous=False, source_ids=["synthetic-complete"])
        for reference in self.catalog["reference_weapons"]:
            asset = self.catalog["assets"][reference["asset_id"]]
            for key in ["name", "quality", "source_ids"]:
                reference[key] = copy.deepcopy(asset[key])
        self.write_documents()

    def test_partial_fixture_is_blocked_and_reports_all_required_records(self):
        result = gate.evaluate_release(self.plugin)
        self.assertFalse(result["ready"])
        self.assertEqual(result["required"], 1299)
        self.assertEqual(result["counts"]["assets_required"], 1264)
        self.assertEqual(result["counts"]["reference_weapons_required"], 35)
        self.assertEqual(len(result["missing_ids"]), result["required"] - result["total_translated"])
        for row in self.inventory["assets"][:2]:
            self.assertIn("asset:" + row["asset_id"], result["missing_ids"])

    def test_complete_synthetic_scope_passes_and_utility_or_reference_removal_cannot(self):
        self.complete_fixture()
        self.assertTrue(gate.evaluate_release(self.plugin)["ready"])
        utility = self.catalog["weapons"]["P01"]["asset_id"]
        del self.catalog["assets"][utility]
        self.catalog["reference_weapons"].pop()
        self.write_documents()
        result = gate.evaluate_release(self.plugin)
        self.assertFalse(result["ready"])
        self.assertEqual(result["required"], 1299)
        self.assertIn("required_scope_changed", {i["code"] for i in result["issues"]})

    def test_placeholder_internal_source_and_reference_conflicts_are_blocked(self):
        self.complete_fixture()
        selected = next(iter(self.catalog["assets"]))
        self.catalog["assets"][selected]["name"] = "Untranslated attachment ID 4"
        self.catalog["reference_weapons"][0]["name"] = "Conflicting reference name"
        self.sources["sources"]["synthetic-complete"]["source_date"] = "not-a-date"
        self.write_documents()
        result = gate.evaluate_release(self.plugin)
        self.assertFalse(result["ready"])
        codes = {i["code"] for i in result["issues"]}
        self.assertTrue({"unreadable_name", "missing_name_provenance", "reference_name_conflict"} <= codes)
        record = self.partial_catalog["assets"][selected]
        self.assertIsNotNone(gate.readable_name_issue(record["name"], record))

    def test_empty_removed_swapped_or_reclassified_native_mappings_cannot_pass(self):
        self.complete_fixture()
        baseline = copy.deepcopy(self.catalog)
        def empty(catalog):
            catalog["weapons"] = {}
        def remove_weapon(catalog):
            del catalog["weapons"]["A01"]
        def remove_slot(catalog):
            del catalog["weapons"]["A01"]["slots"]["barrel"]
        def remove_id(catalog):
            del catalog["weapons"]["A01"]["slots"]["barrel"]["ids"]["1"]
        def reassign_id(catalog):
            slot = catalog["weapons"]["A01"]["slots"]["barrel"]["ids"]
            slot["1"]["asset_id"] = slot["2"]["asset_id"]
        def reclassify_utility(catalog):
            catalog["weapons"]["A01"]["utility"] = True
        def erase_reserved_position(catalog):
            catalog["weapons"]["A01"]["slots"]["magazine"]["reserved_ids"] = []
        for mutate in [empty, remove_weapon, remove_slot, remove_id, reassign_id, reclassify_utility, erase_reserved_position]:
            with self.subTest(change=mutate.__name__):
                changed = copy.deepcopy(baseline)
                mutate(changed)
                result = gate.evaluate_documents(changed, self.sources)
                self.assertFalse(result["ready"])
                self.assertIn("native_identity_scope_changed", {i["code"] for i in result["issues"]})

    def test_partial_hash_import_is_dry_by_default_and_exact(self):
        row = self.untranslated()
        path = self.input_json({row["localize_hashes"][0].upper(): "Readable Test Grip", "ffffffffffffffff": "Unrelated UI text"})
        before = self.file_state()
        result = self.run_import(path)
        self.assertFalse(result["applied"])
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["targeted_assets"], 1)
        self.assertEqual(result["unmatched_name_hashes"], 1)
        self.assertEqual(result["release_after"]["total_translated"], result["release_before"]["total_translated"] + 1)
        self.assertFalse(result["release_after"]["ready"])
        self.assertEqual(before, self.file_state())

    def test_one_exact_hash_fans_out_only_to_its_inventory_assets(self):
        rows = [r for r in self.inventory["assets"][2:] if self.catalog["assets"][r["asset_id"]]["quality"] == "internal"][:2]
        rows[1]["localize_hashes"] = list(rows[0]["localize_hashes"])
        self.inventory_path.write_bytes(encoded(self.inventory))
        result = self.run_import(self.input_json({rows[0]["localize_hashes"][0]: "Shared Readable English Grip"}))
        self.assertEqual({r["asset_id"] for r in result["changes"]}, {r["asset_id"] for r in rows})
        self.assertEqual(result["release_after"]["total_translated"], result["release_before"]["total_translated"] + 2)

    def test_apply_changes_only_name_metadata_and_adds_dated_source_without_overwrites(self):
        row = self.untranslated()
        path = self.input_json({row["localize_hashes"][0]: "Readable Test Grip"})
        old_catalog, old_sources = copy.deepcopy(self.catalog), copy.deepcopy(self.sources)
        result = self.run_import(path, apply=True)
        self.assertTrue(result["applied"])
        current = gate.read_json(self.data / "catalog.json")
        sources = gate.read_json(self.data / "facts-sources.json")
        source = sources["sources"].pop("synthetic-english-test")
        self.assertEqual(sources["sources"], old_sources["sources"])
        for key in set(old_sources) - {"sources", "coverage", "limits"}:
            self.assertEqual(sources[key], old_sources[key])
        self.assertEqual(source["source_date"], "2026-11-09")
        self.assertEqual(source["input_sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        allowed = {"name", "quality", "aliases", "source_ids", "name_claims"}
        for asset_id, asset in current["assets"].items():
            original = old_catalog["assets"][asset_id]
            self.assertEqual({k: v for k, v in asset.items() if k not in allowed},
                             {k: v for k, v in original.items() if k not in allowed})
            if asset_id != row["asset_id"]:
                self.assertEqual(asset, original)
        self.assertEqual(current["snapshot"], old_catalog["snapshot"])
        self.assertEqual(current["weapons"], old_catalog["weapons"])
        self.assertEqual(current["reference_weapons"], old_catalog["reference_weapons"])
        self.assertEqual((self.data / "schema.json").read_bytes(), b'{"do_not_change": true}\n')
        record = current["assets"][row["asset_id"]]
        self.assertEqual(record["quality"], "native_localization")
        self.assertEqual(record["name_claims"][0]["name_hash"], row["localize_hashes"][0])
        self.assertTrue(sources["limits"]["english_localization_decrypted"])
        self.assertFalse(sources["limits"]["complete_readable_english_names"])
        self.assertEqual(sources["coverage"], current["coverage"])
        self.assertEqual(current["coverage"]["native_english_claim_assets"], 1)

    def test_complete_csv_import_covers_no_hash_assets_and_reference_copies(self):
        rows = []
        for index, (asset_id, asset) in enumerate(self.catalog["assets"].items()):
            name = asset["name"] if asset["quality"] in gate.ACCEPTED_QUALITIES else "Verified English Name " + str(index)
            rows.append({"asset_id": asset_id, "name_hash": "", "name": name})
        result = self.run_import(self.input_csv(rows), quality="official_reference", source_url="https://example.invalid/test-catalog", apply=True)
        self.assertTrue(result["release_after"]["ready"])
        self.assertEqual(result["release_after"]["total_translated"], 1299)
        self.assertTrue(gate.evaluate_release(self.plugin)["ready"])
        current = gate.read_json(self.data / "catalog.json")
        for reference in current["reference_weapons"]:
            self.assertEqual(reference["name"], current["assets"][reference["asset_id"]]["name"])

    def test_user_capture_conflict_aborts_entire_apply_and_preserves_all_sources(self):
        captured = next(a for a, r in self.catalog["assets"].items() if r["quality"] == "user_capture")
        row = self.untranslated()
        path = self.input_csv([{"asset_id": row["asset_id"], "name_hash": "", "name": "New Readable Grip"},
                               {"asset_id": captured, "name_hash": "", "name": "Different Captured Name"}])
        before = self.file_state()
        with self.assertRaisesRegex(ValueError, "requires review"):
            self.run_import(path, quality="official_reference", source_url="https://example.invalid/test", apply=True)
        self.assertEqual(before, self.file_state())

    def test_case_only_capture_variant_keeps_preferred_name_and_capture_quality(self):
        asset_id = next(a for a, r in self.catalog["assets"].items() if r["quality"] == "user_capture")
        inventory = next(r for r in self.inventory["assets"] if r["asset_id"] == asset_id)
        original = self.catalog["assets"][asset_id]
        result = self.run_import(self.input_json({inventory["localize_hashes"][0]: original["name"].lower()}), apply=True)
        current = gate.read_json(self.data / "catalog.json")["assets"][asset_id]
        self.assertEqual(current["name"], original["name"])
        self.assertEqual(current["quality"], "user_capture")
        self.assertTrue(set(original["source_ids"]) <= set(current["source_ids"]))
        self.assertEqual(result["release_after"]["total_translated"], result["release_before"]["total_translated"])

    def test_native_conflict_dry_run_reports_all_and_review_preserves_both_named_claims(self):
        selected = next(r for r in self.inventory["assets"][2:] if self.catalog["assets"][r["asset_id"]]["quality"] == "published_fixture")
        asset_id, name_hash = selected["asset_id"], selected["localize_hashes"][0]
        incoming = "Reviewed Native English Optic"
        path = self.input_json({name_hash: incoming})
        old = copy.deepcopy(self.catalog["assets"][asset_id])
        before = self.file_state()
        preview = self.run_import(path)
        self.assertFalse(preview["can_apply"])
        self.assertEqual(preview["unresolved_conflicts"], [asset_id])
        self.assertEqual(before, self.file_state())
        reviewed = self.review_file(path, [self.preference(asset_id, name_hash, incoming, "prefer_native")])
        result = self.run_import(path, review_path=reviewed, apply=True)
        self.assertTrue(result["can_apply"])
        current = gate.read_json(self.data / "catalog.json")["assets"][asset_id]
        self.assertEqual(current["name"], incoming)
        self.assertEqual(current["quality"], "native_localization")
        self.assertTrue({old["name"], incoming} <= set(current["aliases"]))
        self.assertTrue({old["name"], incoming} <= {claim["name"] for claim in current["name_claims"]})
        self.assertTrue(set(old["source_ids"]) <= set(current["source_ids"]))

    def test_conflicting_native_capture_may_be_an_alias_but_never_replace_capture(self):
        asset_id = next(a for a, r in self.catalog["assets"].items() if r["quality"] == "user_capture")
        selected = next(r for r in self.inventory["assets"] if r["asset_id"] == asset_id)
        name_hash = selected["localize_hashes"][0]
        incoming = "Different Native English Grip"
        path = self.input_json({name_hash: incoming})
        before = self.file_state()
        decision = self.preference(asset_id, name_hash, incoming, "prefer_native")
        with self.assertRaisesRegex(ValueError, "User captures cannot be overwritten"):
            self.run_import(path, review_path=self.review_file(path, [decision]), apply=True)
        self.assertEqual(before, self.file_state())
        decision["decision"] = "keep_verified"
        self.run_import(path, review_path=self.review_file(path, [decision]), apply=True)
        current = gate.read_json(self.data / "catalog.json")["assets"][asset_id]
        self.assertEqual(current["name"], self.catalog["assets"][asset_id]["name"])
        self.assertEqual(current["quality"], "user_capture")
        self.assertIn(incoming, current["aliases"])
        self.assertIn(incoming, {claim["name"] for claim in current["name_claims"]})

    def test_exact_normalization_keeps_raw_text_and_stale_or_draft_decisions_cannot_write(self):
        row = self.untranslated()
        name_hash = row["localize_hashes"][0]
        raw, display = "^+Readable Apex^7\n", "Readable Apex"
        path = self.input_json({"language": "en", "source_image_sha256": "a" * 64, "method": "Synthetic test only", "names": {name_hash: raw}})
        preview = self.run_import(path)
        self.assertFalse(preview["can_apply"])
        self.assertTrue(preview["input_issues"])
        decision = {"name_hash": name_hash, "raw_name": raw, "display_name": display,
                    "reason": "Synthetic exact presentation normalization", "evidence": "Temporary test-only trace."}
        before = self.file_state()
        draft = self.review_file(path, [decision], "normalize.json", status="draft_not_approved")
        with self.assertRaisesRegex(ValueError, "status approved"):
            self.run_import(path, normalization_path=draft, apply=True)
        decision["raw_name"] = "stale raw value"
        with self.assertRaisesRegex(ValueError, "stale"):
            self.run_import(path, normalization_path=self.review_file(path, [decision], "normalize.json"), apply=True)
        self.assertEqual(before, self.file_state())
        decision["raw_name"] = raw
        normalized = self.review_file(path, [decision], "normalize.json")
        self.run_import(path, normalization_path=normalized, apply=True)
        current = gate.read_json(self.data / "catalog.json")["assets"][row["asset_id"]]
        self.assertEqual(current["name"], display)
        self.assertEqual(current["name_claims"][0]["raw_name"], raw)
        self.assertEqual(current["name_claims"][0]["normalization"]["review_sha256"], hashlib.sha256(normalized.read_bytes()).hexdigest())
        source = gate.read_json(self.data / "facts-sources.json")["sources"]["synthetic-english-test"]
        self.assertEqual(source["input_provenance"]["source_image_sha256"], "a" * 64)

    def test_preference_decision_binds_current_and_input_names_exactly(self):
        selected = next(r for r in self.inventory["assets"][2:] if self.catalog["assets"][r["asset_id"]]["quality"] == "published_fixture")
        asset_id, name_hash = selected["asset_id"], selected["localize_hashes"][0]
        path = self.input_json({name_hash: "Reviewed Native English Optic"})
        decision = self.preference(asset_id, name_hash, "Reviewed Native English Optic", "prefer_native")
        decision["current_name"] = "Stale preferred name"
        before = self.file_state()
        with self.assertRaisesRegex(ValueError, "stale"):
            self.run_import(path, review_path=self.review_file(path, [decision]), apply=True)
        self.assertEqual(before, self.file_state())

    def test_conflicting_duplicate_or_wrong_asset_hash_never_writes(self):
        row = self.untranslated()
        other = self.inventory["assets"][0]
        for rows in [[{"asset_id": row["asset_id"], "name_hash": "", "name": "Readable One"},
                      {"asset_id": row["asset_id"], "name_hash": "", "name": "Readable Two"}],
                     [{"asset_id": other["asset_id"], "name_hash": row["localize_hashes"][0], "name": "Readable One"}]]:
            with self.subTest(rows=rows):
                before = self.file_state()
                with self.assertRaises(ValueError):
                    self.run_import(self.input_csv(rows), quality="official_reference", source_url="https://example.invalid/test", apply=True)
                self.assertEqual(before, self.file_state())

    def test_invalid_language_utf8_control_placeholder_size_and_source_are_rejected(self):
        row = self.untranslated()
        path = self.input_json({row["localize_hashes"][0]: "Readable Test Grip"})
        before = self.file_state()
        for options in [{"language": "fr"}, {"source_date": "yesterday"}, {"source_id": "community-builds"}]:
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.run_import(path, apply=True, **options)
        for name in ["Unknown attachment", "rex_internal_identifier", "Invisible\u200bName", "Line\nBreak", "\nLeading Control"]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.run_import(self.input_json({row["localize_hashes"][0]: name}), apply=True)
        path.write_bytes(b'\xff\xfe')
        with self.assertRaises(UnicodeError):
            self.run_import(path, apply=True)
        path = self.input_json({row["localize_hashes"][0]: "Readable Test Grip"})
        with patch.object(importer, "MAX_JSON_BYTES", 10), self.assertRaisesRegex(ValueError, "32 MiB"):
            self.run_import(path, apply=True)
        self.assertEqual(before, self.file_state())

    def test_missing_inventory_hash_requires_asset_evidence_instead_of_native_claim(self):
        row = self.inventory["assets"][0]
        path = self.input_csv([{"asset_id": row["asset_id"], "name_hash": "", "name": "Readable Explicit Asset Name"}])
        with self.assertRaisesRegex(ValueError, "inventoried name hash"):
            self.run_import(path, apply=True)
        result = self.run_import(path, quality="user_capture")
        self.assertEqual(result["changes"][0]["inventory_status"], "missing_info_definition")
        self.assertFalse(result["release_after"]["ready"])

    def test_native_claim_requires_matching_evidence_date_and_source_hash(self):
        row = self.untranslated()
        self.run_import(self.input_json({row["localize_hashes"][0]: "Readable Test Grip"}), apply=True)
        current = gate.read_json(self.data / "catalog.json")
        sources = gate.read_json(self.data / "facts-sources.json")
        current["assets"][row["asset_id"]]["name_claims"][0]["source_date"] = "2026-01-01"
        result = gate.evaluate_documents(current, sources)
        self.assertIn({"id": "asset:" + row["asset_id"], "code": "missing_exact_name_claim",
                       "detail": "Native localization needs an English claim linking this name to its source."}, result["issues"])
        sources["sources"]["synthetic-english-test"].pop("input_sha256")
        result = gate.evaluate_documents(current, sources)
        self.assertIn("missing_name_provenance", {i["code"] for i in result["issues"] if i["id"] == "asset:" + row["asset_id"]})

    def test_gate_cli_returns_nonzero_for_missing_names_and_zero_only_when_complete(self):
        command = [sys.executable, str(ROOT / "tools/english_release_gate.py"), "--plugin", str(self.plugin)]
        first = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(first.returncode, 1)
        self.assertFalse(json.loads(first.stdout)["ready"])
        self.complete_fixture()
        complete = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(complete.returncode, 0)
        self.assertTrue(json.loads(complete.stdout)["ready"])

    def test_unreadable_documents_are_a_machine_readable_block(self):
        (self.data / "catalog.json").write_bytes(b'{"assets":')
        result = gate.evaluate_release(self.plugin)
        self.assertFalse(result["ready"])
        self.assertEqual(result["issues"][0]["code"], "unreadable_documents")


if __name__ == "__main__":
    unittest.main()
