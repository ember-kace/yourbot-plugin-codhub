"""Production numeric facts are dated, scoped, bounded and caller-independent."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cod_hub import comparison, telemetry


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        telemetry.clear_cache()
        self.addCleanup(telemetry.clear_cache)

    def test_reviewed_production_scope_and_missing_modes(self):
        profiles = telemetry.profiles_for("multiplayer")
        self.assertEqual(len(profiles), 5)
        self.assertEqual(telemetry.profiles_for("dmz"), {})
        self.assertEqual(telemetry.profiles_for("warzone"), {})
        for profile in profiles.values():
            self.assertNotIn("recoil", profile)
            self.assertNotIn("sway", profile)
            self.assertEqual({c["source_date"] for c in profile["provenance"]["components"]}, {"2026-11-05", "2026-10-19"})
        profiles["54efea11f28407ea"]["dps"]["rpm"] = 99999
        self.assertEqual(telemetry.profiles_for("multiplayer")["54efea11f28407ea"]["dps"]["rpm"], 810)
        result = comparison.compare("A01", "A05", profiles=telemetry.profiles_for("multiplayer"), hit_location="base_profile")
        self.assertEqual([s["points"][0]["dps"] for s in result["metrics"]["dps"]["series"]], [300, 310.5])

    def test_type_73_explicit_official_automatic_fire_adds_dated_base_profile(self):
        profile = telemetry.profiles_for("multiplayer")["75bd0537aaa182c3"]
        self.assertEqual(profile["variant"], {"kind": "base"})
        self.assertEqual(profile["dps"]["fire_mode"], "automatic")
        self.assertEqual(profile["dps"]["rpm"], 821)
        self.assertEqual(profile["dps"]["projectiles_per_shot"], 1)
        self.assertEqual([(row["min_m"], row["max_m"], row["damage"]["base_profile"])
                          for row in profile["dps"]["damage_ranges"]],
                         [(0, 25.53, 22), (25.53, 46.99, 21), (46.99, None, 19)])
        self.assertEqual([row["damage"]["head"] for row in profile["dps"]["damage_ranges"]], [28.6, 27.3, 24.7])
        self.assertEqual([row["source_date"] for row in profile["provenance"]["components"]], ["2026-11-05", "2026-10-19"])
        result = comparison.compare("Type 73", "M4", profiles=telemetry.profiles_for("multiplayer"), hit_location="base_profile")
        metric = result["metrics"]["dps"]
        self.assertTrue(metric["available"])
        self.assertAlmostEqual(metric["series"][0]["segments"][0]["dps"], 22 * 821 / 60)
        self.assertNotIn("upper_torso", profile["dps"]["damage_ranges"][0]["damage"])
        self.assertFalse(result["metrics"]["recoil"]["available"])
        self.assertFalse(result["metrics"]["sway"]["available"])

    def test_invalid_oversized_duplicate_and_wrong_identity_fail_closed(self):
        source = json.loads(telemetry.DATA.read_bytes())
        broken = deepcopy(source)
        profile = broken["profiles"]["multiplayer"].pop("320bd7829fa4bdee")
        broken["profiles"]["multiplayer"]["0000000000000000"] = profile
        wrong_mode = deepcopy(source)
        wrong_mode["profiles"]["multiplayer"]["320bd7829fa4bdee"]["mode"] = "warzone"
        raws = [b"broken", b"[]", b" "*(telemetry.MAX_BYTES+1), b'{"profiles":{},"profiles":{}}', b'{"value":NaN}',
                json.dumps(broken).encode(), json.dumps(wrong_mode).encode()]
        with tempfile.TemporaryDirectory(prefix="cod-hub-telemetry-test-") as temporary:
            path = Path(temporary)/"telemetry.json"
            with patch.object(telemetry, "DATA", path):
                for raw in raws:
                    path.write_bytes(raw); telemetry.clear_cache()
                    self.assertEqual(telemetry.profiles_for("multiplayer"), {})
                    self.assertEqual(telemetry.fingerprint(), "00000000")
                path.unlink(); telemetry.clear_cache()
                self.assertEqual(telemetry.profiles_for("multiplayer"), {})


if __name__ == "__main__":
    unittest.main()
