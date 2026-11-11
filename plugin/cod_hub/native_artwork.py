"""Exact reviewed renders shared by hosted cards and bundled image exports."""
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import stat


BUNDLE_ROOT = Path(__file__).parent
MANIFEST_PATH = BUNDLE_ROOT / "data/native-artwork.json"
IMAGE_DIR = BUNDLE_ROOT / "images/native"
PUBLIC_BASE_URL = "https://ember-kace.github.io/yourbot-plugin-codhub/artwork/v1/"
MAX_MANIFEST_BYTES = 100_000
MAX_IMAGE_BYTES = 512_000
_ASSET = re.compile(r"[0-9a-f]{16}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_PREFIX = re.compile(r"[ALRBPSCUM][0-9]{2}\Z")
_CODE = re.compile(r"[ALRBPSCUM][0-9]{2}(?:-[A-Z0-9]{1,5}){1,4}\Z")
# These identities were reviewed before publication. Changing a manifest alone
# cannot relabel a base image as an attachment-specific render or another gun.
APPROVED_BASE_IMAGES = {
    "320bd7829fa4bdee": ("A01", "Kastov 762", "64492959b90e99317cd46545597a3dd435d721388ec4b0ad8ca2b0fc4ba197fb"),
    "68441ea783099179": ("A03", "Han 86", "0dcbfb56e025b637638c6f36a11f7afe641e8b52277f63926290ed198221a9a8"),
    "6d470118a56e6da9": ("A04", "Axion", "e276af45eb84845ded001632d281c472b60390879e54c4b3f412504c61cbae01"),
    "54efea11f28407ea": ("A05", "M4", "d8132db7a331638cdb7b9f7907180527d4a5d5a068097a32dea92da3c5a4d0f6"),
    "7973ece25ffff326": ("A09", "Hyeon Burst", "56ed822e7a560dc9b08f3c7efc3d8384652e731a56a3b910b2fb6ee8ee3ca211"),
    "3bfd017330a15574": ("B04", "Patriot XMR", "2f01edbf6a834496d09c7da36c9a85cc897821bef3e4a3640ac95430213c4ca1"),
    "6cc4eea570f88e27": ("L02", "APOC-338", "c9905b190c6dd0c7bbbdb61121cbe3ca3030c9adaf79d8c256b40c47081ba449"),
    "1f30c6b00e332af6": ("L03", "FiNN LMG", "c9e5ac055033bf54de38c23e1902735226b3ca7ab70802aae82e74041e28e8f1"),
    "75bd0537aaa182c3": ("L04", "Type 73", "d086785a7348ebbc6e362971b0144d26da58ad4f3641cbe5f75760f92f51b6fa"),
    "3ca278a99a9ab61d": ("M01", "Oris 8.6", "435263f2869641be745ba01c09f241997798cb7e2db89c529bb1272ed779196a"),
    "437a2fe19197ce82": ("M02", "MAR-9", "dd5e7dcbef3ea9716555b8b04920478c2deb478327a93606c93d9e411c42fb5e"),
    "43f5901edb8e5875": ("R02", "Signal 50", "7357d1f659c0bf6f86c72820ebe361cdf8cc3e093555f00613f53fac594a332a"),
    "63845ab500bcb133": ("R03", "Astaroth .57", "87b8f5d06af144ba98aa8805d53bc7977d14de98cc98b4a5b9172c5fc050b727"),
    "62f36eea38527995": ("S03", "VEL 46", "95ab0b43d11c4ee96a901f9320a1252925bb2f28fe164c39ae363da9156efcb9"),
    "161f8341b23454de": ("S04", "Wz.55 Striga", "d46f713a29a422b30ae2f31f3779a4a7e384c6a399586cb8394a9a5646ae70bb"),
    "160d15e6381d5cb5": ("S06", "ISO Nightshade", "1fd65403d530169741e4d7131f2d673f75243802e74ac8ec554c2f0538900025"),
    "58b2312b43165b66": ("S08", "X-58 Nyx", "8460226d213acea03b6c9de8ee601759f65da8b4f9086949f9ff0518c4c40ae7"),
}
APPROVED_BUILD_IMAGES = {
    "A01-42J19-BU11": ("320bd7829fa4bdee", "A01", "ce391668130198680dfbe2533f48ff929be2457339e0d72370fbbe8d17f1db88"),
    "A01-A11NP-B11": ("320bd7829fa4bdee", "A01", "c568f0fb21711798793b1b8fee00240cf14edca7cda9b89f3559e5277ed0beac"),
    "A01-9YGBJ-D11": ("320bd7829fa4bdee", "A01", "b59cf09a211917bd3e1f5400291a69456dc8762d4e29c82f3bc3e365620323a4"),
}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate native artwork key.")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("Non-finite native artwork number.")


def _read_member(root, path, maximum):
    """Only read ordinary bundled files, without following linked components."""
    root, path = Path(root).absolute(), Path(path).absolute()
    relative = path.relative_to(root)
    current = root
    for part in (None, *relative.parts):
        if part is not None:
            current = current / part
        metadata = current.lstat()
        if (stat.S_ISLNK(metadata.st_mode)
                or getattr(metadata, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
            raise ValueError("Linked native artwork resource.")
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root.resolve(strict=True)) or not resolved.is_file():
        raise ValueError("Invalid native artwork resource.")
    with resolved.open("rb") as stream:
        data = stream.read(maximum + 1)
    if not data or len(data) > maximum:
        raise ValueError("Native artwork resource exceeds its limit.")
    return data


def _record(item):
    if not isinstance(item, dict):
        return None
    asset, prefix, digest = item.get("asset_id"), item.get("prefix"), item.get("sha256")
    name = item.get("name")
    if (not isinstance(asset, str) or not _ASSET.fullmatch(asset)
            or not isinstance(prefix, str) or not _PREFIX.fullmatch(prefix)
            or not isinstance(digest, str) or not _SHA256.fullmatch(digest)
            or item.get("filename") != digest + ".webp"
            or not isinstance(name, str) or not name.strip() or len(name) > 160
            or any(ord(char) < 32 or ord(char) == 127 for char in name)
            or item.get("format") != "WEBP" or item.get("mode") != "RGBA"
            or item.get("lossless") is not True
            or type(item.get("width")) is not int or not 1 <= item["width"] <= 1024
            or type(item.get("height")) is not int or not 1 <= item["height"] <= 1024
            or item.get("alpha_extrema") != [0, 255]
            or any(type(value) is not int for value in item.get("alpha_extrema", []))):
        return None
    return {key: deepcopy(item[key]) for key in (
        "asset_id", "prefix", "name", "sha256", "filename", "format", "mode",
        "lossless", "width", "height", "alpha_extrema")}


@lru_cache(maxsize=1)
def _load_manifest(root, path):
    try:
        data = json.loads(_read_member(root, path, MAX_MANIFEST_BYTES).decode("utf8"),
                          object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        if (not isinstance(data, dict) or type(data.get("format_version")) is not int
                or data["format_version"] != 1 or data.get("game") != "mw4"
                or data.get("provider") != "COD Hub native renders"
                or data.get("scope") != "primary_components"
                or data.get("full_game_shader_camo_parity") is not False
                or not isinstance(data.get("base_images"), dict) or len(data["base_images"]) > 128
                or not isinstance(data.get("build_images"), dict) or len(data["build_images"]) > 512):
            return {}, {}
        bases, builds, prefixes = {}, {}, set()
        for asset, item in data["base_images"].items():
            record = _record(item)
            if (record is not None and record["asset_id"] == asset
                    and APPROVED_BASE_IMAGES.get(asset) == (record["prefix"], record["name"], record["sha256"])):
                if record["prefix"] in prefixes:
                    return {}, {}
                prefixes.add(record["prefix"])
                bases[asset] = record
        for code, item in data["build_images"].items():
            record = _record(item)
            if (record is None or not isinstance(code, str) or not _CODE.fullmatch(code)
                    or len(code) > 25 or item.get("build_code") != code
                    or not code.startswith(record["prefix"] + "-")
                    or APPROVED_BUILD_IMAGES.get(code) != (record["asset_id"], record["prefix"], record["sha256"])):
                continue
            base = bases.get(record["asset_id"])
            if base is None or any(record[key] != base[key] for key in ("asset_id", "prefix", "name")):
                continue
            record["build_code"] = code
            builds[code] = record
        return bases, builds
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        return {}, {}


@lru_cache(maxsize=32)
def _image_bytes(root, directory, filename, digest, width, height):
    try:
        data = _read_member(root, Path(directory) / filename, MAX_IMAGE_BYTES)
        if (len(data) < 25 or data[:4] != b"RIFF" or data[8:12] != b"WEBP"
                or int.from_bytes(data[4:8], "little") + 8 != len(data)
                or hashlib.sha256(data).hexdigest() != digest):
            return None
        # Published renders have one metadata-free lossless VP8L chunk. The
        # reviewed hash proves their pixels/alpha; URL selection only needs to
        # check this small header, without loading Pillow or a full RGBA bitmap.
        chunk_bytes = int.from_bytes(data[16:20], "little")
        if (data[12:16] != b"VP8L" or chunk_bytes < 5 or data[20] != 0x2f
                or 20 + chunk_bytes + (chunk_bytes & 1) != len(data)
                or (chunk_bytes & 1 and data[-1] != 0)):
            return None
        dimensions = int.from_bytes(data[21:25], "little")
        if (((dimensions & 0x3fff) + 1, ((dimensions >> 14) & 0x3fff) + 1) != (width, height)
                or (dimensions >> 28) & 1 != 1 or dimensions >> 29 != 0):
            return None
        return data
    except (OSError, ValueError, TypeError):
        return None


def clear_cache():
    _load_manifest.cache_clear()
    _image_bytes.cache_clear()


def image_bytes(art):
    """Return bounded, hash-checked bundled WebP bytes; no URL is fetched."""
    record = _record(art)
    if record is None:
        return None
    base_pin = APPROVED_BASE_IMAGES.get(record["asset_id"])
    build_pin = (record["asset_id"], record["prefix"], record["sha256"])
    if (base_pin != (record["prefix"], record["name"], record["sha256"])
            and build_pin not in APPROVED_BUILD_IMAGES.values()):
        return None
    return _image_bytes(str(BUNDLE_ROOT), str(IMAGE_DIR), record["filename"], record["sha256"],
                        record["width"], record["height"])


def get_art(weapon, *, build_code=None):
    """Prefer an exact reviewed code; other builds receive a labelled base image."""
    if (not isinstance(weapon, dict) or weapon.get("game", "mw4") != "mw4"
            or weapon.get("kind", "weapon") != "weapon"):
        return None
    asset = weapon.get("asset_id")
    if not isinstance(asset, str) or not _ASSET.fullmatch(asset):
        return None
    bases, builds = _load_manifest(str(BUNDLE_ROOT), str(MANIFEST_PATH))
    base = bases.get(asset)
    if base is None or ("prefix" in weapon and weapon["prefix"] != base["prefix"]):
        return None
    exact = builds.get(build_code) if isinstance(build_code, str) else None
    choices = [(exact, "native_build"), (base, "native_base")]
    for record, kind in choices:
        if record is None or record["asset_id"] != asset or image_bytes(record) is None:
            continue
        result = deepcopy(record)
        result.update({"kind": kind, "game": "mw4", "provider": "COD Hub native renders",
                       "image_url": PUBLIC_BASE_URL + record["filename"],
                       "caption": "Native attachment preview" if kind == "native_build" else "Native base-weapon preview",
                       "credit_text": "Call of Duty / Activision", "credit_url": "https://www.callofduty.com/",
                       "scope_text": "Primary components; camos and charms not shown.",
                       "full_game_shader_camo_parity": False})
        return result
    return None
