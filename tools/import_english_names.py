"""Preview an evidence-backed English name import; write only with --apply.

Only exact production asset IDs / inventory localization hashes are joined.
This tool makes no network requests and never opens or executes game files.
"""
from __future__ import annotations

import argparse
from collections import Counter
import copy
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit

try:
    from .english_release_gate import ACCEPTED_QUALITIES, MAX_JSON_BYTES, evaluate_documents, label_key, read_json, readable_name_issue, valid_date
except ImportError:
    from english_release_gate import ACCEPTED_QUALITIES, MAX_JSON_BYTES, evaluate_documents, label_key, read_json, readable_name_issue, valid_date

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = ROOT / "metadata/name-inventory.json"
MAX_ROWS = 200_000
_HASH = re.compile(r"(?:0x)?[0-9a-fA-F]{1,16}\Z")
_RANK = {"published_fixture": 1, "official_reference": 2, "native_localization": 3, "user_capture": 4}


def normalize_hash(value):
    if not isinstance(value, str) or not _HASH.fullmatch(value.strip()):
        raise ValueError("Asset IDs and name hashes must be exact hexadecimal values of at most 64 bits.")
    return f"{int(value.strip(), 16):016x}"


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key: " + str(key))
        result[key] = value
    return result


def _load_rows(path, language):
    path = Path(path)
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError("Input exceeds the 32 MiB bound.")
    raw = path.read_bytes()
    text = raw.decode("utf-8")  # Strict UTF-8; no silent byte replacement.
    if text.startswith("\ufeff"):
        raise ValueError("Input must be UTF-8 without a BOM.")
    metadata = {}
    if path.suffix.lower() == ".json":
        data = json.loads(text, object_pairs_hook=_unique_object)
        if not isinstance(data, dict):
            raise ValueError("JSON input must be a name-hash-to-English-name object.")
        if "names" in data:
            if data.get("language", language) != "en" or not isinstance(data["names"], dict):
                raise ValueError("JSON language must be en and names must be an object.")
            for key in ["source_image_sha256", "upstream_input_sha256", "upstream_input_filename", "method", "selection_scope"]:
                if key in data:
                    if not isinstance(data[key], str) or len(data[key]) > 2000:
                        raise ValueError("Invalid localization source metadata.")
                    metadata[key] = data[key]
            for key in ["source_image_sha256", "upstream_input_sha256"]:
                if key in metadata and not re.fullmatch(r"[0-9a-f]{64}", metadata[key]):
                    raise ValueError("Source/upstream SHA-256 must be exact lowercase hex.")
            if "upstream_input_filename" in metadata and ("/" in metadata["upstream_input_filename"] or "\\" in metadata["upstream_input_filename"]):
                raise ValueError("Upstream filename must not contain an absolute or relative path.")
            if "excluded_name_hashes" in data:
                values = data["excluded_name_hashes"]
                if not isinstance(values, list) or len(values) > MAX_ROWS:
                    raise ValueError("Excluded localization hashes must be a bounded list.")
                metadata["excluded_name_hashes"] = sorted({normalize_hash(h) for h in values})
            data = data["names"]
        if any(not isinstance(value, str) for value in data.values()):
            raise ValueError("Every JSON localization value must be text.")
        rows = [{"name_hash": normalize_hash(key), "name": value} for key, value in data.items()]
    elif path.suffix.lower() == ".csv":
        reader = csv.DictReader(io.StringIO(text, newline=""))
        headers = reader.fieldnames
        allowed = {"asset_id", "name_hash", "namehash", "localize_hash", "name", "language"}
        hash_headers = set(headers or []) & {"name_hash", "namehash", "localize_hash"}
        if (not headers or len(set(headers)) != len(headers) or not set(headers) <= allowed
                or "name" not in headers or not ({"asset_id"} & set(headers) or hash_headers) or len(hash_headers) > 1):
            raise ValueError("CSV needs name and asset_id and/or one name_hash column; optional language must be en.")
        rows = []
        for row in reader:
            if len(rows) >= MAX_ROWS:
                raise ValueError("Input exceeds 200,000 rows.")
            if None in row or any(value is None for value in row.values()):
                raise ValueError("CSV row does not match the header.")
            if row.get("language", language) != "en":
                raise ValueError("Every input row must declare English (en).")
            asset_id = row.get("asset_id", "").strip()
            name_hash = row.get(next(iter(hash_headers)), "").strip() if hash_headers else ""
            if not asset_id and not name_hash:
                raise ValueError("Every row needs an exact asset_id or name_hash.")
            rows.append({"asset_id": normalize_hash(asset_id) if asset_id else None,
                         "name_hash": normalize_hash(name_hash) if name_hash else None, "name": row["name"]})
    else:
        raise ValueError("Input must be a .json or .csv file.")
    if not rows or len(rows) > MAX_ROWS:
        raise ValueError("Input must contain between 1 and 200,000 rows.")
    return rows, hashlib.sha256(raw).hexdigest(), metadata


def _inventory_map(path, catalog):
    inventory = read_json(path)
    if not isinstance(inventory, dict) or not isinstance(inventory.get("assets"), list):
        raise ValueError("Name inventory must contain an assets list.")
    assets, hashes = {}, {}
    for record in inventory["assets"]:
        if not isinstance(record, dict):
            raise ValueError("Invalid inventory record.")
        asset_id = normalize_hash(record.get("asset_id"))
        if asset_id in assets:
            raise ValueError("Duplicate inventory asset: " + asset_id)
        assets[asset_id] = record
        for value in record.get("localize_hashes", []):
            key = normalize_hash(value)
            if key == "0000000000000000":
                raise ValueError("Inventory cannot map a zero name hash.")
            hashes.setdefault(key, set()).add(asset_id)
    if set(assets) != set(catalog["assets"]):
        raise ValueError("Inventory identity set differs from the production catalog.")
    for asset_id, record in assets.items():
        current = catalog["assets"][asset_id]
        if record.get("internal_ref") != current.get("internal_ref") or record.get("loot_id") != current.get("loot_id"):
            raise ValueError("Inventory identity metadata differs for asset " + asset_id)
    return assets, hashes


def _source(source_id, title, source_date, url, quality, language, input_sha256, filename):
    if language != "en":
        raise ValueError("Only explicitly declared English (en) input can be imported.")
    if quality not in ACCEPTED_QUALITIES:
        raise ValueError("Choose an accepted evidence quality; internal/fallback quality cannot be imported.")
    if not isinstance(source_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,79}", source_id):
        raise ValueError("Source ID must be 1–80 lowercase letters, digits, dots, underscores or hyphens.")
    if not isinstance(title, str) or not title.strip() or len(title) > 180 or any(ord(c) < 32 for c in title):
        raise ValueError("Provide a readable source title of at most 180 characters.")
    if not valid_date(source_date):
        raise ValueError("Provide the evidence's data date as YYYY-MM-DD.")
    if quality in {"official_reference", "published_fixture"} and not url:
        raise ValueError("Published/official reference evidence needs its HTTPS source URL.")
    if url:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Source URL, when supplied, must be an HTTPS URL without credentials.")
    result = {"kind": quality, "title": title.strip(), "source_date": source_date, "language": language,
              "input_sha256": input_sha256, "input_filename": filename,
              "scope": "English name claims joined by exact production asset ID or inventoried localization hash; no statistics or native IDs changed."}
    if url:
        result["url"] = url
    return result


def _encode(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _summary(report):
    return {k: report[k] for k in ["ready", "required", "total_translated", "missing_ids", "counts"]}


def _review_file(path, input_sha256, key):
    if path is None:
        return {}, None, None
    path = Path(path)
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError("Review file exceeds the 32 MiB bound.")
    raw = path.read_bytes()
    data = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    if (not isinstance(data, dict) or data.get("status") != "approved" or data.get("language") != "en" or data.get("input_sha256") != input_sha256
            or not valid_date(data.get("reviewed_on")) or not isinstance(data.get("reviewed_by"), str)
            or not data["reviewed_by"].strip() or not isinstance(data.get("decisions"), list)):
        raise ValueError("Review file needs status approved, exact input_sha256, language en, reviewed_by, reviewed_on and decisions list.")
    if len(data["decisions"]) > MAX_ROWS:
        raise ValueError("Review file exceeds 200,000 decisions.")
    result = {}
    for row in data["decisions"]:
        if not isinstance(row, dict):
            raise ValueError("Review decisions must be objects.")
        row = copy.deepcopy(row)
        identifier = normalize_hash(row.get(key))
        row[key] = identifier
        if identifier in result:
            raise ValueError("Duplicate review decision: " + identifier)
        for field in ["raw_name", "display_name", "reason", "evidence"]:
            if not isinstance(row.get(field), str) or not row[field] or len(row[field]) > 4000:
                raise ValueError("Every review decision needs exact raw_name/display_name and nonempty reason/evidence.")
        if row.get("name_hash") is not None:
            row["name_hash"] = normalize_hash(row["name_hash"])
        row["reviewed_by"], row["reviewed_on"] = data["reviewed_by"], data["reviewed_on"]
        result[identifier] = row
    return result, hashlib.sha256(raw).hexdigest(), data


def _legacy_claims(record, sources):
    """Keep an existing preferred label's dated evidence before changing it."""
    result = copy.deepcopy(record.get("name_claims", []))
    quality = record.get("quality")
    for source_id in record.get("source_ids", []):
        source = sources.get(source_id, {})
        kinds = {quality, "published_launch_snapshot"} if quality == "published_fixture" else {quality}
        if source.get("kind") not in kinds or not valid_date(source.get("source_date")):
            continue
        if any(c.get("source_id") == source_id and c.get("name") == record.get("name") for c in result):
            continue
        result.append({"name": record["name"], "quality": quality, "source_id": source_id,
                       "source_date": source["source_date"], "language": "en", "mapping_method": "existing_verified_catalog"})
    return result


def import_names(plugin_path, input_path, inventory_path=DEFAULT_INVENTORY, *, language, quality,
                 source_id, source_title, source_date, source_url=None, apply=False,
                 normalization_path=None, review_path=None):
    """Validate/preview, then optionally atomically replace name metadata files.

    Dry runs report all conflicts/invalid names. Applying requires every one to
    be resolved by exact reviewed decisions; there is no blanket force flag.
    """
    data = Path(plugin_path) / "cod_hub/data"
    catalog_path, sources_path = data / "catalog.json", data / "facts-sources.json"
    originals = {p: p.read_bytes() for p in [catalog_path, sources_path]}
    catalog, provenance = read_json(catalog_path), read_json(sources_path)
    before = evaluate_documents(catalog, provenance)
    if any(i["code"] in {"required_scope_changed", "native_identity_scope_changed", "invalid_snapshot_provenance", "invalid_documents", "invalid_identity_map", "missing_asset"} for i in before["issues"]):
        raise ValueError("The production identity scope differs from the pinned release scope.")
    inventory_assets, hash_assets = _inventory_map(inventory_path, catalog)
    rows, input_sha256, input_metadata = _load_rows(input_path, language)
    normalizations, normalization_sha256, _ = _review_file(normalization_path, input_sha256, "name_hash")
    reviews, review_sha256, _ = _review_file(review_path, input_sha256, "asset_id")
    source = _source(source_id, source_title, source_date, source_url, quality, language, input_sha256, Path(input_path).name)
    if input_metadata:
        source["input_provenance"] = input_metadata
    if normalization_sha256:
        source["normalization_review_sha256"] = normalization_sha256
    if review_sha256:
        source["name_review_sha256"] = review_sha256
    previous_source = provenance["sources"].get(source_id)
    if previous_source is not None and previous_source != source:
        raise ValueError("Source ID already has different provenance. Use a new source ID; existing evidence is immutable.")
    planned, unused, targeted = {}, set(), set()
    used_normalizations, used_reviews = set(), set()
    input_issues, conflicts = [], []
    for number, row in enumerate(rows, 1):
        asset_id, name_hash = row.get("asset_id"), row.get("name_hash")
        if asset_id:
            if asset_id not in inventory_assets:
                raise ValueError(f"Row {number}: asset_id is outside the exact production inventory.")
            if name_hash and asset_id not in hash_assets.get(name_hash, set()):
                raise ValueError(f"Row {number}: name hash does not belong to the stated asset_id.")
            targets = {asset_id}
        else:
            targets = hash_assets.get(name_hash, set())
        if not targets:
            unused.add(name_hash)
            continue  # Full game dictionaries legitimately contain unrelated UI text.
        targeted.update(targets)
        raw_name = row["name"]
        if not isinstance(raw_name, str):
            raise ValueError(f"Row {number}: an English name must be text.")
        normalized = normalizations.get(name_hash)
        if normalized:
            if normalized["raw_name"] != raw_name:
                raise ValueError("Normalization decision is stale for name hash " + name_hash)
            used_normalizations.add(name_hash)
        value = normalized["display_name"] if normalized else raw_name
        for target in sorted(targets):
            record = catalog["assets"][target]
            error = readable_name_issue(value, record)
            if not normalized and raw_name != raw_name.strip():
                error = "Raw name needs an exact per-hash whitespace/format normalization decision."
            if error:
                input_issues.append({"asset_id": target, "name_hash": name_hash, "raw_name": raw_name, "display_name": value, "detail": error})
                continue
            if quality == "native_localization" and not name_hash:
                input_issues.append({"asset_id": target, "name_hash": name_hash, "raw_name": raw_name, "detail": "native_localization needs an exact inventoried name hash; use capture/reference quality for asset-only evidence."})
                continue
            if target in planned and label_key(planned[target]["name"]) != label_key(value):
                raise ValueError("Conflicting input names target the same asset: " + target)
            if record.get("name_ambiguous"):
                input_issues.append({"asset_id": target, "name_hash": name_hash, "raw_name": raw_name, "detail": "Existing name ambiguity requires review."})
                continue
            planned[target] = {"name": value, "raw_name": raw_name, "normalization": normalized, "name_hash": name_hash,
                               "mapping_method": "exact_asset_id_and_hash" if asset_id and name_hash else "exact_asset_id" if asset_id else "exact_localization_hash"}
    if not targeted:
        raise ValueError("No input names match the exact production inventory.")
    if set(normalizations) != used_normalizations:
        raise ValueError("Normalization review contains decisions that were not matched to the exact input/inventory.")
    updated_catalog, updated_provenance = copy.deepcopy(catalog), copy.deepcopy(provenance)
    updated_provenance["sources"][source_id] = source
    changes = []
    for asset_id, proposed in sorted(planned.items()):
        record = updated_catalog["assets"][asset_id]
        old_name, old_quality = record.get("name"), record.get("quality")
        verified = old_quality in ACCEPTED_QUALITIES
        different = verified and label_key(old_name) != label_key(proposed["name"])
        review = reviews.get(asset_id)
        decision = None
        if different:
            if review:
                expected = {"current_name": old_name, "current_quality": old_quality, "raw_name": proposed["raw_name"],
                            "display_name": proposed["name"], "name_hash": proposed["name_hash"]}
                if any(review.get(k) != v for k, v in expected.items()):
                    raise ValueError("Name review decision is stale for asset " + asset_id)
                decision = review.get("decision")
                if decision not in {"keep_verified", "prefer_native"}:
                    raise ValueError("Name review decision must be keep_verified or prefer_native.")
                if decision == "prefer_native" and (old_quality == "user_capture" or quality != "native_localization"):
                    raise ValueError("User captures cannot be overwritten; prefer_native requires native evidence and a non-capture preferred name.")
                used_reviews.add(asset_id)
            conflicts.append({"asset_id": asset_id, "name_hash": proposed["name_hash"], "raw_name": proposed["raw_name"],
                              "display_name": proposed["name"], "current_name": old_name, "current_quality": old_quality,
                              "allowed_decisions": ["keep_verified"] if old_quality == "user_capture" or quality != "native_localization" else ["keep_verified", "prefer_native"],
                              "resolved": bool(review), "decision": decision})
            if not review:
                continue
        elif review:
            raise ValueError("Name review decision no longer addresses a conflicting asset: " + asset_id)
        new_name = proposed["name"] if not verified or decision == "prefer_native" else old_name
        if decision == "keep_verified":
            new_quality = old_quality
        elif decision == "prefer_native":
            new_quality = "native_localization"
        else:
            new_quality = old_quality if _RANK.get(old_quality, 0) > _RANK[quality] else quality
        record["name_claims"] = _legacy_claims(record, provenance["sources"]) if verified else copy.deepcopy(record.get("name_claims", []))
        record["name"], record["quality"] = new_name, new_quality
        record["aliases"] = list(dict.fromkeys(record.get("aliases", []) + ([old_name] if verified else []) + [proposed["name"]]))
        record["source_ids"] = list(dict.fromkeys(record.get("source_ids", []) + [source_id]))
        claim = {"name": proposed["name"], "raw_name": proposed["raw_name"], "quality": quality, "source_id": source_id,
                 "source_date": source_date, "language": "en", "mapping_method": proposed["mapping_method"]}
        if proposed["name_hash"]:
            claim["name_hash"] = proposed["name_hash"]
        if proposed["normalization"]:
            claim["normalization"] = dict(proposed["normalization"], review_sha256=normalization_sha256)
        if review:
            claim["preference_review"] = dict(review, review_sha256=review_sha256)
        record.setdefault("name_claims", [])
        if claim not in record["name_claims"]:
            record["name_claims"].append(claim)
        for reference in updated_catalog["reference_weapons"]:
            if reference.get("asset_id") == asset_id:
                for key in ["name", "quality", "source_ids", "aliases", "name_claims"]:
                    reference[key] = copy.deepcopy(record[key])
        changes.append({"asset_id": asset_id, "old_name": old_name, "name": new_name,
                        "old_quality": old_quality, "quality": new_quality,
                        "inventory_status": inventory_assets[asset_id].get("status"),
                        "name_hash": proposed["name_hash"], "raw_name": proposed["raw_name"], "decision": decision})
    if set(reviews) != used_reviews:
        raise ValueError("Name review contains decisions that were not matched to the exact input/current catalog.")
    after = evaluate_documents(updated_catalog, updated_provenance)
    if quality == "native_localization" and changes:
        assets = updated_catalog["assets"]
        claim_assets = sum(any(isinstance(c, dict) and c.get("quality") == "native_localization"
                               and c.get("language") == "en" and c.get("source_id") in updated_provenance["sources"]
                               and updated_provenance["sources"][c["source_id"]].get("kind") == "native_localization"
                               and not readable_name_issue(c.get("name")) for c in a.get("name_claims", []))
                           for a in assets.values())
        coverage = updated_catalog.setdefault("coverage", {})
        coverage.update({"english_name_assets": after["counts"]["assets_translated"],
                         "english_reference_weapons": after["counts"]["reference_weapons_translated"],
                         "untranslated_name_assets": len(assets) - after["counts"]["assets_translated"],
                         "native_english_claim_assets": claim_assets,
                         "preferred_name_qualities": dict(sorted(Counter(a.get("quality", "unknown") for a in assets.values()).items()))})
        updated_provenance["coverage"] = copy.deepcopy(coverage)
        updated_provenance.setdefault("limits", {}).update({"english_localization_decrypted": True,
                                                            "complete_readable_english_names": after["ready"]})
    report = {"applied": False, "dry_run": not apply, "input_sha256": input_sha256,
              "input_rows": len(rows), "targeted_assets": len(targeted), "accepted_assets": len(changes), "unmatched_name_hashes": len(unused),
              "unmatched_hash_sample": sorted(unused)[:20], "source_id": source_id, "source": source,
              "changes": changes, "input_issues": input_issues, "conflicts": conflicts,
              "unresolved_conflicts": [c["asset_id"] for c in conflicts if not c["resolved"]],
              "can_apply": not input_issues and not any(not c["resolved"] for c in conflicts),
              "release_before": _summary(before), "release_after": _summary(after)}
    if apply:
        if not report["can_apply"]:
            first = input_issues[0]["detail"] if input_issues else "A verified name conflict requires review."
            raise ValueError("Import requires review before any writes: " + first)
        lock = data / ".english-name-import.lock"
        descriptor = None
        temporary = []
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            for path, original in originals.items():
                if path.read_bytes() != original:
                    raise ValueError("Catalog or source evidence changed during validation. Retry against the new snapshot.")
            # Source first: an interruption may leave unused evidence, never a
            # new catalog name pointing to a source that was not registered.
            for path, value in [(sources_path, updated_provenance), (catalog_path, updated_catalog)]:
                handle, temp_name = tempfile.mkstemp(prefix=".english-name-", suffix=".tmp", dir=data)
                temporary.append(Path(temp_name))
                with os.fdopen(handle, "wb") as stream:
                    stream.write(_encode(value))
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temp_name, path)
            report["applied"] = True
        except FileExistsError as error:
            raise ValueError("Another English import holds the catalog lock; no changes were made.") from error
        finally:
            for path in temporary:
                path.unlink(missing_ok=True)
            if descriptor is not None:
                os.close(descriptor)
                lock.unlink(missing_ok=True)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--plugin", type=Path, default=ROOT / "plugin")
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--language", required=True, choices=["en"])
    parser.add_argument("--quality", required=True, choices=sorted(ACCEPTED_QUALITIES))
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--source-title", required=True)
    parser.add_argument("--source-date", required=True)
    parser.add_argument("--source-url")
    parser.add_argument("--normalizations", type=Path, help="Exact per-hash raw-to-display review file")
    parser.add_argument("--reviews", type=Path, help="Exact per-asset native/verified preference decisions")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = import_names(args.plugin, args.input, args.inventory, language=args.language, quality=args.quality,
                              source_id=args.source_id, source_title=args.source_title, source_date=args.source_date,
                              source_url=args.source_url, apply=args.apply, normalization_path=args.normalizations, review_path=args.reviews)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
        return 0 if report["can_apply"] else 1
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, csv.Error) as error:
        print(json.dumps({"applied": False, "error": str(error)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
