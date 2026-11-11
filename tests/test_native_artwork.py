"""Native preview identity, bundled bytes, hosted URLs and honest fallbacks."""
from copy import deepcopy
import builtins
import hashlib
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

from cod_hub import artwork, native_artwork as native


ASSET = "320bd7829fa4bdee"
CODE = "A01-42J19-BU11"
WEAPON = {"asset_id": ASSET, "prefix": "A01", "name": "Kastov 762", "game": "mw4"}
ROOT = Path(__file__).resolve().parents[1]


def webp(color):
    with Image.new("RGBA", (16, 16), (0, 0, 0, 0)) as image:
        ImageDraw.Draw(image).rectangle((2, 4, 13, 11), fill=color)
        buffer = BytesIO()
        image.save(buffer, "WEBP", lossless=True, exact=True)
        return buffer.getvalue()


def record(data):
    digest = hashlib.sha256(data).hexdigest()
    return {"asset_id": ASSET, "prefix": "A01", "name": "Kastov 762", "sha256": digest,
            "filename": digest + ".webp", "format": "WEBP", "mode": "RGBA", "lossless": True,
            "width": 16, "height": 16, "alpha_extrema": [0, 255]}


class NativeArtworkTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="cod-hub-native-art-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.manifest = self.root / "data/native-artwork.json"
        self.images = self.root / "images/native"
        self.manifest.parent.mkdir()
        self.images.mkdir(parents=True)
        base, build = webp((30, 55, 70, 255)), webp((90, 120, 50, 255))
        self.base, self.build = record(base), dict(record(build), build_code=CODE)
        for item, data in ((self.base, base), (self.build, build)):
            (self.images / item["filename"]).write_bytes(data)
        self.data = {"format_version": 1, "game": "mw4", "provider": "COD Hub native renders",
                     "scope": "primary_components", "full_game_shader_camo_parity": False,
                     "base_images": {ASSET: self.base}, "build_images": {CODE: self.build}}
        for name, value in (("BUNDLE_ROOT", self.root), ("MANIFEST_PATH", self.manifest), ("IMAGE_DIR", self.images)):
            patcher = patch.object(native, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name, value in (("APPROVED_BASE_IMAGES", {ASSET: ("A01", "Kastov 762", self.base["sha256"])}),
                            ("APPROVED_BUILD_IMAGES", {CODE: (ASSET, "A01", self.build["sha256"])})):
            patcher = patch.object(native, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(native.clear_cache)
        self.write()

    def write(self, raw=None):
        self.manifest.write_bytes(raw if raw is not None else json.dumps(self.data).encode("utf8"))
        native.clear_cache()

    def test_exact_build_has_distinct_immutable_hosted_image_and_bundled_bytes(self):
        exact = native.get_art(WEAPON, build_code=CODE)
        base = native.get_art(WEAPON)
        self.assertEqual(exact["kind"], "native_build")
        self.assertEqual(exact["caption"], "Native attachment preview")
        self.assertEqual(exact["build_code"], CODE)
        self.assertEqual(base["kind"], "native_base")
        self.assertEqual(base["caption"], "Native base-weapon preview")
        self.assertNotEqual(exact["image_url"], base["image_url"])
        self.assertEqual(exact["image_url"], native.PUBLIC_BASE_URL + self.build["filename"])
        self.assertEqual(hashlib.sha256(native.image_bytes(exact)).hexdigest(), self.build["sha256"])
        self.assertEqual(exact["credit_text"], "Call of Duty / Activision")
        self.assertFalse(exact["full_game_shader_camo_parity"])
        exact["alpha_extrema"][0] = 99
        self.assertEqual(native.get_art(WEAPON, build_code=CODE)["alpha_extrema"], [0, 255])

    def test_hosted_lookup_never_imports_pillow_or_decodes_image_pixels(self):
        native.clear_cache()
        original_import = builtins.__import__
        def guarded_import(name, *args, **kwargs):
            if name == "PIL" or name.startswith("PIL."):
                raise AssertionError("Hosted artwork lookup must not import Pillow")
            return original_import(name, *args, **kwargs)
        with patch.object(Image, "open", side_effect=AssertionError("Hosted lookup must not decode images")):
            with patch.object(builtins, "__import__", guarded_import):
                art = native.get_art(WEAPON, build_code=CODE)
                self.assertEqual(art["kind"], "native_build")
                self.assertIsNotNone(native.image_bytes(art))

    def test_reviewed_files_still_require_valid_metadata_free_lossless_headers(self):
        source = (self.images / self.base["filename"]).read_bytes()
        variants = []
        for start, replacement in ((12, b"VP8 "), (16, (5).to_bytes(4, "little")), (20, b"\x00")):
            data = bytearray(source)
            data[start:start + len(replacement)] = replacement
            variants.append(bytes(data))
        original_dimensions = int.from_bytes(source[21:25], "little")
        for dimensions in (original_dimensions & ~(1 << 28), original_dimensions | (1 << 29),
                           original_dimensions ^ 1):
            data = bytearray(source)
            data[21:25] = dimensions.to_bytes(4, "little")
            variants.append(bytes(data))
        metadata = bytearray(source + b"EXIF\x00\x00\x00\x00")
        metadata[4:8] = (len(metadata) - 8).to_bytes(4, "little")
        variants.append(bytes(metadata))
        for data in variants:
            with self.subTest(header=data[:25]):
                item = record(data)
                native.APPROVED_BASE_IMAGES[ASSET] = ("A01", "Kastov 762", item["sha256"])
                (self.images / item["filename"]).write_bytes(data)
                native.clear_cache()
                self.assertIsNone(native.image_bytes(item))

    def test_other_codes_and_lookalikes_are_base_previews_not_exact_build_claims(self):
        for code in ("A01-A11NP-B11", CODE.lower(), CODE + " ", CODE.replace("A01", "R03"), None, [], {}):
            with self.subTest(code=code):
                art = native.get_art(WEAPON, build_code=code)
                self.assertEqual(art["kind"], "native_base")
                self.assertNotIn("build_code", art)
        for candidate in (dict(WEAPON, asset_id=ASSET.upper()), dict(WEAPON, game="bo7"),
                          dict(WEAPON, prefix="A09"), dict(WEAPON, kind="attachment"),
                          {"name": WEAPON["name"], "prefix": "A01"}, None):
            self.assertIsNone(native.get_art(candidate, build_code=CODE))
        art = native.get_art(dict(WEAPON, image_url="https://untrusted.invalid/a.png"), build_code=CODE)
        self.assertEqual(art["image_url"], native.PUBLIC_BASE_URL + self.build["filename"])

    def test_invalid_manifest_header_and_json_fail_closed(self):
        before = deepcopy(self.data)
        for key, value in (("format_version", True), ("game", "bo7"), ("provider", "Other"),
                           ("scope", "full_game_parity"), ("full_game_shader_camo_parity", True),
                           ("base_images", []), ("build_images", [])):
            with self.subTest(key=key):
                self.data = deepcopy(before)
                self.data[key] = value
                self.write()
                self.assertIsNone(native.get_art(WEAPON))
        for raw in (b"[]", b"broken", b'{"a":NaN}', b'{"a":1,"a":2}',
                    b" " * (native.MAX_MANIFEST_BYTES + 1)):
            self.write(raw)
            self.assertIsNone(native.get_art(WEAPON))
        self.manifest.unlink()
        native.clear_cache()
        self.assertIsNone(native.get_art(WEAPON))

    def test_invalid_identity_resource_and_shape_metadata_are_rejected(self):
        before = deepcopy(self.base)
        for key, value in (("asset_id", "0" * 16), ("prefix", "A0"), ("name", "bad\nname"),
                           ("sha256", "not-a-hash"), ("filename", "../outside.webp"),
                           ("filename", "https://untrusted.invalid/image.webp"), ("width", True),
                           ("width", 1025), ("height", 0), ("mode", "RGB"), ("format", "PNG"),
                           ("lossless", False), ("alpha_extrema", [False, 255])):
            with self.subTest(key=key, value=value):
                self.data["base_images"][ASSET] = dict(before, **{key: value})
                self.write()
                self.assertIsNone(native.get_art(WEAPON))

    def test_build_identity_must_agree_with_base_and_canonical_key(self):
        before = deepcopy(self.build)
        for key, value in (("asset_id", "0" * 16), ("prefix", "R03"), ("name", "Another weapon"),
                           ("build_code", CODE.lower())):
            with self.subTest(key=key):
                self.data["build_images"][CODE] = dict(before, **{key: value})
                self.write()
                self.assertEqual(native.get_art(WEAPON, build_code=CODE)["kind"], "native_base")
        self.data["build_images"][CODE] = dict(before, filename=self.base["filename"], sha256=self.base["sha256"])
        self.write()
        self.assertEqual(native.get_art(WEAPON, build_code=CODE)["kind"], "native_base")
        self.data["base_images"][ASSET] = dict(self.base, filename=self.build["filename"], sha256=self.build["sha256"])
        self.write()
        self.assertIsNone(native.get_art(WEAPON))

    def test_missing_corrupt_opaque_or_oversized_images_never_offer_bad_links(self):
        image_path = self.images / self.build["filename"]
        image_path.write_bytes(b"RIFFbrokenWEBP")
        native.clear_cache()
        self.assertEqual(native.get_art(WEAPON, build_code=CODE)["kind"], "native_base")
        image_path.unlink()
        native.clear_cache()
        self.assertEqual(native.get_art(WEAPON, build_code=CODE)["kind"], "native_base")
        base_path = self.images / self.base["filename"]
        for data in (b"x" * (native.MAX_IMAGE_BYTES + 1), b"RIFF\x04\x00\x00\x00WEBP"):
            base_path.write_bytes(data)
            native.clear_cache()
            self.assertIsNone(native.get_art(WEAPON))
        with Image.new("RGBA", (16, 16), (10, 20, 30, 255)) as opaque:
            buffer = BytesIO()
            opaque.save(buffer, "WEBP", lossless=True)
        opaque_data = buffer.getvalue()
        self.data["base_images"][ASSET] = record(opaque_data)
        (self.images / self.data["base_images"][ASSET]["filename"]).write_bytes(opaque_data)
        native.APPROVED_BASE_IMAGES[ASSET] = ("A01", "Kastov 762", self.data["base_images"][ASSET]["sha256"])
        self.write()
        self.assertIsNone(native.get_art(WEAPON))

    def test_resources_cannot_escape_the_bundle_or_follow_linked_directories(self):
        with tempfile.TemporaryDirectory(prefix="cod-hub-native-external-") as temporary:
            external = Path(temporary)
            (external / self.base["filename"]).write_bytes((self.images / self.base["filename"]).read_bytes())
            with patch.object(native, "IMAGE_DIR", external):
                native.clear_cache()
                self.assertIsNone(native.get_art(WEAPON))
        # A mocked filesystem attribute exercises the same guard on platforms
        # where creating directory symlinks requires extra system privileges.
        original = Path.lstat
        def linked_directory(path):
            result = original(path)
            if path == self.images.parent:
                class Linked:
                    st_mode = result.st_mode
                    st_file_attributes = 0x400
                return Linked()
            return result
        with patch.object(Path, "lstat", linked_directory):
            native.clear_cache()
            self.assertIsNone(native.get_art(WEAPON))

    def test_native_embed_is_credited_bounded_idempotent_and_honest_for_other_builds(self):
        original = {"title": "Kastov 762", "description": "x" * 5000,
                    "fields": [{"name": "Weapon", "value": "Kastov 762"}]}
        before = deepcopy(original)
        result = artwork.decorate_embed(original, WEAPON, build_code=CODE)
        self.assertEqual(original, before)
        self.assertLessEqual(len(result["description"]), 4096)
        self.assertIn("Native attachment preview", result["description"])
        self.assertIn("Call of Duty / Activision", result["description"])
        self.assertIn("Primary components; camos and charms not shown.", result["description"])
        self.assertNotIn("MetaRadar", result["description"])
        self.assertEqual(artwork.decorate_embed(result, WEAPON, build_code=CODE), result)
        unknown = artwork.decorate_embed({"title": "Other build"}, WEAPON, build_code="A01-UNKNOWN")
        self.assertIn("Native base-weapon preview", unknown["description"])
        self.assertNotIn("Native attachment preview", unknown["description"])
        full = {"title": "A", "fields": [{"name": "A", "value": "x" * 5999}]}
        self.assertEqual(artwork.decorate_embed(full, WEAPON, build_code=CODE), full)

    def test_missing_native_bytes_falls_back_to_existing_provider_art(self):
        for path in self.images.iterdir():
            path.unlink()
        native.clear_cache()
        result = artwork.decorate_embed({"title": "Kastov 762"}, WEAPON, build_code=CODE)
        self.assertIn("metaradar.gg", result["image"]["url"])
        self.assertIn("Base weapon image", result["description"])


class NativeReleaseArtworkTests(unittest.TestCase):
    def test_reviewed_release_has_seventeen_bases_and_three_distinct_builds(self):
        path = ROOT / "plugin/cod_hub/data/native-artwork.json"
        data = json.loads(path.read_text(encoding="utf8"))
        self.assertEqual(len(data["base_images"]), 17)
        self.assertEqual(len(data["build_images"]), 3)
        self.assertEqual(set(data["build_images"]), {CODE, "A01-A11NP-B11", "A01-9YGBJ-D11"})
        for asset, record_data in data["base_images"].items():
            art = native.get_art({"asset_id": asset, "prefix": record_data["prefix"], "game": "mw4"})
            self.assertIsNotNone(art, asset)
            self.assertEqual(art["kind"], "native_base")
            self.assertEqual(hashlib.sha256(native.image_bytes(art)).hexdigest(), record_data["sha256"])
        build_images = [native.get_art(WEAPON, build_code=code) for code in data["build_images"]]
        self.assertEqual(len({art["image_url"] for art in build_images}), 3)
        self.assertTrue(all(art["kind"] == "native_build" for art in build_images))


if __name__ == "__main__":
    unittest.main()
