"""Bounded offline native map and challenge references, separate from loot IDs."""
from collections import Counter
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import stat
import unicodedata


DATA = Path(__file__).parent / "data"
MAX_DATA_BYTES = 2_000_000
MAX_SOURCE_BYTES = 10_000
MAX_QUERY = 36
SOURCE_ID = "mw4-current-native-guide-2026-11-11"
SNAPSHOT = "2026-11-11"
TABLE_SOURCE_SHA256 = "2c4d7afa41c08fab3f8a3015851a4895b8d19280be9507d8867f4e7aa86c8854"
TABLE_KINDS = {
    "3717489cf4f58cbe": "map", "1a7b5f69c5b97ba3": "warzone_daily_challenge",
    "774f3e0caf169670": "multiplayer_daily_challenge", "45df53d00b45fc22": "calling_card_challenge",
    "47b30954dda595bd": "weapon_mastery_track", "0b04010c6c8c035c": "dmz_faction_mission",
    "5b9214c3d6bc1341": "seasonal_event_reference", "507e2b0f4a1993e5": "seasonal_event_reference",
}
CATEGORIES = {
    "maps": ("Maps", {"map"}),
    "mp_daily": ("Multiplayer daily challenges", {"multiplayer_daily_challenge"}),
    "wz_daily": ("Warzone daily challenges", {"warzone_daily_challenge"}),
    "calling_cards": ("Calling card challenges", {"calling_card_challenge"}),
    "mastery": ("Weapon mastery", {"weapon_mastery_track"}),
    "dmz": ("DMZ missions", {"dmz_faction_mission"}),
    "events": ("Seasonal event references", {"seasonal_event_reference"}),
}
_REF = re.compile(r"g([0-9a-f]{16})r(0|[1-9][0-9]{0,4})\Z")
_HASH16 = re.compile(r"[0-9a-f]{16}\Z")
_HASH64 = re.compile(r"[0-9a-f]{64}\Z")
_UNEXPANDED = re.compile(r"&&\d+|#x[0-9a-fA-F]{8,}|\^|%(?:\d+\$)?[-+0-9.]*[sdiufegx]|<[^>]+>|\{[^}]*\}", re.I)
_DESCRIPTION_STATES = {"not_in_table_schema", "source_static_text", "source_template_operands_uninterpreted",
                       "requires_native_formatting", "absent_native_reference", "unresolved_native_reference",
                       "withheld_native_placeholder"}
_ROW_FIELDS = {"id", "kind", "native_id", "name", "name_hash", "quality", "description_hash",
               "description_template", "description_display", "description_status", "status", "held_reason",
               "source_table_hash", "source_row", "source_ids", "internal_ref", "scope", "native_operands",
               "native_operand_columns", "operand_semantics"}
_LIMITS = {"all_native_guide_tables_exhaustive": False, "player_progress_known": False,
           "current_rotation_verified": False, "operand_meanings_verified": False,
           "achievement_to_loot_joins_inferred": False}


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate game guide metadata.")
        result[key] = value
    return result


def _document(raw):
    def invalid(_):
        raise ValueError("Invalid game guide number.")
    return json.loads(raw.decode("utf8"), object_pairs_hook=_unique, parse_constant=invalid)


def _read(name, maximum):
    if name not in {"native-guide.json", "native-guide-sources.json"}:
        raise ValueError("Invalid game guide resource.")
    root = Path(DATA).absolute()
    path = root / name
    for target in (root, path):
        info = target.lstat()
        if (stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
            raise ValueError("Linked game guide resource.")
    if not stat.S_ISREG(info.st_mode) or not path.resolve(strict=True).is_relative_to(root.resolve(strict=True)):
        raise ValueError("Invalid game guide resource.")
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    if not 1 <= len(raw) <= maximum:
        raise ValueError("Game guide resource exceeds its limit.")
    return raw


def _text(value, maximum, *, required=False):
    return (value is None and not required) or (
        isinstance(value, str) and len(value) <= maximum and (bool(value.strip()) or not required)
        and not any(unicodedata.category(c).startswith("C") or unicodedata.category(c) in {"Zl", "Zp"} for c in value))


def _named(value):
    return (_text(value, 160, required=True) and re.search(r"[A-Za-z]", value)
            and not _UNEXPANDED.search(value) and "_" not in value
            and not re.search(r"\b(?:unknown|placeholder|unresolved|todo|tbd|null|undefined)\b", value, re.I)
            and not value.lstrip().startswith("#PH:"))


def validate_document(data):
    """Validate normalized metadata; release tooling separately pins exact bytes."""
    fields = {"format_version", "game", "snapshot_date", "source_id", "coverage", "description_coverage", "limits", "items"}
    if (not isinstance(data, dict) or set(data) != fields or type(data.get("format_version")) is not int
            or data["format_version"] != 1 or data.get("game") != "mw4" or data.get("snapshot_date") != SNAPSHOT
            or data.get("source_id") != SOURCE_ID or data.get("limits") != _LIMITS
            or not isinstance(data.get("items"), dict) or not 1 <= len(data["items"]) <= 2000):
        raise ValueError("Invalid native game guide document.")
    counts, descriptions, table_rows = Counter(), Counter(), set()
    for identifier, row in data["items"].items():
        match = _REF.fullmatch(identifier) if isinstance(identifier, str) else None
        if (not match or not isinstance(row, dict) or set(row) - _ROW_FIELDS or row.get("id") != identifier
                or row.get("source_table_hash") not in TABLE_KINDS
                or row.get("kind") != TABLE_KINDS[row["source_table_hash"]]
                or type(row.get("source_row")) is not int or not 0 <= row["source_row"] < 100000
                or identifier != f"g{row['source_table_hash']}r{row['source_row']}"
                or row.get("source_ids") != [SOURCE_ID] or row.get("status") not in {"resolved", "held"}
                or not _text(row.get("native_id"), 160, required=True)
                or not _text(row.get("internal_ref"), 500, required=True)
                or not _text(row.get("scope"), 500, required=True)
                or not isinstance(row.get("name_hash"), str) or not _HASH16.fullmatch(row["name_hash"])):
            raise ValueError("Invalid game guide source reference.")
        coordinate = (row["source_table_hash"], row["source_row"])
        if coordinate in table_rows:
            raise ValueError("Duplicate game guide source row.")
        table_rows.add(coordinate)
        if row["status"] == "resolved":
            if (not _named(row.get("name")) or row.get("quality") != "native_localization"
                    or row.get("held_reason") is not None or row["internal_ref"].startswith("mp_frontend")
                    or (row["kind"] != "map" and ("test" in row["internal_ref"].lower()
                        or row["name"].lower().startswith("test code")))):
                raise ValueError("The game guide contains an unverified display name.")
        elif (row.get("name") is not None or row.get("quality") is not None
              or not _text(row.get("held_reason"), 500, required=True)):
            raise ValueError("A held guide reference cannot have a display name.")
        state = row.get("description_status")
        desc_hash = row.get("description_hash")
        if (state not in _DESCRIPTION_STATES or not _text(row.get("description_template"), 8000)
                or not _text(row.get("description_display"), 8000)
                or (desc_hash is not None and (not isinstance(desc_hash, str) or not _HASH16.fullmatch(desc_hash)))):
            raise ValueError("Invalid game guide description.")
        if state == "source_static_text":
            value = row.get("description_display")
            if (not _text(value, 8000, required=True) or value != row.get("description_template")
                    or _UNEXPANDED.search(value) or value.lstrip().startswith("#PH:") or "do not ship" in value.lower()):
                raise ValueError("A game guide instruction requires native formatting.")
        elif row.get("description_display") is not None:
            raise ValueError("Uninterpreted native requirements cannot become instructions.")
        if row["kind"] != "map":
            operands, columns = row.get("native_operands"), row.get("native_operand_columns")
            if (row.get("operand_semantics") != "uninterpreted_native_cells"
                    or not isinstance(operands, list) or not 1 <= len(operands) <= 60
                    or any(not _text(v, 8000, required=False) or v is None for v in operands)
                    or not isinstance(columns, list) or len(columns) != len(operands)):
                raise ValueError("Invalid raw game guide operands.")
            for index, column in enumerate(columns, 4):
                if (not isinstance(column, dict) or set(column) != {"column", "native_type"}
                        or type(column.get("column")) is not int or column["column"] != index
                        or type(column.get("native_type")) is not int or column["native_type"] not in {1, 2, 11}):
                    raise ValueError("Invalid typed game guide operand.")
        elif any(key in row for key in ("native_operands", "native_operand_columns", "operand_semantics")):
            raise ValueError("Map references have no challenge operands.")
        counts[(row["kind"], "total")] += 1
        counts[(row["kind"], row["status"])] += 1
        descriptions[state] += 1
    kinds = {row["kind"] for row in data["items"].values()}
    expected = {kind: {state: counts[(kind, state)] for state in ("total", "resolved", "held")} for kind in kinds}
    if data.get("coverage") != expected or data.get("description_coverage") != dict(descriptions):
        raise ValueError("Game guide coverage does not reconcile.")
    return data


def validate_sources(sources, raw):
    if (not isinstance(sources, dict) or set(sources) != {"catalog_sha256", "catalog_records", "reference_id_scope", "sources"}
            or sources.get("catalog_sha256") != hashlib.sha256(raw).hexdigest()
            or type(sources.get("catalog_records")) is not int or not 1 <= sources["catalog_records"] <= 2000
            or sources.get("reference_id_scope") != "native_table_and_row_not_loot_id"
            or not isinstance(sources.get("sources"), dict) or set(sources["sources"]) != {SOURCE_ID}):
        raise ValueError("The game guide failed its integrity check.")
    record = sources["sources"][SOURCE_ID]
    if (not isinstance(record, dict) or record.get("kind") != "local_game_facts"
            or record.get("source_date") != SNAPSHOT or record.get("sha256") != TABLE_SOURCE_SHA256
            or record.get("table_hashes") != list(TABLE_KINDS)
            or not isinstance(record.get("english_source_sha256"), str)
            or not _HASH64.fullmatch(record["english_source_sha256"])
            or not _text(record.get("title"), 300, required=True) or not _text(record.get("scope"), 1000, required=True)):
        raise ValueError("Invalid current game guide provenance.")


@lru_cache(maxsize=1)
def _load(root):
    raw = _read("native-guide.json", MAX_DATA_BYTES)
    sources = _document(_read("native-guide-sources.json", MAX_SOURCE_BYTES))
    validate_sources(sources, raw)
    data = validate_document(_document(raw))
    if len(data["items"]) != sources["catalog_records"]:
        raise ValueError("Game guide totals do not reconcile.")
    return data


def clear_cache():
    _load.cache_clear()


def _data():
    try:
        return _load(str(DATA))
    except (OSError, UnicodeError, TypeError, KeyError, AttributeError, RecursionError) as error:
        raise ValueError("The offline game guide is unavailable. Try /codguide again later.") from error


def categories():
    data = _data()
    return [{"key": key, "label": label,
             **{state: sum(data["coverage"].get(kind, {}).get(state, 0) for kind in kinds)
                for state in ("total", "resolved", "held")}}
            for key, (label, kinds) in CATEGORIES.items()]


def normalize_query(value):
    if not isinstance(value, str) or len(value) > MAX_QUERY:
        raise ValueError(f"Search the guide with up to {MAX_QUERY} characters.")
    return _normalize(value)


def _normalize(value):
    value = unicodedata.normalize("NFKD", value.casefold()).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def browse(category="all", query="", page=1, page_size=10):
    if not isinstance(category, str) or category not in {"all", *CATEGORIES}:
        raise ValueError("Choose a game guide category.")
    if type(page) is not int or not 1 <= page <= 1000 or type(page_size) is not int or not 1 <= page_size <= 25:
        raise ValueError("Choose a valid game guide page.")
    query = normalize_query(query)
    data = _data()
    kinds = CATEGORIES[category][1] if category != "all" else set(TABLE_KINDS.values())
    rows = []
    for item in data["items"].values():
        if item["status"] != "resolved" or item["kind"] not in kinds:
            continue
        name = _normalize(item["name"])
        searchable = _normalize(item["name"] + " " + item["internal_ref"] + " " + item["id"])
        if query and not all(word in searchable for word in query.split()):
            continue
        score = 0 if query and name == query else 1 if query and name.startswith(query) else 2
        rows.append((score, name, item["id"], item))
    rows.sort(key=lambda row: row[:3])
    pages = max(1, (len(rows) + page_size - 1) // page_size)
    if page > pages:
        raise ValueError("That game guide page doesn't exist.")
    return {"items": [{key: row[3][key] for key in ("id", "kind", "name", "internal_ref")} for row in rows[(page - 1) * page_size:page * page_size]],
            "category": category, "query": query, "page": page, "pages": pages, "total": len(rows),
            "snapshot_date": data["snapshot_date"]}


def get_reference(identifier):
    if not isinstance(identifier, str) or not _REF.fullmatch(identifier):
        raise ValueError("Choose a reference from the game guide.")
    row = _data()["items"].get(identifier)
    if row is None or row["status"] != "resolved":
        raise ValueError("That reference isn't available in this guide view.")
    result = deepcopy(row)
    result["snapshot_date"] = SNAPSHOT
    return result


def category_for(kind):
    return next((key for key, (_, kinds) in CATEGORIES.items() if kind in kinds), "all")
