"""Bounded, source-counted MW4 item browsing over independently checked shards."""
from copy import deepcopy
from functools import lru_cache
import hashlib
import heapq
import json
from pathlib import Path, PurePosixPath
import re
import stat
import unicodedata


DATA = Path(__file__).parent / "data"
MANIFEST_PATH = DATA / "item-catalog.json"
MAX_MANIFEST_BYTES = 150_000
MAX_SHARD_BYTES = 1_000_000
MAX_RECORDS = 20_000
_KIND = re.compile(r"[a-z][a-z0-9_]{0,39}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_NAME_HASH = re.compile(r"[0-9a-f]{16}\Z")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
LABELS = {
    "weapon": "Weapons and blueprints", "attachment": "Attachments", "camo": "Camos",
    "weapon_charm": "Weapon charms", "sticker": "Stickers", "reticle": "Reticles",
    "operator": "Operators", "operator_skin": "Operator skins", "executions": "Finishing moves",
    "equipment": "Equipment", "perk": "Perks", "killstreak": "Killstreaks", "super": "Field upgrades",
    "progression": "Progression", "levelicon": "Level icons", "prestigemastercolor": "Prestige colors",
    "playercards": "Calling cards", "playercardtitle": "Player titles", "emblems": "Emblems",
    "spray": "Sprays", "vehicle_camo": "Vehicle camos", "battlepass": "Battle pass records",
    "loadingscreen": "Loading screens", "clantag": "Clan tags", "calloutmarkerpingitem": "Pings",
    "consumable": "Consumables", "contrail": "Contrails", "emotes": "Emotes",
    "parachute": "Parachutes", "feature": "Feature records", "sentinel": "Other native records",
}
_ORDER = {kind: index for index, kind in enumerate(LABELS)}


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate item catalog metadata.")
        result[key] = value
    return result


def _read(relative, maximum):
    if (not isinstance(relative, str) or "\\" in relative or ":" in relative
            or PurePosixPath(relative).is_absolute() or any(part in {"", ".", ".."} for part in relative.split("/"))):
        raise ValueError("Invalid item catalog resource.")
    root = Path(DATA).absolute()
    path = root / relative
    if Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ValueError("Invalid item catalog resource.")
    current = root
    for part in (None, *Path(relative).parts):
        if part is not None:
            current /= part
        info = current.lstat()
        if (stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
            raise ValueError("Linked item catalog resource.")
    if not path.resolve(strict=True).is_relative_to(root.resolve(strict=True)):
        raise ValueError("Invalid item catalog resource.")
    with path.open("rb") as stream:
        data = stream.read(maximum + 1)
    if not data or len(data) > maximum:
        raise ValueError("Item catalog resource exceeds its limit.")
    return data


def _document(raw):
    def reject(value):
        raise ValueError("Invalid item catalog number.")
    return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique, parse_constant=reject)


def display_name(item):
    """Present exact context labels without assigning a false canonical name."""
    if item.get("name_source") != "native_context_labels":
        return item.get("name")
    labels = item.get("display_labels")
    if item.get("name") is not None or not isinstance(labels, list) or not 2 <= len(labels) <= 6:
        raise ValueError("Invalid native context labels.")
    names = []
    for label in labels:
        if (not isinstance(label, dict) or set(label) != {"name", "name_hash", "context_ids"}
                or not isinstance(label["name"], str) or not label["name"].strip() or len(label["name"]) > 150
                or not isinstance(label["name_hash"], str) or not _NAME_HASH.fullmatch(label["name_hash"])
                or not isinstance(label["context_ids"], list) or not 1 <= len(label["context_ids"]) <= 100
                or any(not isinstance(value, str) or not _HASH.fullmatch(value) for value in label["context_ids"])):
            raise ValueError("Invalid native context label evidence.")
        names.append(label["name"])
    if len(set(names)) != len(names):
        raise ValueError("Duplicate native context label.")
    return " / ".join(names)


@lru_cache(maxsize=1)
def _manifest(root, path):
    relative = Path(path).absolute().relative_to(Path(root).absolute()).as_posix()
    data = _document(_read(relative, MAX_MANIFEST_BYTES))
    if (not isinstance(data, dict) or data.get("format_version") != 1
            or type(data.get("format_version")) is not int or data.get("game") != "mw4"
            or not isinstance(data.get("snapshot_date"), str) or not _DATE.fullmatch(data["snapshot_date"])
            or not isinstance(data.get("categories"), dict) or not 1 <= len(data["categories"]) <= 100):
        raise ValueError("The MW4 item catalog is unavailable. Open Weapons or try again later.")
    total = 0
    for kind, category in data["categories"].items():
        if (not isinstance(kind, str) or not _KIND.fullmatch(kind) or not isinstance(category, dict)
                or not isinstance(category.get("shards"), list) or len(category["shards"]) > 1000):
            raise ValueError("Invalid item catalog category.")
        for key in ("total", "resolved", "held", "source_internal"):
            if type(category.get(key)) is not int or not 0 <= category[key] <= 100_000:
                raise ValueError("Invalid item catalog coverage.")
        if category["total"] != category["resolved"] + category["held"] + category["source_internal"]:
            raise ValueError("Item catalog coverage does not reconcile.")
        count = 0
        for index, shard in enumerate(category["shards"]):
            if (not isinstance(shard, dict) or not isinstance(shard.get("sha256"), str)
                    or not _HASH.fullmatch(shard["sha256"])
                    or shard.get("file") != f"items/{kind}-{index:03d}-{shard['sha256']}.json"
                    or type(shard.get("count")) is not int or not 1 <= shard["count"] <= 100):
                raise ValueError("Invalid item catalog shard.")
            count += shard["count"]
        if count != category["total"]:
            raise ValueError("Item catalog shard counts do not reconcile.")
        total += count
    if (type(data.get("native_records")) is not int or data["native_records"] != total
            or not 1 <= total <= MAX_RECORDS):
        raise ValueError("Item catalog totals do not reconcile.")
    return data


@lru_cache(maxsize=2)
def _shard(root, kind, descriptor_json):
    descriptor = json.loads(descriptor_json)
    raw = _read(descriptor["file"], MAX_SHARD_BYTES)
    if hashlib.sha256(raw).hexdigest() != descriptor["sha256"]:
        raise ValueError("The item catalog failed its integrity check.")
    items = _document(raw)
    if not isinstance(items, list) or len(items) != descriptor["count"]:
        raise ValueError("Invalid item catalog shard contents.")
    seen = set()
    for item in items:
        if (not isinstance(item, dict) or type(item.get("id")) is not int
                or not 0 <= item["id"] < 2**31 or item["id"] in seen or item.get("kind") != kind
                or item.get("status") not in {"resolved", "held", "source_internal"}):
            raise ValueError("Invalid item catalog identity.")
        seen.add(item["id"])
        name = display_name(item)
        if item["status"] == "resolved" and (
                not isinstance(name, str) or not name.strip() or len(name) > 1000
                or item.get("quality") != "native_localization"):
            raise ValueError("An item has no verified English name.")
        for key, maximum in (("internal_ref", 1000), ("description", 8000), ("unlock", 8000), ("season", 100)):
            value = item.get(key)
            if value is not None and (not isinstance(value, str) or len(value) > maximum):
                raise ValueError("Invalid item catalog text.")
    return items


def clear_cache():
    _manifest.cache_clear()
    _shard.cache_clear()


def manifest():
    try:
        return _manifest(str(DATA), str(MANIFEST_PATH))
    except (OSError, UnicodeError, TypeError, KeyError, RecursionError) as error:
        raise ValueError("The MW4 item catalog is unavailable. Open Weapons or try again later.") from error


def categories():
    data = manifest()
    return [dict(key=kind, label=LABELS.get(kind, kind.replace("_", " ").title()),
                 **{key: category[key] for key in ("total", "resolved", "held", "source_internal")})
            for kind, category in sorted(data["categories"].items(),
                                        key=lambda row: (_ORDER.get(row[0], 1000), row[0]))]


def _normalize(value):
    value = unicodedata.normalize("NFKD", value.casefold())
    return " ".join("".join(char if char.isalnum() else " " for char in value
                            if not unicodedata.combining(char)).split())


def _query(value):
    if not isinstance(value, str) or len(value) > 100:
        raise ValueError("Search with up to 100 characters.")
    return _normalize(value)


def _items(kind):
    data = manifest()
    if not isinstance(kind, str):
        raise ValueError("Choose a category from the catalog.")
    kinds = [kind] if kind != "all" else [row["key"] for row in categories()]
    if any(key not in data["categories"] for key in kinds):
        raise ValueError("Choose a category from the catalog.")
    for key in kinds:
        for index, descriptor in enumerate(data["categories"][key]["shards"]):
            for item in _shard(str(DATA), key, json.dumps(descriptor, sort_keys=True)):
                if item["status"] == "resolved":
                    yield item, index


def browse(kind="all", query="", page=1, page_size=10):
    if type(page) is not int or not 1 <= page <= 10000 or type(page_size) is not int or not 1 <= page_size <= 25:
        raise ValueError("Choose a valid catalog page.")
    query = _query(query)
    count = 0

    def matching():
        nonlocal count
        for item, index in _items(kind):
            label = display_name(item)
            name = _normalize(label)
            words = _normalize(str(item.get("internal_ref") or "")[:1000])
            if query and not all(word in name or word in words or word == str(item["id"]) for word in query.split()):
                continue
            count += 1
            score = 0 if query and name == query else 1 if query and name.startswith(query) else 2
            yield (score, name, item["id"], {"id": item["id"], "name": label,
                                          "kind": item["kind"], "shard": index})

    selected = heapq.nsmallest(page * page_size, matching(), key=lambda row: row[:3])
    pages = max(1, (count + page_size - 1) // page_size)
    if page > pages:
        raise ValueError("That item catalog page doesn't exist.")
    data = manifest()
    return {"items": [row[3] for row in selected[(page - 1) * page_size:page * page_size]],
            "kind": kind, "query": query, "page": page, "pages": pages, "total": count,
            "native_records": data["native_records"], "snapshot_date": data["snapshot_date"]}


def get_item(kind, shard, identifier):
    data = manifest()
    if (not isinstance(kind, str) or kind not in data["categories"] or type(shard) is not int
            or not 0 <= shard < len(data["categories"][kind]["shards"]) or type(identifier) is not int):
        raise ValueError("Open an item from the catalog.")
    descriptor = data["categories"][kind]["shards"][shard]
    for item in _shard(str(DATA), kind, json.dumps(descriptor, sort_keys=True)):
        if item["id"] == identifier and item["status"] == "resolved":
            result = deepcopy(item)
            result["snapshot_date"] = data["snapshot_date"]
            return result
    raise ValueError("That item isn't available in this catalog view.")
