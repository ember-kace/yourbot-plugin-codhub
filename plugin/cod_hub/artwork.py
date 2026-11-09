"""Curated base-weapon image URLs; no network, image decoding or fuzzy joins."""
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path
import re
from .urls import split_https


MANIFEST_PATH = Path(__file__).parent / "data/artwork.json"
MAX_MANIFEST_BYTES = 100_000
_ASSET_ID = re.compile(r"[0-9a-f]{16}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_IMAGE_PATH = re.compile(r"/icons/mw4--([a-z0-9]+(?:-[a-z0-9]+)*)\.webp\Z")
_SOURCE_PATH = re.compile(r"/modernwarfare4/weapons/([a-z0-9]+(?:-[a-z0-9]+)*)\Z")
_CDN_HOST = "oyozmuwtlqoyrsfvyorw.supabase.co"
_CDN_IMAGE_PATH = re.compile(r"/storage/v1/object/public/weapon-icons/mw4--([a-z0-9]+(?:-[a-z0-9]+)*)\.webp\Z")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate artwork metadata key.")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("Non-finite artwork metadata number.")


def _url_path(value, host="metaradar.gg"):
    if (not isinstance(value, str) or not value or len(value) > 2048
            or any(ord(char) <= 32 or ord(char) == 127 for char in value)
            or "?" in value or "#" in value or "\\" in value):
        return None
    try:
        parsed = split_https(value)
        if (parsed.scheme != "https" or parsed.hostname != host
                or parsed.username is not None or parsed.password is not None
                or parsed.port not in (None, 443) or parsed.query or parsed.fragment):
            return None
        return parsed.path
    except (ValueError, TypeError):
        return None


def _image_slug(value):
    # One exact provider project/bucket, as published in the MW4 weapon index.
    # Arbitrary Supabase projects, buckets, paths and supplied URLs stay rejected.
    for host, pattern in (("metaradar.gg", _IMAGE_PATH), (_CDN_HOST, _CDN_IMAGE_PATH)):
        match = pattern.fullmatch(_url_path(value, host) or "")
        if match:
            return match.group(1)
    return None


def _record(asset_id, item, credit_url):
    if not isinstance(asset_id, str) or not _ASSET_ID.fullmatch(asset_id) or not isinstance(item, dict):
        return None
    image_slug = _image_slug(item.get("image_url"))
    source_path = _url_path(item.get("source_page"))
    source = _SOURCE_PATH.fullmatch(source_path or "")
    if not image_slug or not source or image_slug != source.group(1):
        return None
    if (not isinstance(item.get("sha256"), str) or not _SHA256.fullmatch(item["sha256"])
            or item.get("format") != "WEBP" or item.get("mode") != "RGBA"
            or type(item.get("width")) is not int or not 1 <= item["width"] <= 1024
            or type(item.get("height")) is not int or not 1 <= item["height"] <= 1024):
        return None
    alpha = item.get("alpha_extrema")
    if (not isinstance(alpha, list) or len(alpha) != 2
            or any(type(number) is not int for number in alpha) or alpha != [0, 255]):
        return None
    name = item.get("name")
    if (not isinstance(name, str) or not name.strip() or len(name) > 160
            or any(ord(char) < 32 or ord(char) == 127 for char in name)):
        return None
    return {"asset_id": asset_id, "provider": "MetaRadar", "game": "mw4", "name": name,
            "image_url": item["image_url"], "source_page": item["source_page"],
            "sha256": item["sha256"], "width": item["width"], "height": item["height"],
            "format": "WEBP", "mode": "RGBA", "alpha_extrema": [0, 255],
            "credit_text": "Data by MetaRadar", "credit_url": credit_url}


@lru_cache(maxsize=1)
def _load_manifest(path):
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(MAX_MANIFEST_BYTES + 1)
        if not raw or len(raw) > MAX_MANIFEST_BYTES:
            return {}
        data = json.loads(raw.decode("utf8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        if (not isinstance(data, dict) or type(data.get("format_version")) is not int
                or data["format_version"] != 1 or data.get("game") != "mw4"
                or data.get("provider") != "MetaRadar" or data.get("credit_text") != "Data by MetaRadar"
                or _url_path(data.get("credit_url")) != "/modernwarfare4/meta"
                or not isinstance(data.get("images"), dict) or len(data["images"]) > 128):
            return {}
        approved = {}
        for asset_id, item in data["images"].items():
            record = _record(asset_id, item, data["credit_url"])
            if record is not None:
                approved[asset_id] = record
        return approved
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        return {}


def clear_cache():
    """Reset metadata after changing a test fixture; deployed data is read-only."""
    _load_manifest.cache_clear()


def get_weapon_art(weapon):
    """Resolve only an exact asset ID from the curated MW4 weapon manifest."""
    if (not isinstance(weapon, dict) or weapon.get("game", "mw4") != "mw4"
            or weapon.get("kind", "weapon") != "weapon"):
        return None
    asset_id = weapon.get("asset_id")
    if not isinstance(asset_id, str) or not _ASSET_ID.fullmatch(asset_id):
        return None
    record = _load_manifest(str(MANIFEST_PATH)).get(asset_id)
    return deepcopy(record) if record is not None else None


def _other_text_length(embed):
    total = len(str(embed.get("title") or ""))
    for parent, child in (("footer", "text"), ("author", "name")):
        item = embed.get(parent)
        if isinstance(item, dict):
            total += len(str(item.get(child) or ""))
    fields = embed.get("fields")
    if isinstance(fields, list):
        for field in fields:
            if isinstance(field, dict):
                total += len(str(field.get("name") or "")) + len(str(field.get("value") or ""))
    return total


def decorate_embed(embed, weapon):
    """Copy a card and append credited base-weapon art when an exact match exists."""
    result = deepcopy(embed) if isinstance(embed, dict) else {}
    art = get_weapon_art(weapon)
    if art is None:
        return result
    credit = "[Base weapon image](" + art["source_page"] + ") · [Data by MetaRadar](" + art["credit_url"] + ")"
    budget = min(4096, 6000 - _other_text_length(result))
    if budget < len(credit):
        # Do not display uncredited artwork when a caller supplies an already
        # overfull embed. Existing text remains available without an image.
        return result
    description = str(result.get("description") or "")
    if description.endswith(credit):
        description = description[:-len(credit)].rstrip()
    if description:
        description = description[:max(0, budget - len(credit) - 2)].rstrip()
    result["description"] = (description + "\n\n" if description else "") + credit
    result["image"] = {"url": art["image_url"]}
    return result
