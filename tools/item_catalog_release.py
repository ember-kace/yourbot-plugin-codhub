"""Build bounded catalog resources from reviewed, exact native item joins.

This accepts normalized metadata only. It neither reads nor extracts game files.
An unresolved record stays in the source census and cannot become a named card.
"""
from collections import Counter
import argparse
import hashlib
import json
from pathlib import Path
import re
import unicodedata

try:
    from .english_release_gate import readable_name_issue
except ImportError:
    from english_release_gate import readable_name_issue


SOURCE_ID = "mw4-native-item-registry-current-2026-11-11"
SNAPSHOT = "2026-11-11"
ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "cod_hub/data/item-catalog.json"
REVIEWED_MANIFEST_SHA256 = "1c48e7f88911e7e3df70c759e7ae838dc3b36ed70baf62ad27a3e32dc0a42ca1"
REVIEWED_ENGLISH_SHA256 = '01b8467a4175a3abfbf36eaae8a96129394511dca766dfa13e561bae8c3d46b2'
REVIEWED_INVENTORY_SHA256 = '5c73af65af166acb803ef95054901f82f755437f5091bb37bffc537ec18dab70'
FIELDS = {"id", "kind", "internal_ref", "asset_id", "name", "name_hash", "description", "unlock",
          "image_asset_id", "season", "quality", "status", "source_ids", "classification", "base_item_id", "name_source",
          "rank_index", "reward_loot_ids", "progression_name", "display_labels", "name_hashes"}
HEX16 = re.compile(r"[0-9a-f]{16}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
KIND = re.compile(r"[a-z][a-z0-9_]{0,39}\Z")
# The native English source assigns this literal numeric blueprint title.
# This exception cannot turn another numeric value into a named item.
REVIEWED_NATIVE_LITERAL_TITLES = {(134368, "77f779fafebe9526", "141"), (157011, "797f54a90b316037", "141")}


def canonical(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf8")


def reviewed_item(item, identifier):
    if not isinstance(item, dict) or set(item) - FIELDS:
        raise ValueError("Only normalized item metadata may be distributed.")
    if (type(item.get("id")) is not int or not 0 <= item["id"] < 2**31 or str(item["id"]) != identifier
            or not isinstance(item.get("kind"), str) or not KIND.fullmatch(item["kind"])
            or item.get("status") not in {"resolved", "held", "source_internal"}
            or item.get("source_ids") != [SOURCE_ID]):
        raise ValueError("Invalid native item identity or provenance.")
    for key in ("asset_id", "name_hash", "image_asset_id"):
        value = item.get(key)
        if value is not None and (not isinstance(value, str) or not HEX16.fullmatch(value)):
            raise ValueError("Invalid native item hash.")
    for key, maximum in (("name", 1000), ("internal_ref", 1000), ("description", 8000), ("unlock", 8000), ("season", 100)):
        value = item.get(key)
        if value is not None and (not isinstance(value, str) or len(value) > maximum or "\x00" in value):
            raise ValueError("Invalid normalized item text.")
    contextual = item.get("name_source") == "native_context_labels"
    equivalent_hashes = item.get("name_hashes")
    if equivalent_hashes is not None and (contextual or item.get("name_hash") is not None
            or not isinstance(equivalent_hashes, list) or not 2 <= len(equivalent_hashes) <= 20
            or any(not isinstance(value, str) or not HEX16.fullmatch(value) for value in equivalent_hashes)
            or equivalent_hashes != sorted(set(equivalent_hashes))):
        raise ValueError("Invalid equivalent native English name references.")
    if contextual:
        labels = item.get("display_labels")
        if item["status"] != "resolved" or item.get("name") is not None or item.get("name_hash") is not None or not isinstance(labels, list) or not 2 <= len(labels) <= 6:
            raise ValueError("Context labels must retain an unassigned canonical name.")
        seen = set()
        for label in labels:
            if (not isinstance(label, dict) or set(label) != {"name", "name_hash", "context_ids"}
                    or not isinstance(label["name"], str) or not label["name"].strip() or len(label["name"]) > 150
                    or readable_name_issue(label["name"]) or label["name"] in seen
                    or not isinstance(label["name_hash"], str) or not HEX16.fullmatch(label["name_hash"])
                    or not isinstance(label["context_ids"], list) or not 1 <= len(label["context_ids"]) <= 100
                    or any(not isinstance(value, str) or not HEX64.fullmatch(value) for value in label["context_ids"])):
                raise ValueError("Invalid source-backed English context label.")
            seen.add(label["name"])
        if item.get("quality") != "native_localization":
            raise ValueError("Context labels require native English evidence.")
    elif "display_labels" in item:
        raise ValueError("Context labels require their explicit native scope.")
    if item["status"] == "resolved" and not contextual and (
            not isinstance(item.get("name"), str) or not item["name"].strip()
            or item.get("quality") != "native_localization" or not (item.get("name_hash") or equivalent_hashes)):
        raise ValueError("A resolved item needs its exact native English name reference.")
    literal_title = (item["id"], item.get("name_hash"), item.get("name")) in REVIEWED_NATIVE_LITERAL_TITLES
    if item["status"] == "resolved" and not contextual and not literal_title and readable_name_issue(item["name"]):
        raise ValueError("A resolved item has an unreadable or placeholder name.")
    if item.get("classification") not in {None, "player_catalog_record", "blueprint_variant", "entitlement_or_tracking",
                                         "progression_tracker", "progression_step", "approved_technical_record"}:
        raise ValueError("Invalid item classification.")
    if "base_item_id" in item and (type(item["base_item_id"]) is not int or not 0 <= item["base_item_id"] < 2**31):
        raise ValueError("Invalid native base item identity.")
    if item.get("name_source") not in {None, "native_baseref", "native_frontend_label", "native_context_labels", "native_default_variant", "native_literal_title"}:
        raise ValueError("Invalid native name source.")
    if item.get("name_source") == "native_literal_title" and not literal_title:
        raise ValueError("Literal title differs from its exact reviewed identity.")
    if "rank_index" in item and (type(item["rank_index"]) is not int or not 0 <= item["rank_index"] <= 10000):
        raise ValueError("Invalid numeric progression reference.")
    if "reward_loot_ids" in item and (not isinstance(item["reward_loot_ids"], list) or len(item["reward_loot_ids"]) > 1000
            or any(type(value) is not int or not 0 <= value < 2**31 for value in item["reward_loot_ids"])):
        raise ValueError("Invalid progression reward references.")
    if "progression_name" in item and (item["progression_name"] is not None and
            (not isinstance(item["progression_name"], str) or len(item["progression_name"]) > 1000)):
        raise ValueError("Invalid progression label.")
    result = dict(item)
    for key in ("description", "unlock"):
        text = result.get(key)
        if text and (text.lstrip().startswith("#PH:") or any(unicodedata.category(char).startswith("C") and char not in "\n\t" for char in text)):
            result[key] = None
    return result


def build_resources(candidate):
    if (not isinstance(candidate, dict) or candidate.get("format_version") != 1
            or type(candidate.get("format_version")) is not int or candidate.get("game") != "mw4"
            or candidate.get("snapshot_date") != SNAPSHOT or candidate.get("source_id") != SOURCE_ID
            or not isinstance(candidate.get("items"), dict) or not 1 <= len(candidate["items"]) <= 20000):
        raise ValueError("Invalid reviewed native catalog document.")
    kinds = {}
    for identifier, item in candidate["items"].items():
        row = reviewed_item(item, identifier)
        if row.get("name_source") == "native_baseref":
            parent = candidate["items"].get(str(row.get("base_item_id")))
            if (row.get("classification") != "blueprint_variant" or row["status"] != "resolved"
                    or not isinstance(parent, dict) or parent.get("status") not in {"resolved", "source_internal"}
                    or parent.get("quality") != "native_localization" or not parent.get("name_hash")
                    or readable_name_issue(parent.get("name"))
                    or parent.get("kind") != row["kind"] or parent.get("id") == row["id"]
                    or (parent.get("name"), parent.get("name_hash")) != (row.get("name"), row.get("name_hash"))):
                raise ValueError("An inherited name has no exact, named native parent.")
        kinds.setdefault(row["kind"], []).append(row)
    if len(kinds) > 100:
        raise ValueError("Too many catalog categories.")
    categories, resources = {}, {}
    for kind, items in sorted(kinds.items()):
        items.sort(key=lambda row: row["id"])
        counts = Counter(row["status"] for row in items)
        category = {"total": len(items), **{key: counts[key] for key in ("resolved", "held", "source_internal")}, "shards": []}
        for index, start in enumerate(range(0, len(items), 100)):
            chunk = items[start:start + 100]
            data = canonical(chunk)
            if len(data) > 1000000:
                raise ValueError("An item catalog shard exceeds its runtime bound.")
            digest = hashlib.sha256(data).hexdigest()
            relative = f"items/{kind}-{index:03d}-{digest}.json"
            resources[relative] = data
            category["shards"].append({"file": relative, "sha256": digest, "count": len(chunk)})
        categories[kind] = category
    coverage = candidate.get("coverage", {})
    if coverage.get("native_records") != len(candidate["items"]):
        raise ValueError("The native census and normalized catalog do not reconcile.")
    for kind, category in categories.items():
        claimed = coverage.get("by_kind", {}).get(kind)
        if isinstance(claimed, dict) and "source_proven_internal" in claimed:
            claimed = {**claimed, "source_internal": claimed["source_proven_internal"]}
        if not isinstance(claimed, dict) or any(claimed.get(key, 0) != category[key] for key in ("total", "resolved", "held", "source_internal")):
            raise ValueError("Native category coverage does not reconcile.")
    manifest = {"format_version": 1, "game": "mw4", "snapshot_date": SNAPSHOT, "source_id": SOURCE_ID,
                "native_records": len(candidate["items"]), "categories": categories}
    resources["item-catalog.json"] = canonical(manifest)
    return resources


def summarize(resources):
    manifest = json.loads(resources["item-catalog.json"])
    return {"native_records": manifest["native_records"], "categories": len(manifest["categories"]),
            "resolved": sum(row["resolved"] for row in manifest["categories"].values()),
            "held": sum(row["held"] for row in manifest["categories"].values()),
            "source_internal": sum(row["source_internal"] for row in manifest["categories"].values()),
            "resource_bytes": sum(map(len, resources.values())),
            "manifest_sha256": hashlib.sha256(resources["item-catalog.json"]).hexdigest(),
            "files": len(resources)}


def required_files(raw):
    """Return only the reviewed sharded resources; no directory enumeration."""
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= 150000 or hashlib.sha256(raw).hexdigest() != REVIEWED_MANIFEST_SHA256:
        raise ValueError("Item catalog manifest differs from the reviewed current snapshot.")
    document = json.loads(raw)
    if (document.get("format_version") != 1 or document.get("game") != "mw4"
            or document.get("source_id") != SOURCE_ID or document.get("snapshot_date") != SNAPSHOT
            or not isinstance(document.get("categories"), dict) or not 1 <= len(document["categories"]) <= 100):
        raise ValueError("Invalid reviewed item catalog manifest.")
    files = [MANIFEST]
    for kind, category in sorted(document["categories"].items()):
        if not isinstance(kind, str) or not KIND.fullmatch(kind) or not isinstance(category.get("shards"), list):
            raise ValueError("Invalid reviewed item catalog category.")
        for index, shard in enumerate(category["shards"]):
            if (not isinstance(shard, dict) or not isinstance(shard.get("sha256"), str) or not HEX64.fullmatch(shard["sha256"])
                    or shard.get("file") != f"items/{kind}-{index:03d}-{shard['sha256']}.json"):
                raise ValueError("Invalid reviewed item catalog shard.")
            files.append("cod_hub/data/" + shard["file"])
    return files


def evaluate_captured(captured):
    """Validate the exact current-snapshot bytes entering the plugin archive."""
    try:
        names = required_files(captured.get(MANIFEST))
        manifest = json.loads(captured[MANIFEST])
        items = {}
        for name in names[1:]:
            raw = captured.get(name)
            if not isinstance(raw, bytes) or not 1 <= len(raw) <= 1000000:
                raise ValueError("Missing or oversized captured item catalog shard.")
            for row in json.loads(raw):
                key = str(row["id"])
                if key in items:
                    raise ValueError("Duplicate native catalog identity.")
                items[key] = row
        coverage = {"native_records": manifest["native_records"], "by_kind": manifest["categories"]}
        candidate = {"format_version": 1, "game": "mw4", "source_id": SOURCE_ID,
                     "snapshot_date": SNAPSHOT, "items": items, "coverage": coverage}
        expected = build_resources(candidate)
        if any(captured.get("cod_hub/data/" + name) != raw for name, raw in expected.items()):
            raise ValueError("Captured item catalog differs from its normalized reviewed resources.")
        return {"ready": True, **summarize(expected), "issues": []}
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError) as error:
        return {"ready": False, "issues": [str(error)]}


def evaluate_release(plugin_path=ROOT / "plugin"):
    try:
        try:
            from .native_artwork_release import _safe_file
        except ImportError:
            from native_artwork_release import _safe_file
        raw = _safe_file(plugin_path, MANIFEST)
        captured = {name: _safe_file(plugin_path, name) for name in required_files(raw)}
        expected = {Path(name).name for name in captured if name != MANIFEST}
        actual = {path.name for path in (Path(plugin_path) / "cod_hub/data/items").iterdir()}
        if actual != expected:
            raise ValueError("Item catalog directory differs from the reviewed shard set.")
        report = evaluate_captured(captured)
        if report["ready"]:
            report["english_evidence"] = evaluate_name_evidence(captured, ROOT)
            report["ready"] = report["english_evidence"]["ready"]
            report["issues"].extend(report["english_evidence"]["issues"])
        return report
    except (OSError, ValueError, TypeError, KeyError) as error:
        return {"ready": False, "issues": [str(error)]}


def evaluate_name_evidence(captured, evidence_root):
    """Cross-check every named card against a separate exact current name witness."""
    try:
        try:
            from .native_artwork_release import _safe_file
        except ImportError:
            from native_artwork_release import _safe_file
        names_raw = _safe_file(evidence_root, "metadata/names/current-item-English.json")
        inventory_raw = _safe_file(evidence_root, "metadata/item-name-inventory.json")
        if (hashlib.sha256(names_raw).hexdigest() != REVIEWED_ENGLISH_SHA256
                or hashlib.sha256(inventory_raw).hexdigest() != REVIEWED_INVENTORY_SHA256):
            raise ValueError("Current English evidence differs from its reviewed source pins.")
        names, inventory = json.loads(names_raw), json.loads(inventory_raw)
        if (names.get("source_id") != SOURCE_ID or names.get("language") != "en"
                or names.get("snapshot_date") != SNAPSHOT or inventory.get("source_id") != SOURCE_ID):
            raise ValueError("Current English evidence scope differs.")
        records = names["records"]
        normalized = lambda value: " ".join(value.split()).casefold()
        checked = 0
        for filename in required_files(captured[MANIFEST])[1:]:
            for item in json.loads(captured[filename]):
                if item["status"] != "resolved":
                    continue
                proof = inventory["items"].get(str(item["id"]))
                if not isinstance(proof, dict) or any(proof.get(key) != item.get(key) for key in ("id", "asset_id", "kind", "status", "quality")):
                    raise ValueError("A named item has no exact current identity witness.")
                witnesses = []
                for key in proof["source_context_ids"]:
                    witness = records[key]
                    if (witness.get("item_id") != item["id"] or witness.get("asset_id") != item.get("asset_id")
                            or witness.get("kind") != item["kind"] or witness.get("source_context_sha256") != key
                            or witness.get("current_source_bound") is not True or witness.get("source_ids") != [SOURCE_ID]):
                        raise ValueError("An English label witness belongs to another native identity.")
                    witnesses.append(witness)
                if item.get("name_source") == "native_context_labels":
                    for label in item["display_labels"]:
                        if not label["context_ids"] or any(key not in proof["source_context_ids"] for key in label["context_ids"]):
                            raise ValueError("A contextual label lost its native identity witness.")
                        for key in label["context_ids"]:
                            witness = records[key]
                            if normalized(witness["display_name"]) != normalized(label["name"]):
                                raise ValueError("A contextual label differs from its exact native English fact.")
                        if not any(records[key]["name_hash"] == label["name_hash"] for key in label["context_ids"]):
                            raise ValueError("A contextual label has no exact assigned native name hash.")
                else:
                    hashes = item.get("name_hashes") or [item.get("name_hash")]
                    if not hashes or any(not any(witness["name_hash"] == key
                            and normalized(witness["display_name"]) == normalized(item["name"])
                            for witness in witnesses) for key in hashes):
                        raise ValueError("A named card differs from its exact native English fact.")
                checked += 1
        return {"ready": True, "named_references_checked": checked, "source_contexts": len(records), "issues": []}
    except (OSError, ValueError, TypeError, KeyError, AttributeError, UnicodeError) as error:
        return {"ready": False, "issues": [str(error)]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path, nargs="?")
    parser.add_argument("--output", type=Path, help="Write a staged data directory; omitted to validate only.")
    args = parser.parse_args(argv)
    try:
        if args.candidate is None:
            if args.output:
                raise ValueError("Specify reviewed input metadata before staging resources.")
            report = evaluate_release()
            print(json.dumps(report, indent=2))
            return 0 if report["ready"] else 1
        resources = build_resources(json.loads(args.candidate.read_text(encoding="utf8")))
        report = summarize(resources)
        if args.output:
            if args.output.exists() and any(args.output.iterdir()):
                raise ValueError("Use an empty staging directory; existing resources are never overwritten.")
            for name, raw in resources.items():
                path = args.output / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
        print(json.dumps(report, indent=2))
        return 0
    except (OSError, ValueError, TypeError) as error:
        print(json.dumps({"ready": False, "error": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
