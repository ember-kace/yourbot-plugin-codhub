"""Validate captured native artwork and the matching public hosting copies."""
from __future__ import annotations

import argparse
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import stat
import warnings

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "cod_hub/data/native-artwork.json"
CATALOG = "cod_hub/data/catalog.json"
IMAGE_ROOT = "cod_hub/images/native/"
MAX_MANIFEST_BYTES = 100_000
MAX_IMAGE_BYTES = 512_000
MAX_TOTAL_IMAGE_BYTES = 16 * 1024 * 1024

# Reviewed identity-to-render pins. Updating these requires another image review.
REVIEWED_BASE_IMAGES = {'07f7d22f45558288': 'ccd54ae9fcd5bd05e82a15777e0434cbbe27f12f80320e8856c45ffe70383a6c',
 '094574f827113d6d': '6ccb90ac10c29a8fda29a10be6477895330c3f6a5c0cc68ebc77f9148edad8a6',
 '0acd07c3fd30e85a': '0978efaa1d1f212fc6f88df4abf3bf846f35b3d322d8fc65a811c5b6ffa521e8',
 '12cf1c65abc24d34': '320d185497c0a12cf70cec026ac20a88363c15a23a3948f8512439d963c0277a',
 '160d15e6381d5cb5': '1fd65403d530169741e4d7131f2d673f75243802e74ac8ec554c2f0538900025',
 '161f8341b23454de': 'd46f713a29a422b30ae2f31f3779a4a7e384c6a399586cb8394a9a5646ae70bb',
 '174ac9ebd217d177': 'c3a9f90c3c7d2ecd2fcc6f6485b776bf1ea2248f97e8378bfc5802e1bf71d92a',
 '1f30c6b00e332af6': 'c9e5ac055033bf54de38c23e1902735226b3ca7ab70802aae82e74041e28e8f1',
 '2906672daed5983e': 'e38320cf8d5a2aba929b78cca16abe4aec0ba1705fff6516dce5d72e71e826e7',
 '2e05c75adfbfd24c': 'ce8b17a020474777c28b1959989ffb0e17802df1f7c36f9ba88984dc6d5f6281',
 '2efa8aea20d8b45d': 'eec3d5dc616ae65954bb3394003bba13859f0f0f97ae357c9c7903eccd580142',
 '320bd7829fa4bdee': '64492959b90e99317cd46545597a3dd435d721388ec4b0ad8ca2b0fc4ba197fb',
 '32f2e812899c570d': 'a9e95298d49b81e8d2ddfb1c130e2417b821426c9fc9834a71780a9295335fd6',
 '3313ea5514c15bbd': '83c238a081cb49eae5d40a63ee4f37f4ca6e9516b2887f17cb99fd30ffc5803d',
 '3bfd017330a15574': '2f01edbf6a834496d09c7da36c9a85cc897821bef3e4a3640ac95430213c4ca1',
 '3ca278a99a9ab61d': '435263f2869641be745ba01c09f241997798cb7e2db89c529bb1272ed779196a',
 '437a2fe19197ce82': 'dd5e7dcbef3ea9716555b8b04920478c2deb478327a93606c93d9e411c42fb5e',
 '43f5901edb8e5875': '56b214c0e6d96dc3be896a021bcca339c75bfa43217d9e01844340a3f8b87b46',
 '49c1b0190d746a45': '7a16d298dbb8b5b36cf3d28ceba4f44e7caab0240dc721804e7ad15bb69f7c6c',
 '4b0393a280f71061': '51c93d7dcdc295ad3ed07d441e4d1b710786b0645d66f0a7a68502af91b85295',
 '50a03474c191ed85': '6d3eb81bf5b5b7ef27d5039a8e3a42fe37e5d3c751a9c72ceb49018644ccb7c6',
 '547541041d63934d': 'b752deca280174780e93a7169062ee070ff5d274fc63107b6bde0335e86c141a',
 '54efea11f28407ea': 'd8132db7a331638cdb7b9f7907180527d4a5d5a068097a32dea92da3c5a4d0f6',
 '58b2312b43165b66': '8460226d213acea03b6c9de8ee601759f65da8b4f9086949f9ff0518c4c40ae7',
 '62f36eea38527995': '95ab0b43d11c4ee96a901f9320a1252925bb2f28fe164c39ae363da9156efcb9',
 '63845ab500bcb133': 'e0691d0a3b9a8e28528910fda21fac93921f21fa7bcdb981e506783f629e7400',
 '66bbbb111859e8e1': '870fb4ee16932ef1c737f645e517a22a12f5ff19f11f5faa08401e5276bf2d15',
 '68441ea783099179': '0dcbfb56e025b637638c6f36a11f7afe641e8b52277f63926290ed198221a9a8',
 '6cc4eea570f88e27': 'c9905b190c6dd0c7bbbdb61121cbe3ca3030c9adaf79d8c256b40c47081ba449',
 '6d470118a56e6da9': 'e276af45eb84845ded001632d281c472b60390879e54c4b3f412504c61cbae01',
 '6d7160ae60292b75': '58b294833861d9152d65b8fa76eddac618cb83f7445e66de6606805879df91c3',
 '73ca8d7b9145bb65': '6c9728c1b7923242ddef85dd1d210e7f81bbfa93b8ac0ea77a8325667a5a71af',
 '7574652bd34cc3f6': 'b6a992951221c9240820b8f1f27ba7f6cf5cc6322430f81ad819ab78ecd08962',
 '75bd0537aaa182c3': 'd086785a7348ebbc6e362971b0144d26da58ad4f3641cbe5f75760f92f51b6fa',
 '7973ece25ffff326': '56ed822e7a560dc9b08f3c7efc3d8384652e731a56a3b910b2fb6ee8ee3ca211'}
REVIEWED_BUILD_IMAGES = {
    "A01-42J19-BU11": "ce391668130198680dfbe2533f48ff929be2457339e0d72370fbbe8d17f1db88",
    "A01-9YGBJ-D11": "b59cf09a211917bd3e1f5400291a69456dc8762d4e29c82f3bc3e365620323a4",
    "A01-A11NP-B11": "c568f0fb21711798793b1b8fee00240cf14edca7cda9b89f3559e5277ed0beac",
}
REVIEWED_PREVIEW_KINDS = {'07f7d22f45558288': 'static_default',
 '094574f827113d6d': 'static_default',
 '0acd07c3fd30e85a': 'static_default',
 '12cf1c65abc24d34': 'static_default',
 '160d15e6381d5cb5': 'primary_components',
 '161f8341b23454de': 'primary_components',
 '174ac9ebd217d177': 'shader_simplified',
 '1f30c6b00e332af6': 'primary_components',
 '2906672daed5983e': 'static_default',
 '2e05c75adfbfd24c': 'folded_reference',
 '2efa8aea20d8b45d': 'static_default',
 '320bd7829fa4bdee': 'primary_components',
 '32f2e812899c570d': 'native_item_icon',
 '3313ea5514c15bbd': 'native_item_icon',
 '3bfd017330a15574': 'primary_components',
 '3ca278a99a9ab61d': 'primary_components',
 '437a2fe19197ce82': 'primary_components',
 '43f5901edb8e5875': 'shader_simplified',
 '49c1b0190d746a45': 'native_item_icon',
 '4b0393a280f71061': 'static_default',
 '50a03474c191ed85': 'static_default',
 '547541041d63934d': 'static_default',
 '54efea11f28407ea': 'primary_components',
 '58b2312b43165b66': 'primary_components',
 '62f36eea38527995': 'primary_components',
 '63845ab500bcb133': 'shader_simplified',
 '66bbbb111859e8e1': 'native_item_icon',
 '68441ea783099179': 'primary_components',
 '6cc4eea570f88e27': 'primary_components',
 '6d470118a56e6da9': 'primary_components',
 '6d7160ae60292b75': 'native_item_icon',
 '73ca8d7b9145bb65': 'shader_simplified',
 '7574652bd34cc3f6': 'static_default',
 '75bd0537aaa182c3': 'primary_components',
 '7973ece25ffff326': 'primary_components'}
PREVIEW_KINDS = {"primary_components", "static_default", "shader_simplified", "folded_reference", "world_model", "native_item_icon"}
_ASSET = re.compile(r"[0-9a-f]{16}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_PREFIX = re.compile(r"[ALRBPSCUM][0-9]{2}\Z")
_CODE = re.compile(r"[ALRBPSCUM][0-9]{2}(?:-[A-Z0-9]{1,5}){1,4}\Z")
_RECORD_KEYS = {"asset_id", "prefix", "name", "filename", "sha256", "width", "height",
                "alpha_extrema", "format", "mode", "lossless"}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate metadata key")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("Nonfinite metadata number")


def _document(raw, maximum=MAX_MANIFEST_BYTES):
    if not isinstance(raw, bytes) or not raw or len(raw) > maximum:
        raise ValueError("Missing or oversized metadata")
    return json.loads(raw.decode("utf8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)


def _lossless_chunks(data):
    """Accept static lossless WebP chunks, with no ancillary metadata payloads."""
    if (len(data) < 20 or data[:4] != b"RIFF" or data[8:12] != b"WEBP"
            or int.from_bytes(data[4:8], "little") + 8 != len(data)):
        return False
    chunks, offset = [], 12
    while offset + 8 <= len(data):
        kind = data[offset:offset + 4]
        size = int.from_bytes(data[offset + 4:offset + 8], "little")
        start, end = offset + 8, offset + 8 + size
        if end > len(data) or kind not in {b"VP8X", b"VP8L"} or kind in chunks:
            return False
        if kind == b"VP8X" and (size != 10 or data[start] not in (0, 16) or data[start + 1:start + 4] != b"\0\0\0"):
            return False
        if kind == b"VP8L" and (size < 5 or data[start] != 0x2F):
            return False
        if size % 2 and (end >= len(data) or data[end] != 0):
            return False
        chunks.append(kind)
        offset = end + size % 2
    return offset == len(data) and chunks in ([b"VP8L"], [b"VP8X", b"VP8L"])


def _image_issue(data, record):
    if not isinstance(data, bytes) or not 1 <= len(data) <= MAX_IMAGE_BYTES:
        return "missing or oversized native image"
    if hashlib.sha256(data).hexdigest() != record["sha256"]:
        return "native image hash mismatch"
    if not _lossless_chunks(data):
        return "native image must be static lossless WebP without ancillary metadata"
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                if (image.format != "WEBP" or image.mode != "RGBA"
                        or image.size != (record["width"], record["height"])
                        or getattr(image, "n_frames", 1) != 1):
                    return "native image format, dimensions or channels mismatch"
                if set(image.info) - {"loop", "background"}:
                    return "native image contains unsupported metadata"
                image.load()
                if list(image.getchannel("A").getextrema()) != [0, 255]:
                    return "native image must retain transparent and opaque pixels"
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        return "native image cannot be decoded safely"
    return None


def _record_issue(record, key, is_build, catalog):
    expected_keys = _RECORD_KEYS | ({"build_code"} if is_build else set())
    if not isinstance(record, dict) or set(record) not in (expected_keys, expected_keys | {"preview_kind"}):
        return "unexpected native artwork record fields"
    asset, prefix, sha = record["asset_id"], record["prefix"], record["sha256"]
    if (not isinstance(asset, str) or not _ASSET.fullmatch(asset)
            or (prefix is not None and (not isinstance(prefix, str) or not _PREFIX.fullmatch(prefix)))
            or not isinstance(sha, str) or not _SHA256.fullmatch(sha)
            or record["filename"] != sha + ".webp"):
        return "invalid native artwork identity or content filename"
    name = record["name"]
    if (not isinstance(name, str) or not name.strip() or len(name) > 160
            or any(ord(char) < 32 or ord(char) == 127 for char in name)
            or any(char in name for char in ("/", "\\", ":"))):
        return "invalid native artwork display name"
    if (record["format"] != "WEBP" or record["mode"] != "RGBA" or record["lossless"] is not True
            or type(record["width"]) is not int or not 1 <= record["width"] <= 1024
            or type(record["height"]) is not int or not 1 <= record["height"] <= 1024
            or record["alpha_extrema"] != [0, 255]
            or any(type(value) is not int for value in record["alpha_extrema"])):
        return "invalid native image format declaration"
    if is_build:
        if (not isinstance(key, str) or not _CODE.fullmatch(key) or len(key) > 25
                or record["build_code"] != key or not isinstance(prefix, str) or not key.startswith(prefix + "-")):
            return "invalid canonical native build image key"
        if REVIEWED_BUILD_IMAGES.get(key) != sha:
            return "native build image does not match its reviewed code pin"
    elif key != asset or REVIEWED_BASE_IMAGES.get(key) != sha:
        return "native base image does not match its reviewed asset pin"
    kind = record.get("preview_kind", "primary_components")
    if kind not in PREVIEW_KINDS or kind != ("primary_components" if is_build else REVIEWED_PREVIEW_KINDS.get(asset, "primary_components")):
        return "native artwork role differs from its reviewed scope"
    weapon = catalog.get("weapons", {}).get(prefix)
    asset_record = catalog.get("assets", {}).get(asset)
    if prefix is None and not is_build:
        reference = next((row for row in catalog.get("reference_weapons", []) if row.get("asset_id") == asset), None)
        if (not isinstance(reference, dict) or reference.get("native_supported") is not False
                or not isinstance(asset_record, dict) or asset_record.get("kind") != "weapon"):
            return "native reference image and reference-only weapon disagree"
        return None
    if (not isinstance(weapon, dict) or weapon.get("asset_id") != asset
            or not isinstance(asset_record, dict) or asset_record.get("kind") != "weapon"):
        return "native artwork prefix and catalog asset disagree"
    return None


def evaluate_captured(captured):
    """Approve exactly the JSON and image bytes already captured for the ZIP."""
    issues, records, referenced = [], [], set()
    report = {"ready": False, "base_count": 0, "build_count": 0, "image_count": 0,
              "image_bytes": 0, "issues": issues}
    try:
        manifest = _document(captured.get(MANIFEST))
        catalog = _document(captured.get(CATALOG), maximum=10 * 1024 * 1024)
        if not isinstance(catalog, dict) or not isinstance(catalog.get("weapons"), dict) or not isinstance(catalog.get("assets"), dict):
            raise ValueError("Catalog shape")
        if (not isinstance(manifest, dict) or set(manifest) != {
                "format_version", "game", "provider", "scope", "full_game_shader_camo_parity", "base_images", "build_images"}
                or type(manifest["format_version"]) is not int or manifest["format_version"] != 1
                or manifest["game"] != "mw4" or manifest["provider"] != "COD Hub native renders"
                or manifest["scope"] not in {"primary_components", "reviewed_native_references"} or manifest["full_game_shader_camo_parity"] is not False
                or not isinstance(manifest["base_images"], dict) or not isinstance(manifest["build_images"], dict)):
            raise ValueError("Manifest shape or scope")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        issues.append({"path": MANIFEST, "issue": "invalid native artwork manifest or catalog"})
        return report
    for field, is_build, pins in (("base_images", False, REVIEWED_BASE_IMAGES),
                                 ("build_images", True, REVIEWED_BUILD_IMAGES)):
        entries = manifest[field]
        if set(entries) != set(pins):
            issues.append({"path": MANIFEST, "issue": "native artwork must contain the complete reviewed identity set", "field": field})
        report["build_count" if is_build else "base_count"] = len(entries)
        for key, record in entries.items():
            problem = _record_issue(record, key, is_build, catalog)
            if problem:
                issues.append({"path": MANIFEST, "issue": problem, "field": field})
                continue
            path = IMAGE_ROOT + record["filename"]
            referenced.add(path)
            records.append((path, record))
    bundled = {path for path in captured if path.startswith(IMAGE_ROOT)}
    for path in sorted(bundled - referenced):
        issues.append({"path": path, "issue": "unreferenced bundled native image"})
    for path, record in records:
        problem = _image_issue(captured.get(path), record)
        if problem:
            issues.append({"path": path, "issue": problem})
    report["image_count"] = len(referenced)
    report["image_bytes"] = sum(len(captured[path]) for path in referenced if isinstance(captured.get(path), bytes))
    if report["image_bytes"] > MAX_TOTAL_IMAGE_BYTES:
        issues.append({"path": IMAGE_ROOT, "issue": "native artwork exceeds the total byte budget"})
    report["ready"] = not issues
    return report


def _safe_file(root, relative):
    """Read a regular file without following symlink or junction components."""
    root = Path(root).absolute()
    current = root
    for part in (None, *Path(relative).parts):
        if part is not None:
            current /= part
        metadata = current.lstat()
        if (stat.S_ISLNK(metadata.st_mode)
                or getattr(metadata, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
            raise ValueError("Linked artwork source path")
    if not current.resolve(strict=True).is_relative_to(root.resolve(strict=True)) or not current.is_file():
        raise ValueError("Invalid artwork source file")
    return current.read_bytes()


def evaluate_release(plugin_path=ROOT / "plugin", hosted_path=ROOT / "docs/artwork/v1"):
    """Validate source art and byte-identical Pages copies, with no private inputs."""
    plugin_path, hosted_path = Path(plugin_path), Path(hosted_path)
    captured, source_issues = {}, []
    for relative in (MANIFEST, CATALOG):
        try:
            captured[relative] = _safe_file(plugin_path, relative)
        except (OSError, ValueError):
            source_issues.append({"path": relative, "issue": "missing or linked native artwork source"})
    image_names = sorted({sha + ".webp" for sha in (*REVIEWED_BASE_IMAGES.values(), *REVIEWED_BUILD_IMAGES.values())})
    for filename in image_names:
        relative = IMAGE_ROOT + filename
        try:
            captured[relative] = _safe_file(plugin_path, relative)
        except (OSError, ValueError):
            source_issues.append({"path": relative, "issue": "missing or linked native image"})
    report = evaluate_captured(captured)
    report["issues"].extend(source_issues)
    try:
        hosted_manifest = _safe_file(hosted_path.parent, "manifest.json")
        if hosted_manifest != captured.get(MANIFEST):
            report["issues"].append({"path": "docs/artwork/manifest.json", "issue": "hosted and bundled native manifests differ"})
    except (OSError, ValueError):
        report["issues"].append({"path": "docs/artwork/manifest.json", "issue": "missing or linked hosted native manifest"})
    expected = set(image_names)
    for root, label in ((plugin_path / IMAGE_ROOT, IMAGE_ROOT), (hosted_path, "docs/artwork/v1/")):
        try:
            found = {path.name for path in root.iterdir()}
        except OSError:
            found = set()
        if found != expected:
            report["issues"].append({"path": label, "issue": "native image directory differs from the reviewed file set"})
    for filename in image_names:
        try:
            hosted = _safe_file(hosted_path, filename)
            if hosted != captured.get(IMAGE_ROOT + filename):
                report["issues"].append({"path": "docs/artwork/v1/" + filename, "issue": "hosted and bundled native image bytes differ"})
        except (OSError, ValueError):
            report["issues"].append({"path": "docs/artwork/v1/" + filename, "issue": "missing or linked hosted native image"})
    report["hosted_copies_checked"] = len(image_names)
    report["ready"] = not report["issues"]
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin", type=Path, default=ROOT / "plugin")
    parser.add_argument("--hosted", type=Path, default=ROOT / "docs/artwork/v1")
    args = parser.parse_args(argv)
    report = evaluate_release(args.plugin, args.hosted)
    print(json.dumps(report, indent=2))
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
