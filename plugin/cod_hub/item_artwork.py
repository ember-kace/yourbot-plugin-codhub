"""Fixed-host native item artwork URLs; no image fetches during interaction handling."""
from functools import lru_cache
import json
from pathlib import Path
import re
import stat


DATA = Path(__file__).parent / "data"
INDEX_PATH = DATA / "item-artwork.json"
HOST = "https://ember-kace.github.io/yourbot-plugin-codhub/artwork/items/v1/"
MAX_INDEX_BYTES = 2_000_000
_ASSET = re.compile(r"[0-9a-f]{16}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate item artwork metadata.")
        result[key] = value
    return result


@lru_cache(maxsize=1)
def _index(root, filename):
    root, path = Path(root).absolute(), Path(filename).absolute()
    if path.parent != root:
        raise ValueError("Invalid native item artwork resource.")
    for checked in (root, path):
        info = checked.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            raise ValueError("Linked native item artwork resource.")
    with path.open("rb") as stream:
        raw = stream.read(MAX_INDEX_BYTES + 1)
    if not 0 < len(raw) <= MAX_INDEX_BYTES:
        raise ValueError("Native item artwork index exceeds its limit.")
    data = json.loads(raw.decode("utf8"), object_pairs_hook=_unique)
    if (not isinstance(data, dict) or type(data.get("format_version")) is not int or data["format_version"] != 1
            or data.get("game") != "mw4" or not isinstance(data.get("images"), dict)
            or not 1 <= len(data["images"]) <= 10000 or not isinstance(data.get("by_asset"), dict)
            or len(data["by_asset"]) > 20000):
        raise ValueError("Invalid native item artwork index.")
    for identity, record in data["images"].items():
        if (not _ASSET.fullmatch(identity) or not isinstance(record, dict) or record.get("image_asset_id") != identity
                or not isinstance(record.get("sha256"), str) or not _HASH.fullmatch(record["sha256"])
                or record.get("filename") != record["sha256"] + ".webp" or record.get("format") != "WEBP"
                or record.get("lossless") is not True
                or any(type(record.get(key)) is not int or not 1 <= record[key] <= 16384 for key in ("width", "height"))
                or record["width"] * record["height"] > 16 * 1024 * 1024):
            raise ValueError("Invalid native item artwork identity.")
        scope = record.get("scope", "native_item_artwork")
        if scope not in {"native_item_artwork", "native_part_preview"}:
            raise ValueError("Invalid native item artwork scope.")
        if scope == "native_part_preview" and (record.get("canonical_full_image") is not False
                or type(record.get("part_index")) is not int or record["part_index"] != 0):
            raise ValueError("Invalid native static preview scope.")
    if any(not _ASSET.fullmatch(identity) or image not in data["images"] for identity, image in data["by_asset"].items()):
        raise ValueError("Invalid native item artwork association.")
    return data


def clear_cache():
    _index.cache_clear()


def get_art(item):
    if not isinstance(item, dict):
        return None
    try:
        data = _index(str(DATA), str(INDEX_PATH))
        identity = item.get("image_asset_id")
        if identity is None:
            asset = item.get("asset_id")
            identity = data["by_asset"].get(asset) if isinstance(asset, str) else None
        record = data["images"].get(identity) if isinstance(identity, str) else None
        if record is None:
            return None
        return {"url": HOST + record["filename"], "width": record["width"], "height": record["height"],
                "scope": record.get("scope", "native_item_artwork"), "image_asset_id": identity}
    except (ValueError, OSError, UnicodeError, TypeError, KeyError, RecursionError):
        return None


def decorate_embed(embed, item):
    artwork = get_art(item)
    if artwork:
        destination = "image" if item.get("kind") in {"playercards", "loadingscreen"} else "thumbnail"
        embed[destination] = {"url": artwork["url"]}
        footer = dict(embed.get("footer") or {})
        credit = "Native artwork: Call of Duty / Activision"
        footer["text"] = (str(footer.get("text") or "")[:1800] + " · " + credit).lstrip(" ·")
        embed["footer"] = footer
        if artwork["scope"] == "native_part_preview":
            text = embed.get("description", "")
            embed["description"] = (text[:3900] + "\n\nStatic native artwork preview.").lstrip()
    return embed
