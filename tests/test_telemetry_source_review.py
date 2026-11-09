"""Public numeric source contracts remain dated and explicitly automatic."""
import json
from pathlib import Path
import unittest

from cod_hub import comparison, telemetry


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/official-numeric-candidates.json"


class AutomaticSourceReviewTests(unittest.TestCase):
    def test_five_reviewed_profiles_keep_explicit_primary_sources_and_numeric_facts(self):
        reviewed = json.loads(FIXTURE.read_text(encoding="utf8"))["profiles"]
        self.assertEqual(len(reviewed), 5)
        packaged = telemetry.profiles_for("multiplayer")
        self.assertEqual(set(packaged), {row["asset_id"] for row in reviewed})
        for row in reviewed:
            with self.subTest(asset=row["asset_id"]):
                self.assertTrue(row["eligible_for_theoretical_dps"])
                rate = row["rpm_provenance"]
                self.assertIn(rate["automatic_evidence_phrase"].lower(),
                              {"full-auto", "fully automatic", "sustained automatic fire", "automatic fire"})
                self.assertTrue(rate["source_url"].startswith("https://www.callofduty.com/"))
                self.assertEqual(rate["source_date"], "2026-10-19")
                self.assertEqual(row["provenance"]["source_date"], "2026-11-05")
                self.assertEqual(packaged[row["asset_id"]]["dps"], row["dps"])
                self.assertEqual(comparison.validate_profile(row)["dps"]["fire_mode"], "automatic")

    def test_type_73_review_retains_exact_numeric_rows_and_launch_source(self):
        source = json.loads(FIXTURE.read_text(encoding="utf8"))
        profile = next(p for p in source["profiles"] if p["asset_id"] == "75bd0537aaa182c3")
        self.assertTrue(profile["eligible_for_theoretical_dps"])
        self.assertEqual(profile["rpm_provenance"]["automatic_evidence_phrase"], "sustained automatic fire")
        self.assertEqual(profile["rpm_provenance"]["raw_reported_rate"], "**Fire Rate:** 821 RPM")
        self.assertIn("www.callofduty.com/blog/2026/10/", profile["rpm_provenance"]["source_url"])
        self.assertEqual([(row["min_m"], row["max_m"], row["damage"]["base_profile"])
                          for row in profile["dps"]["damage_ranges"]],
                         [(0, 25.53, 22), (25.53, 46.99, 21), (46.99, None, 19)])
        self.assertEqual(len([p for p in source["profiles"] if p["eligible_for_theoretical_dps"]]), 5)


if __name__ == "__main__":
    unittest.main()
