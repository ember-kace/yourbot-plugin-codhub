"""Offline plot rendering; synthetic angular paths are test fixtures only."""
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import struct
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from cod_hub import comparison, comparison_charts as charts, telemetry
from tests.test_comparison import profile_map


def measured_fixture():
    profiles = profile_map("A01", "A05")
    for profile in profiles.values():
        profile["provenance"]["caveats"] = ["Synthetic unit-test measurements only; not production weapon facts."]
    profiles[comparison.resolve_subject("A05")["key"]]["recoil"]["points"][1]["x"] = 0.06
    return comparison.compare("A01", "A05", profiles=profiles)


class ComparisonChartTests(unittest.TestCase):
    def test_unavailable_metrics_are_refused_instead_of_invented(self):
        result = comparison.compare("A01", "A05")
        for metric in ("dps", "recoil", "sway"):
            with self.subTest(metric=metric), self.assertRaisesRegex(ValueError, "unavailable"):
                charts.render_chart(result, metric)
        for result, metric in ((None, "dps"), ({"metrics": None}, "dps"), ({}, "accuracy")):
            with self.assertRaises(ValueError):
                charts.render_svg(result, metric)

    def test_dps_svg_is_standalone_and_preserves_dates_caveats_and_label_scope(self):
        result = comparison.compare("A01", "A05", profiles=telemetry.profiles_for("multiplayer"), hit_location="base_profile")
        svg = charts.render_svg(result)
        root = ET.fromstring(svg)
        self.assertEqual((root.attrib["width"], root.attrib["height"]), ("760", "700"))
        text = " ".join(root.itertext())
        for expected in ("Theoretical DPS by distance", "region unspecified", "2026-11-05", "2026-10-19",
                         "Kastov 762", "M4", "current", "not real TTK", "engine threshold"):
            self.assertIn(expected, text)
        self.assertNotIn("<script", svg)
        self.assertNotIn("file://", svg)
        self.assertNotIn("<image", svg)
        for element in root.iter():
            for name, value in element.attrib.items():
                if name.split("}")[-1] == "href":
                    self.assertTrue(value.startswith("#"), value)
        for series in result["metrics"]["dps"]["series"]:
            for caveat in series["provenance"]["caveats"]:
                self.assertIn(caveat, text)

    def test_real_dps_png_has_bounded_dimensions_and_visible_ink(self):
        from PIL import Image
        result = comparison.compare("A01", "A05", profiles=telemetry.profiles_for("multiplayer"), hit_location="base_profile")
        png = charts.render_chart(result)
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(struct.unpack_from(">II", png, 16), (760, 700))
        self.assertLess(len(png), 300_000)
        with Image.open(BytesIO(png)) as image:
            self.assertEqual(image.size, (760, 700))
            self.assertGreater(len(image.getcolors(760*700)), 100)

    def test_recoil_and_sway_render_different_measured_axes_without_scores(self):
        result = measured_fixture()
        original = deepcopy(result)
        recoil = charts.render_svg(result, "recoil")
        sway = charts.render_svg(result, "sway")
        self.assertIn("Horizontal angle (degrees)", recoil)
        self.assertIn("Vertical angle (degrees)", recoil)
        self.assertIn("single trial, 1 sample", recoil)
        self.assertIn("Time (s)", sway)
        self.assertIn("Aiming angle (degrees)", sway)
        self.assertIn("horizontal", sway)
        self.assertIn("vertical", sway)
        self.assertIn("Synthetic unit-test measurements only", sway)
        for metric in ("recoil", "sway"):
            self.assertTrue(charts.render_chart(result, metric).startswith(b"\x89PNG"))
        self.assertEqual(result, original)

    def test_labels_cannot_create_scripts_or_external_svg_resources(self):
        result = measured_fixture()
        result["metrics"]["dps"]["series"][0]["label"] = "A </text><image href='https://attacker.invalid/a'/>"
        svg = charts.render_svg(result)
        root = ET.fromstring(svg)
        self.assertFalse(any(node.tag.split("}")[-1] in {"image", "script", "foreignObject"} for node in root.iter()))
        self.assertIn("&lt;image", svg)

    def test_bad_numbers_sampling_and_units_are_refused(self):
        edits = [
            ("dps", lambda s: s["points"][0].update(dps=float("nan"))),
            ("dps", lambda s: s["points"][0].update(distance_m=-1)),
            ("dps", lambda s: s.update(hit_location="head")),
            ("recoil", lambda s: s["points"][0].update(shot=2)),
            ("recoil", lambda s: s.update(sample_count=2)),
            ("recoil", lambda s: s.update(unit="percent")),
            ("sway", lambda s: s["points"][1].update(time_s=0)),
        ]
        for metric, edit in edits:
            result = measured_fixture()
            edit(result["metrics"][metric]["series"][0])
            with self.subTest(metric=metric), self.assertRaises(ValueError):
                charts.render_svg(result, metric)

    def test_missing_or_invalid_font_and_bad_renderer_payload_fail_cleanly(self):
        result = measured_fixture()
        with patch.object(charts, "FONT_PATH", Path("not-an-installed-chart-font.ttf")):
            with self.assertRaisesRegex(ValueError, "font"):
                charts.render_chart(result)
        with patch("resvg_py.svg_to_bytes", return_value=b"\x89PNG\r\n\x1a\n"):
            with self.assertRaisesRegex(ValueError, "invalid"):
                charts.render_chart(result)
        with patch("resvg_py.svg_to_bytes", side_effect=RuntimeError("renderer failed")):
            with self.assertRaisesRegex(ValueError, "could not be rendered"):
                charts.render_chart(result)

    def test_explicit_font_and_system_font_isolation_are_passed_to_resvg(self):
        import resvg_py
        original = resvg_py.svg_to_bytes
        with patch("resvg_py.svg_to_bytes", wraps=original) as renderer:
            charts.render_chart(measured_fixture())
        kwargs = renderer.call_args.kwargs
        self.assertTrue(kwargs["skip_system_fonts"])
        self.assertEqual(kwargs["font_files"], [str(charts.FONT_PATH)])
        self.assertEqual(kwargs["font_family"], "Atkinson Hyperlegible")
        self.assertNotIn("resources_dir", kwargs)
        license_text = charts.FONT_PATH.with_name("LICENSE.txt").read_text()
        self.assertIn("SIL OPEN FONT LICENSE", license_text)
        self.assertIn("Copyright 2020 Braille Institute", license_text)

    def test_busy_renderer_fails_without_starting_another_native_job(self):
        with patch.object(charts, "_RENDER_LOCK") as lock, patch.object(charts, "_rasterize") as raster:
            lock.acquire.return_value = False
            with self.assertRaisesRegex(ValueError, "busy"):
                charts.render_chart(measured_fixture())
        raster.assert_not_called()

    def test_compact_plot_has_readable_labels_and_complete_companion_provenance(self):
        result = comparison.compare("A01", "A05", profiles=telemetry.profiles_for("multiplayer"), hit_location="base_profile")
        svg = charts.render_svg(result)
        root = ET.fromstring(svg)
        visible = " ".join(node.text or "" for node in root.iter() if node.tag.split("}")[-1] == "text")
        self.assertIn("comparison-measurements.txt", visible)
        self.assertIn("region unspecified", visible)
        self.assertIn("not real TTK", visible)
        self.assertIn("2026-11-05", visible)
        self.assertIn("2026-10-19", visible)
        self.assertRegex(svg, r"font-size:\s*18px")
        self.assertRegex(svg, r"font-size:\s*21px")
        # The full export remains useful independently of the compact image.
        notes = charts.measurement_notes(result)
        metadata = next(node for node in root.iter() if node.tag.split("}")[-1] == "metadata")
        complete = json.loads(metadata.text)["complete_notes"]
        for series in result["metrics"]["dps"]["series"]:
            provenance = series["provenance"]
            for key in ("patch", "method", "source_url", "source_date"):
                self.assertIn(provenance[key], notes)
            for component in provenance["components"]:
                for key in ("source_url", "source_date", "note"):
                    self.assertIn(component[key], notes)
            for caveat in provenance["caveats"]:
                self.assertIn(caveat, notes)
                self.assertIn(caveat, complete)
        for metric in ("recoil", "sway"):
            fixture = measured_fixture()
            if metric == "sway":
                for series in fixture["metrics"]["sway"]["series"]:
                    series["condition"] = "Synthetic ADS after one second"
                    series["stance"] = "Synthetic standing stance"
            notes = charts.measurement_notes(fixture, metric)
            self.assertIn("Synthetic unit-test measurements only", notes)
            self.assertIn("Synthetic", notes)
            self.assertIn("degrees", notes)
            if metric == "sway":
                self.assertIn("condition: Synthetic ADS after one second", notes)
                self.assertIn("stance: Synthetic standing stance", notes)


if __name__ == "__main__":
    unittest.main()
