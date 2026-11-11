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
APPROVED_BASE_IMAGES = {'07f7d22f45558288': ('B03', 'Cronen Squall', 'ccd54ae9fcd5bd05e82a15777e0434cbbe27f12f80320e8856c45ffe70383a6c'),
 '094574f827113d6d': ('M03', 'Mosin-Nagant', '6ccb90ac10c29a8fda29a10be6477895330c3f6a5c0cc68ebc77f9148edad8a6'),
 '0acd07c3fd30e85a': ('S05', 'PPSh-41', '0978efaa1d1f212fc6f88df4abf3bf846f35b3d322d8fc65a811c5b6ffa521e8'),
 '12cf1c65abc24d34': ('P04', 'Sang 9mm', '320d185497c0a12cf70cec026ac20a88363c15a23a3948f8512439d963c0277a'),
 '160d15e6381d5cb5': ('S06', 'ISO Nightshade', '1fd65403d530169741e4d7131f2d673f75243802e74ac8ec554c2f0538900025'),
 '161f8341b23454de': ('S04', 'Wz.55 Striga', 'd46f713a29a422b30ae2f31f3779a4a7e384c6a399586cb8394a9a5646ae70bb'),
 '174ac9ebd217d177': (None, 'JOKR', 'c3a9f90c3c7d2ecd2fcc6f6485b776bf1ea2248f97e8378bfc5802e1bf71d92a'),
 '1f30c6b00e332af6': ('L03', 'FiNN LMG', 'c9e5ac055033bf54de38c23e1902735226b3ca7ab70802aae82e74041e28e8f1'),
 '2906672daed5983e': (None, 'RPG-8', 'e38320cf8d5a2aba929b78cca16abe4aec0ba1705fff6516dce5d72e71e826e7'),
 '2e05c75adfbfd24c': ('S01', 'CSG-35', 'ce8b17a020474777c28b1959989ffb0e17802df1f7c36f9ba88984dc6d5f6281'),
 '2efa8aea20d8b45d': ('P02', '.50 GS', 'eec3d5dc616ae65954bb3394003bba13859f0f0f97ae357c9c7903eccd580142'),
 '320bd7829fa4bdee': ('A01', 'Kastov 762', '64492959b90e99317cd46545597a3dd435d721388ec4b0ad8ca2b0fc4ba197fb'),
 '32f2e812899c570d': ('P03', 'Krait P68', 'a9e95298d49b81e8d2ddfb1c130e2417b821426c9fc9834a71780a9295335fd6'),
 '3313ea5514c15bbd': ('C03', 'Rezi 12', '83c238a081cb49eae5d40a63ee4f37f4ca6e9516b2887f17cb99fd30ffc5803d'),
 '3bfd017330a15574': ('B04', 'Patriot XMR', '2f01edbf6a834496d09c7da36c9a85cc897821bef3e4a3640ac95430213c4ca1'),
 '3ca278a99a9ab61d': ('M01', 'Oris 8.6', '435263f2869641be745ba01c09f241997798cb7e2db89c529bb1272ed779196a'),
 '437a2fe19197ce82': ('M02', 'MAR-9', 'dd5e7dcbef3ea9716555b8b04920478c2deb478327a93606c93d9e411c42fb5e'),
 '43f5901edb8e5875': ('R02', 'Signal 50', '56b214c0e6d96dc3be896a021bcca339c75bfa43217d9e01844340a3f8b87b46'),
 '49c1b0190d746a45': (None, 'PILA', '7a16d298dbb8b5b36cf3d28ceba4f44e7caab0240dc721804e7ad15bb69f7c6c'),
 '4b0393a280f71061': (None, 'PM-40 Anvil', '51c93d7dcdc295ad3ed07d441e4d1b710786b0645d66f0a7a68502af91b85295'),
 '50a03474c191ed85': ('B01', 'Oden', '6d3eb81bf5b5b7ef27d5039a8e3a42fe37e5d3c751a9c72ceb49018644ccb7c6'),
 '547541041d63934d': (None,
                      'FSS Carbon Edge 1095',
                      'b752deca280174780e93a7169062ee070ff5d274fc63107b6bde0335e86c141a'),
 '54efea11f28407ea': ('A05', 'M4', 'd8132db7a331638cdb7b9f7907180527d4a5d5a068097a32dea92da3c5a4d0f6'),
 '58b2312b43165b66': ('S08', 'X-58 Nyx', '8460226d213acea03b6c9de8ee601759f65da8b4f9086949f9ff0518c4c40ae7'),
 '62f36eea38527995': ('S03', 'VEL 46', '95ab0b43d11c4ee96a901f9320a1252925bb2f28fe164c39ae363da9156efcb9'),
 '63845ab500bcb133': ('R03', 'Astaroth .57', 'e0691d0a3b9a8e28528910fda21fac93921f21fa7bcdb981e506783f629e7400'),
 '66bbbb111859e8e1': ('P07', 'Mojave .357', '870fb4ee16932ef1c737f645e517a22a12f5ff19f11f5faa08401e5276bf2d15'),
 '68441ea783099179': ('A03', 'Han 86', '0dcbfb56e025b637638c6f36a11f7afe641e8b52277f63926290ed198221a9a8'),
 '6cc4eea570f88e27': ('L02', 'APOC-338', 'c9905b190c6dd0c7bbbdb61121cbe3ca3030c9adaf79d8c256b40c47081ba449'),
 '6d470118a56e6da9': ('A04', 'Axion', 'e276af45eb84845ded001632d281c472b60390879e54c4b3f412504c61cbae01'),
 '6d7160ae60292b75': ('A02', 'Cronen Osprey', '58b294833861d9152d65b8fa76eddac618cb83f7445e66de6606805879df91c3'),
 '73ca8d7b9145bb65': ('R04', 'KG-7 Vulcan', '6c9728c1b7923242ddef85dd1d210e7f81bbfa93b8ac0ea77a8325667a5a71af'),
 '7574652bd34cc3f6': ('C04', 'Warlord', 'b6a992951221c9240820b8f1f27ba7f6cf5cc6322430f81ad819ab78ecd08962'),
 '75bd0537aaa182c3': ('L04', 'Type 73', 'd086785a7348ebbc6e362971b0144d26da58ad4f3641cbe5f75760f92f51b6fa'),
 '7973ece25ffff326': ('A09', 'Hyeon Burst', '56ed822e7a560dc9b08f3c7efc3d8384652e731a56a3b910b2fb6ee8ee3ca211')}
APPROVED_BUILD_IMAGES = {
    "A01-42J19-BU11": ("320bd7829fa4bdee", "A01", "ce391668130198680dfbe2533f48ff929be2457339e0d72370fbbe8d17f1db88"),
    "A01-A11NP-B11": ("320bd7829fa4bdee", "A01", "c568f0fb21711798793b1b8fee00240cf14edca7cda9b89f3559e5277ed0beac"),
    "A01-9YGBJ-D11": ("320bd7829fa4bdee", "A01", "b59cf09a211917bd3e1f5400291a69456dc8762d4e29c82f3bc3e365620323a4"),
}
APPROVED_PREVIEW_KINDS = {'07f7d22f45558288': 'static_default',
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
PREVIEW_KINDS = {
    "primary_components": ("Native base-weapon preview", "Primary components; camos and charms not shown."),
    "static_default": ("Native static weapon reference", "Source-selected static components; camos and charms not shown."),
    "shader_simplified": ("Native static weapon reference", "Source-selected static components. Lens shaders simplified. Camos and charms not shown."),
    "folded_reference": ("Native folded reference", "Source-defined folded model; not the active weapon or selected build."),
    "world_model": ("Native world-model reference", "Source-defined world model; not the selected build."),
    "native_item_icon": ("Native weapon icon", "Native catalog artwork; not a rendered build."),
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
            or (prefix is not None and (not isinstance(prefix, str) or not _PREFIX.fullmatch(prefix)))
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
    kind = item.get("preview_kind", "primary_components")
    if kind not in PREVIEW_KINDS:
        return None
    return {"preview_kind": kind, **{key: deepcopy(item[key]) for key in (
        "asset_id", "prefix", "name", "sha256", "filename", "format", "mode",
        "lossless", "width", "height", "alpha_extrema")}}


@lru_cache(maxsize=1)
def _load_manifest(root, path):
    try:
        data = json.loads(_read_member(root, path, MAX_MANIFEST_BYTES).decode("utf8"),
                          object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        if (not isinstance(data, dict) or type(data.get("format_version")) is not int
                or data["format_version"] != 1 or data.get("game") != "mw4"
                or data.get("provider") != "COD Hub native renders"
                or data.get("scope") not in {"primary_components", "reviewed_native_references"}
                or data.get("full_game_shader_camo_parity") is not False
                or not isinstance(data.get("base_images"), dict) or len(data["base_images"]) > 128
                or not isinstance(data.get("build_images"), dict) or len(data["build_images"]) > 512):
            return {}, {}
        bases, builds, prefixes = {}, {}, set()
        for asset, item in data["base_images"].items():
            record = _record(item)
            if (record is not None and record["asset_id"] == asset
                    and APPROVED_BASE_IMAGES.get(asset) == (record["prefix"], record["name"], record["sha256"])
                    and record["preview_kind"] == APPROVED_PREVIEW_KINDS.get(asset, "primary_components")):
                if record["prefix"] is not None and record["prefix"] in prefixes:
                    return {}, {}
                if record["prefix"] is not None:
                    prefixes.add(record["prefix"])
                bases[asset] = record
        for code, item in data["build_images"].items():
            record = _record(item)
            if (record is None or not isinstance(code, str) or not _CODE.fullmatch(code)
                    or len(code) > 25 or item.get("build_code") != code
                    or not isinstance(record["prefix"], str) or not code.startswith(record["prefix"] + "-")
                    or record["preview_kind"] != "primary_components"
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
    if (base_pin == (record["prefix"], record["name"], record["sha256"])
            and record["preview_kind"] != APPROVED_PREVIEW_KINDS.get(record["asset_id"], "primary_components")):
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
                       "caption": "Native attachment preview" if kind == "native_build" else PREVIEW_KINDS[record["preview_kind"]][0],
                       "credit_text": "Call of Duty / Activision", "credit_url": "https://www.callofduty.com/",
                       "scope_text": "Primary components; camos and charms not shown." if kind == "native_build" else PREVIEW_KINDS[record["preview_kind"]][1],
                       "full_game_shader_camo_parity": False})
        return result
    return None
