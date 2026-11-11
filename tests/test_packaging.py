"""Release-policy and accidental game-file disclosure checks."""
from io import BytesIO
from contextlib import redirect_stdout
from io import StringIO
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from tools.package_plugin import ROOT, FILES, main, prepare
from tools.english_release_gate import evaluate_release


def synthetic_plugin(parent):
    """A complete synthetic fixture; it never changes production name evidence."""
    plugin = Path(parent) / "plugin"
    for relative in FILES:
        target = plugin / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / "plugin" / relative).read_bytes())
    data = plugin / "cod_hub/data"
    catalog = json.loads((data / "catalog.json").read_text())
    sources = json.loads((data / "facts-sources.json").read_text())
    sources["sources"]["synthetic-package-test"] = {
        "title": "Synthetic packaging test only", "kind": "official_reference", "language": "en",
        "source_date": "2026-11-09", "url": "https://example.invalid/synthetic"}
    for number, record in enumerate(catalog["assets"].values()):
        record.update(name=f"Verified English Name {number}", quality="official_reference", name_ambiguous=False,
                      source_ids=["synthetic-package-test"])
    for reference in catalog["reference_weapons"]:
        source = catalog["assets"][reference["asset_id"]]
        for key in ("name", "quality", "source_ids"):
            reference[key] = copy.deepcopy(source[key])
    (data / "catalog.json").write_text(json.dumps(catalog), encoding="utf8")
    (data / "facts-sources.json").write_text(json.dumps(sources), encoding="utf8")
    assert evaluate_release(plugin)["ready"]
    return plugin, catalog


class PackagingTests(unittest.TestCase):
    def test_manifest_matches_assigned_platform_id_and_runtime_version(self):
        from cod_hub import __version__
        from tools.package_plugin import PLATFORM_PLUGIN_ID

        manifest = json.loads((ROOT / "plugin/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["id"], "rmg84ete7r8b")
        self.assertEqual(manifest["id"], PLATFORM_PLUGIN_ID)
        self.assertEqual(manifest["version"], __version__)

    def test_package_rejects_manifest_for_a_different_platform_plugin(self):
        with tempfile.TemporaryDirectory(prefix="cod-hub-package-identity-test-") as temporary:
            plugin, _ = synthetic_plugin(temporary)
            manifest_path = plugin / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["id"] = "another_plugin"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            _, report = prepare(plugin)
            self.assertFalse(report["release_ready"])
            self.assertTrue(report["sdk_validation"]["errors"])
            _, report = prepare(plugin, plugin_id="another_plugin")
            self.assertTrue(report["release_ready"])

    def test_local_policy_blocks_url_import_even_when_sdk_validation_passes(self):
        with tempfile.TemporaryDirectory(prefix="cod-hub-package-security-test-") as temporary:
            plugin, _ = synthetic_plugin(temporary)
            source_path = plugin / "cod_hub/cards.py"
            source_path.write_text("from urllib.parse import urlsplit\n" + source_path.read_text(encoding="utf-8"),
                                   encoding="utf-8")
            output = Path(temporary) / "COD-Hub.zip"
            report_path = Path(temporary) / "report.json"
            with redirect_stdout(StringIO()):
                result = main(["--plugin", str(plugin), "--output", str(output), "--report", str(report_path)])
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["sdk_validation"]["errors"], [])
            self.assertFalse(report["artifact_policy"]["ready"])
            self.assertEqual(report["artifact_policy"]["findings"][0]["symbol"], "urllib.parse")
            self.assertEqual(result, 1)
            self.assertFalse(output.exists())

    def test_package_rejects_a_different_expected_platform_version(self):
        with tempfile.TemporaryDirectory(prefix="cod-hub-package-version-test-") as temporary:
            plugin, _ = synthetic_plugin(temporary)
            _, report = prepare(plugin, version="99.0.0")
            self.assertFalse(report["release_ready"])
            self.assertTrue(report["sdk_validation"]["errors"])

    def test_missing_manifest_version_returns_a_clean_failure_without_a_zip(self):
        with tempfile.TemporaryDirectory(prefix="cod-hub-package-manifest-test-") as temporary:
            plugin, _ = synthetic_plugin(temporary)
            manifest_path = plugin / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            del manifest["version"]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            output = Path(temporary) / "COD-Hub.zip"
            with redirect_stdout(StringIO()) as printed:
                result = main(["--plugin", str(plugin), "--output", str(output)])
            self.assertEqual(result, 1)
            self.assertFalse(output.exists())
            self.assertIn("version fields", json.loads(printed.getvalue())["error"])

    def test_ancestor_symlink_cannot_supply_inside_or_outside_package_members(self):
        for escape in (False, True):
            with self.subTest(escape=escape), tempfile.TemporaryDirectory(prefix="cod-hub-package-link-test-") as temporary:
                root = Path(temporary).resolve()
                plugin, _ = synthetic_plugin(root)
                linked = plugin / "cod_hub"
                destination = (root if escape else plugin) / "moved-members"
                self.assertTrue(linked.resolve().is_relative_to(root))
                self.assertTrue(destination.resolve().is_relative_to(root))
                linked.rename(destination)
                try:
                    linked.symlink_to(destination, target_is_directory=True)
                except OSError as error:
                    self.skipTest("Directory symlinks unavailable: " + str(error))
                try:
                    leaf = linked / "data/catalog.json"
                    self.assertFalse(leaf.is_symlink())
                    self.assertTrue(leaf.is_file())
                    self.assertEqual(leaf.resolve().is_relative_to(plugin), not escape)
                    with self.assertRaisesRegex(ValueError, "Linked package path component"):
                        prepare(plugin)
                finally:
                    # Only remove our checked link; never recursively delete its target.
                    self.assertTrue(linked.absolute().is_relative_to(root))
                    self.assertTrue(linked.resolve().is_relative_to(root))
                    linked.unlink()

    @unittest.skipUnless(os.name == "nt", "Windows junction regression")
    def test_windows_junction_ancestor_cannot_escape_package_root(self):
        import _winapi

        with tempfile.TemporaryDirectory(prefix="cod-hub-package-junction-test-") as temporary:
            root = Path(temporary).resolve()
            plugin, _ = synthetic_plugin(root)
            linked, destination = plugin / "cod_hub", root / "external-members"
            self.assertTrue(linked.resolve().is_relative_to(root))
            self.assertTrue(destination.resolve().is_relative_to(root))
            linked.rename(destination)
            _winapi.CreateJunction(str(destination), str(linked))
            try:
                leaf = linked / "data/catalog.json"
                self.assertTrue(linked.is_junction())
                self.assertFalse(leaf.is_symlink())
                self.assertTrue(leaf.is_file())
                self.assertFalse(leaf.resolve().is_relative_to(plugin))
                with self.assertRaisesRegex(ValueError, "Linked package path component"):
                    prepare(plugin)
            finally:
                # rmdir unlinks the checked junction without traversing it.
                self.assertTrue(linked.absolute().is_relative_to(root))
                self.assertTrue(linked.resolve().is_relative_to(root))
                linked.rmdir()

    def test_font_exception_is_the_known_licensed_chart_resource(self):
        font = ROOT / "plugin/cod_hub/fonts/font.ttf"
        data = font.read_bytes()
        self.assertTrue(data.startswith(b"\x00\x01\x00\x00"))
        self.assertEqual(hashlib.sha256(data).hexdigest(), "7fb917c89019896d0b52ee84b7cbb3304c18cb90b19a62f5e32712bd23e97669")
        self.assertIn("SIL OPEN FONT LICENSE", (font.parent / "LICENSE.txt").read_text(encoding="utf8"))

    def test_incomplete_english_cannot_write_release_zip(self):
        with tempfile.TemporaryDirectory(prefix="cod-hub-package-test-") as temporary:
            plugin, catalog = synthetic_plugin(temporary)
            next(iter(catalog["assets"].values()))["quality"] = "internal"
            (plugin / "cod_hub/data/catalog.json").write_text(json.dumps(catalog), encoding="utf8")
            output = Path(temporary) / "COD-Hub.zip"
            report = Path(temporary) / "report.json"
            with redirect_stdout(StringIO()):
                result = main(["--plugin", str(plugin), "--output", str(output), "--report", str(report)])
            self.assertEqual(result, 1)
            self.assertFalse(output.exists())
            state = json.loads(report.read_text())
            self.assertFalse(state["release_ready"])
            self.assertEqual(state["english"]["required"], 1299)
            self.assertLess(state["english"]["total_translated"], 1299)

    def test_concurrent_completion_cannot_approve_an_older_incomplete_archive(self):
        from yourbot_sdk._validation import validate_artifact
        with tempfile.TemporaryDirectory(prefix="cod-hub-package-race-test-") as temporary:
            plugin, complete = synthetic_plugin(temporary)
            partial = copy.deepcopy(complete)
            asset_id = next(iter(partial["assets"]))
            partial["assets"][asset_id]["quality"] = "internal"
            catalog_path = plugin / "cod_hub/data/catalog.json"
            catalog_path.write_text(json.dumps(partial), encoding="utf8")

            def finish_import(**kwargs):
                result = validate_artifact(**kwargs)
                catalog_path.write_text(json.dumps(complete), encoding="utf8")
                return result

            with patch("yourbot_sdk._validation.validate_artifact", side_effect=finish_import):
                data, report = prepare(plugin)
            self.assertTrue(evaluate_release(plugin)["ready"])
            self.assertFalse(report["release_ready"])
            with zipfile.ZipFile(BytesIO(data)) as archive:
                captured = json.loads(archive.read("cod_hub/data/catalog.json"))
            self.assertEqual(captured["assets"][asset_id]["quality"], "internal")

    def test_archive_has_root_entrypoint_and_no_research_or_compiled_payload(self):
        data, report = prepare(ROOT / "plugin")
        self.assertEqual(report["sdk_validation"]["errors"], [])
        self.assertEqual(report["sdk_validation"]["warnings"], [])
        self.assertTrue(report["native_artwork"]["ready"])
        self.assertEqual(report["native_artwork"]["image_count"], 20)
        self.assertEqual(report["native_artwork"]["image_bytes"], 2_001_102)
        with zipfile.ZipFile(BytesIO(data)) as archive:
            paths = archive.namelist()
            self.assertIn("manifest.json", paths)
            self.assertIn("__main__.py", paths)
            self.assertLessEqual(len(paths), 200)
            self.assertLess(sum(i.file_size for i in archive.infolist()), 40 * 1024 * 1024)
            for name in paths:
                self.assertTrue(name.endswith((".py", ".json", ".txt", ".md")) or name == "cod_hub/fonts/font.ttf"
                                or name.startswith("cod_hub/images/native/") and name.endswith(".webp"), name)
                self.assertFalse(any(part in name.lower() for part in ("research", "__pycache__", "analysis-packages", "cod-image", "transformed-region")), name)
                self.assertFalse(name.startswith(("/", "\\")))
                self.assertNotIn("..", Path(name).parts)

    def test_corrupt_native_image_cannot_write_a_release_zip(self):
        with tempfile.TemporaryDirectory(prefix="cod-hub-package-native-art-test-") as temporary:
            plugin, _ = synthetic_plugin(temporary)
            image = next((plugin / "cod_hub/images/native").glob("*.webp"))
            image.write_bytes(b"corrupt native image")
            output = Path(temporary) / "COD-Hub.zip"
            report_path = Path(temporary) / "report.json"
            with redirect_stdout(StringIO()):
                result = main(["--plugin", str(plugin), "--output", str(output), "--report", str(report_path)])
            report = json.loads(report_path.read_text(encoding="utf8"))
            self.assertEqual(result, 1)
            self.assertFalse(output.exists())
            self.assertFalse(report["release_ready"])
            self.assertFalse(report["native_artwork"]["ready"])
            self.assertTrue(any(item["issue"] == "native image hash mismatch" for item in report["native_artwork"]["issues"]))

    def test_late_native_image_repair_cannot_approve_older_captured_bytes(self):
        from yourbot_sdk._validation import validate_artifact
        with tempfile.TemporaryDirectory(prefix="cod-hub-package-native-race-test-") as temporary:
            plugin, _ = synthetic_plugin(temporary)
            image = next((plugin / "cod_hub/images/native").glob("*.webp"))
            original = image.read_bytes()
            image.write_bytes(b"corrupt native image")

            def finish_repair(**kwargs):
                result = validate_artifact(**kwargs)
                image.write_bytes(original)
                return result

            with patch("yourbot_sdk._validation.validate_artifact", side_effect=finish_repair):
                data, report = prepare(plugin)
            self.assertEqual(image.read_bytes(), original)
            self.assertFalse(report["native_artwork"]["ready"])
            self.assertFalse(report["release_ready"])
            with zipfile.ZipFile(BytesIO(data)) as archive:
                self.assertEqual(archive.read(image.relative_to(plugin).as_posix()), b"corrupt native image")


if __name__ == "__main__":
    unittest.main()
