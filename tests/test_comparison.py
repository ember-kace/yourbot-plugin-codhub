"""Comparison invariants; all ballistic profiles here are synthetic test data."""
from copy import deepcopy
import math
import json
from pathlib import Path
import unittest

from cod_hub import catalog, comparison


FIVE = "A01-42J19-BU11"
FOUR = "A01-A11NP-B11"
CHANGED = "A01-9YGBJ-D11"
HYEON = "A09-43QCD-D4HTW-VI11"
OFFICIAL_CANDIDATES = Path(__file__).resolve().parents[1] / "tests/fixtures/official-numeric-candidates.json"


def profile(selection="A01", mode="multiplayer", *, damage=30, rpm=600):
    subject = comparison.resolve_subject(selection)
    return {
        "schema_version": 1, "game": "mw4", "mode": mode, "asset_id": subject["weapon"]["asset_id"],
        "variant": {"kind": "build", "code": subject["code"]} if subject["code"] else {"kind": "base"},
        "provenance": {"source_url": "https://example.invalid/synthetic-comparison-fixture", "source_date": "2026-11-09",
                       "patch": "Synthetic test patch; not production evidence", "method": "Synthetic unit test only"},
        "dps": {"fire_mode": "automatic", "rpm": rpm, "projectiles_per_shot": 1,
                "damage_ranges": [{"min_m": 0, "max_m": 20, "damage": {"upper_torso": damage, "head": damage*2}},
                                  {"min_m": 20, "max_m": None, "damage": {"upper_torso": damage-10, "head": damage*2-10}}]},
        "recoil": {"unit": "degrees", "statistic": "single_trial", "sample_count": 1,
                   "condition": "Synthetic ADS standing fixture",
                   "points": [{"shot": 1, "x": 0, "y": 0.1}, {"shot": 2, "x": -0.05, "y": 0.3}]},
        "sway": {"unit": "degrees", "stance": "standing", "condition": "Synthetic ADS fixture",
                 "points": [{"time_s": 0, "x": 0, "y": 0.01}, {"time_s": 0.5, "x": 0.03, "y": 0}]},
    }


def profile_map(*selections, mode="multiplayer"):
    return {comparison.resolve_subject(selection)["key"]: profile(selection, mode) for selection in selections}


class ComparisonTests(unittest.TestCase):
    def test_exact_names_prefixes_assets_and_canonical_codes(self):
        weapon = catalog.get_weapon("A01")
        for query in ("A01", "kastov 762", weapon["asset_id"]):
            subject = comparison.resolve_subject(query)
            self.assertEqual(subject["kind"], "weapon")
            self.assertEqual(subject["key"], weapon["asset_id"])
            self.assertIsNone(subject["code"])
        subject = comparison.resolve_subject(FIVE.lower())
        self.assertEqual(subject["code"], FIVE)
        self.assertEqual(subject["kind"], "build")
        self.assertEqual(len(subject["attachments"]), 5)
        for invalid in (None, "", "Kastov", "A01-42J19-BU12", "P01-111", "A01\n-111", "x"*257):
            with self.subTest(query=invalid), self.assertRaises(ValueError):
                comparison.resolve_subject(invalid)

    def test_gun_base_fields_are_dated_and_no_performance_winner_is_invented(self):
        result = comparison.compare("A01", "A05")
        self.assertFalse(result["same_weapon"])
        rows = {row["key"]: row for row in result["base_stats"]["rows"]}
        self.assertEqual(rows["rpm"]["left"], 600)
        self.assertEqual(rows["rpm"]["right"], 810)
        self.assertEqual(rows["rpm"]["delta"], -210)
        self.assertEqual(rows["rpm"]["left_date"], "2026-10-24")
        self.assertIsNone(rows["caliber"]["delta"])
        self.assertFalse(result["base_stats"]["mode_specific"])
        self.assertFalse(result["base_stats"]["attachment_adjusted"])
        self.assertNotIn("winner", result)
        self.assertTrue(all(not metric["available"] and metric["series"] == [] for metric in result["metrics"].values()))

    def test_missing_launch_values_stay_missing(self):
        result = comparison.compare("A02", "A01", mode="DMZ")
        self.assertEqual(result["mode"], "dmz")
        rows = {row["key"]: row for row in result["base_stats"]["rows"]}
        self.assertIsNone(rows["rpm"]["left"])
        self.assertIsNone(rows["rpm"]["delta"])
        self.assertIn("Mode-specific", result["base_stats"]["note"])

    def test_removed_attachment_control_pair_and_changed_muzzle_pair(self):
        removed = comparison.compare(FIVE, FOUR)["attachment_diff"]
        self.assertEqual(len(removed["common"]), 4)
        self.assertEqual([item["slot"] for item in removed["left_only"]], ["underbarrel"])
        self.assertEqual(removed["changed"], [])
        changed = comparison.compare(FOUR, CHANGED)["attachment_diff"]
        self.assertEqual(len(changed["common"]), 3)
        self.assertEqual(changed["changed"][0]["slot"], "muzzle")
        self.assertNotEqual(changed["changed"][0]["left"]["asset_id"], changed["changed"][0]["right"]["asset_id"])

    def test_different_weapons_never_equate_native_attachment_indexes(self):
        result = comparison.compare(FIVE, HYEON)
        diff = result["attachment_diff"]
        self.assertFalse(diff["comparable"])
        self.assertEqual(diff["common"], [])
        self.assertEqual(len(diff["left_only"]), 5)
        self.assertEqual(len(diff["right_only"]), 6)
        self.assertEqual(result["left"]["code"], FIVE)
        self.assertEqual(result["right"]["code"], HYEON)

    def test_build_reference_values_never_apply_attachment_effects(self):
        result = comparison.compare("A01", FIVE)
        self.assertTrue(result["same_weapon"])
        self.assertTrue(all(row["delta"] in (0, None) for row in result["base_stats"]["rows"]))
        telemetry = profile_map("A01")
        result = comparison.compare("A01", FIVE, profiles=telemetry)
        self.assertTrue(result["metrics"]["dps"]["left_available"])
        self.assertFalse(result["metrics"]["dps"]["right_available"])
        self.assertIn("exact build", result["metrics"]["dps"]["reason"])

    def test_automatic_dps_uses_explicit_projectile_damage_and_half_open_ranges(self):
        source = profile()
        source["dps"]["projectiles_per_shot"] = 2
        self.assertEqual(comparison.damage_at_distance(source, 19.999), 30)
        self.assertEqual(comparison.damage_at_distance(source, 20), 20)
        curve = comparison.dps_curve(source)
        self.assertEqual(curve["points"], [{"distance_m": 0, "dps": 600}, {"distance_m": 20, "dps": 600},
                                         {"distance_m": 20, "dps": 400}, {"distance_m": 100, "dps": 400}])
        self.assertIn("reloads", curve["model"])
        self.assertEqual(comparison.dps_curve(source, "head")["points"][0]["dps"], 1200)

    def test_finite_measurement_coverage_is_never_extrapolated(self):
        source = profile()
        source["dps"]["damage_ranges"][-1]["max_m"] = 50
        curve = comparison.dps_curve(source, max_distance_m=100)
        self.assertEqual(curve["max_distance_m"], 50)
        self.assertFalse(curve["segments"][-1]["includes_end"])
        with self.assertRaises(ValueError):
            comparison.damage_at_distance(source, 50)

    def test_scoped_synthetic_profiles_enable_only_matching_metrics(self):
        profiles = profile_map("A01", "A05")
        result = comparison.compare("A01", "A05", profiles=profiles)
        for metric in result["metrics"].values():
            self.assertTrue(metric["available"])
            self.assertEqual(len(metric["series"]), 2)
            self.assertIn("Synthetic", metric["series"][0]["provenance"]["patch"])
        self.assertFalse(any("remain unavailable" in note for note in result["notes"]))
        result["metrics"]["recoil"]["series"][0]["points"][0]["y"] = 999
        self.assertEqual(next(iter(profiles.values()))["recoil"]["points"][0]["y"], 0.1)

    def test_composite_dated_sources_and_generic_body_region_are_preserved(self):
        profiles = profile_map("A01", "A05")
        for source in profiles.values():
            source["provenance"]["components"] = [
                {"metric": "damage", "source_url": "https://example.invalid/synthetic-damage", "source_date": "2026-11-05"},
                {"metric": "rpm", "source_url": "https://example.invalid/synthetic-rpm", "source_date": "2026-10-24",
                 "note": "Dated launch reference, not a current measurement"}]
            source["provenance"]["caveats"] = ["Synthetic fixtures only"]
            for damage in source["dps"]["damage_ranges"]:
                damage["damage"]["body"] = damage["damage"]["upper_torso"]
        result = comparison.compare("A01", "A05", profiles=profiles, hit_location="body")
        self.assertTrue(result["metrics"]["dps"]["available"])
        provenance = result["metrics"]["dps"]["series"][0]["provenance"]
        self.assertEqual(provenance["components"][1]["source_date"], "2026-10-24")
        self.assertEqual(provenance["caveats"], ["Synthetic fixtures only"])
        self.assertTrue(any("separately dated" in note for note in result["notes"]))

    def test_five_source_reviewed_automatic_candidates_preserve_unknown_base_region(self):
        data = json.loads(OFFICIAL_CANDIDATES.read_text(encoding="utf8"))
        profiles = {row["asset_id"]: row for row in data["profiles"] if row["eligible_for_theoretical_dps"]}
        self.assertEqual(len(profiles), 5)
        for source in profiles.values():
            validated = comparison.validate_profile(source, mode="multiplayer")
            self.assertEqual(validated["dps"]["fire_mode"], "automatic")
            self.assertIn("base_profile", validated["dps"]["damage_ranges"][0]["damage"])
        result = comparison.compare("A01", "A05", profiles=profiles, hit_location="base_profile")
        metric = result["metrics"]["dps"]
        self.assertTrue(metric["available"])
        self.assertEqual(metric["series"][0]["points"][0]["dps"], 300)
        self.assertEqual(metric["series"][1]["points"][0]["dps"], 310.5)
        self.assertIn("region unspecified", metric["series"][0]["hit_location_label"])
        self.assertIn("no hit-location multiplier", metric["series"][0]["region_note"])
        # The official M4 table does not publish an upper-torso multiplier.
        self.assertFalse(comparison.compare("A01", "A05", profiles=profiles, hit_location="upper_torso")["metrics"]["dps"]["available"])
        for mode in ("dmz", "warzone"):
            self.assertFalse(comparison.compare("A01", "A05", profiles=profiles, mode=mode, hit_location="base_profile")["metrics"]["dps"]["available"])

    def test_profile_mode_weapon_patch_and_build_scope_cannot_be_reused(self):
        profiles = profile_map("A01", "A05")
        left_key = comparison.resolve_subject("A01")["key"]
        right_key = comparison.resolve_subject("A05")["key"]
        profiles[left_key]["mode"] = "dmz"
        result = comparison.compare("A01", "A05", profiles=profiles)
        self.assertFalse(result["metrics"]["dps"]["available"])
        self.assertIn("mode", result["metrics"]["dps"]["reason"])
        profiles[left_key] = profile("A01")
        profiles[right_key]["provenance"]["patch"] = "Different synthetic patch"
        self.assertIn("different balance patches", comparison.compare("A01", "A05", profiles=profiles)["metrics"]["dps"]["reason"])
        wrong_build = profile(FIVE)
        with self.assertRaises(ValueError):
            comparison.validate_profile(wrong_build, subject=comparison.resolve_subject(FOUR))
        wrong_weapon = profile("A05")
        with self.assertRaises(ValueError):
            comparison.validate_profile(wrong_weapon, subject=comparison.resolve_subject("A01"))

    def test_recoil_and_sway_are_distinct_measured_metrics(self):
        profiles = profile_map("A01", "A05")
        right_key = comparison.resolve_subject("A05")["key"]
        profiles[right_key]["recoil"]["unit"] = "milliradians"
        result = comparison.compare("A01", "A05", profiles=profiles)
        self.assertFalse(result["metrics"]["recoil"]["available"])
        self.assertTrue(result["metrics"]["sway"]["available"])
        self.assertTrue(result["metrics"]["dps"]["available"])
        del profiles[right_key]["sway"]
        self.assertFalse(comparison.compare("A01", "A05", profiles=profiles)["metrics"]["sway"]["available"])

    def test_invalid_profile_values_cannot_become_curves(self):
        cases = [
            lambda p: p.update(schema_version=True),
            lambda p: p["dps"].update(rpm=math.nan),
            lambda p: p["dps"].update(rpm=True),
            lambda p: p["dps"].update(fire_mode="burst"),
            lambda p: p["dps"].update(projectiles_per_shot=0),
            lambda p: p["dps"]["damage_ranges"][1].update(min_m=19),
            lambda p: p["dps"]["damage_ranges"][0].update(max_m=None),
            lambda p: p["dps"]["damage_ranges"][0]["damage"].update(upper_torso=math.inf),
            lambda p: p["recoil"]["points"][1].update(shot=3),
            lambda p: p["recoil"].update(sample_count=2),
            lambda p: p["sway"]["points"][1].update(time_s=0),
            lambda p: p["provenance"].update(source_url="http://example.invalid/test"),
            lambda p: p["provenance"].update(source_date="2026-02-30"),
            lambda p: p["variant"].update(code=FIVE),
        ]
        for edit in cases:
            source = profile()
            edit(source)
            with self.subTest(profile=source), self.assertRaises(ValueError):
                comparison.validate_profile(source)

    def test_invalid_telemetry_never_breaks_base_comparison_or_mutates_catalog(self):
        before = deepcopy(catalog.get_weapon("A01"))
        profiles = profile_map("A01", "A05")
        profiles[comparison.resolve_subject("A01")["key"]]["dps"]["rpm"] = float("inf")
        result = comparison.compare("A01", "A05", profiles=profiles)
        self.assertTrue(result["base_stats"]["rows"])
        self.assertFalse(result["metrics"]["dps"]["available"])
        result["left"]["weapon"]["name"] = "Caller mutation"
        self.assertEqual(catalog.get_weapon("A01"), before)
        for bad_mode in ("ranked", "", None):
            with self.assertRaises(ValueError):
                comparison.compare("A01", "A05", bad_mode)


if __name__ == "__main__":
    unittest.main()
