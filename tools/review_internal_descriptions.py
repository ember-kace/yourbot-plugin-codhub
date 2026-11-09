"""Apply a pinned English description policy without renaming assets.

Preview by default. The pure transform changes only internal_description on the
approved 72 identities and registers its separate policy source. --apply uses
the name importer's lock, validates current input bytes, and rolls back an
ordinary failed second replacement. It never opens a game installation.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REVIEW = ROOT / "metadata/policies/internal-descriptions.json"
SOURCE_ID = "reviewed-internal-descriptions-2026-11-09"
EXPECTED_POLICY_SHA256 = "c6242d8c49e0fada0c61c168bcf809786c6e389e8657ac69649eab18a1b10f8b"
QUALITY = "reviewed_internal_description"
EXPECTED_COUNT = 72
EXPECTED_IDS_SHA256 = "afbc05fafed513e8a673ea2061367c0f38109914d302781e957918a14ab6c428"
EXPECTED_REVIEW_SHA256 = "2c3d64b1e22d1209b74b0b551b2263ebe39d2eeabc119a21f6185cf6acd7908d"
EXPECTED_MANIFEST_SHA256 = "994f3cf6089441552de2063632921d451389728a93f0be47f8095f0fc6e34369"
EXPECTED_SOURCE_SHA256 = "a8abe7b3faefa89d2bf4c4cfddc9096cf7daf109f47fb228e43770ed7f38e593"
BASE_KEYS = ("name", "quality", "kind", "internal_ref", "loot_id", "aliases", "source_ids", "name_claims", "name_ambiguous")
NAME_QUALITIES = frozenset({"user_capture", "published_fixture", "native_localization", "official_reference"})
MAX_JSON_BYTES = 32 * 1024 * 1024


def canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def canonical_sha256(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key: " + key)
        result[key] = value
    return result


def _decode(raw):
    if len(raw) > MAX_JSON_BYTES:
        raise ValueError("JSON input exceeds the 32 MiB bound.")
    return json.loads(raw.decode("utf8"), object_pairs_hook=_unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON number.")))


def _encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf8")


def _validate_review(review):
    if not isinstance(review, dict) or canonical_sha256(review) != EXPECTED_MANIFEST_SHA256:
        raise ValueError("Review manifest differs from the explicitly reviewed and pinned policy.")
    records = review.get("records")
    if not isinstance(records, dict) or len(records) != EXPECTED_COUNT:
        raise ValueError("The review must contain exactly 72 approved identities.")
    ids = sorted(records)
    scope = hashlib.sha256(("\n".join(ids) + "\n").encode("ascii")).hexdigest()
    if (scope != EXPECTED_IDS_SHA256 or review.get("scope_asset_ids") != ids
            or review.get("scope_asset_ids_sha256") != scope):
        raise ValueError("The approved internal identity scope changed.")
    if (canonical_sha256(records) != EXPECTED_REVIEW_SHA256
            or review.get("canonical_review_sha256") != EXPECTED_REVIEW_SHA256):
        raise ValueError("The description wording or per-identity evidence changed.")
    policy = review.get("policy")
    if (not isinstance(policy, dict) or policy.get("review_status") != "reviewed"
            or canonical_sha256(policy) != EXPECTED_POLICY_SHA256):
        raise ValueError("The exact reviewed public policy is required.")
    source = review.get("source")
    if (review.get("source_id") != SOURCE_ID or canonical_sha256(source) != EXPECTED_SOURCE_SHA256
            or source.get("input_sha256") != EXPECTED_REVIEW_SHA256
            or source.get("policy_sha256") != EXPECTED_POLICY_SHA256):
        raise ValueError("The registered internal-description policy source changed.")
    for asset_id, row in records.items():
        description = row["internal_description"]
        evidence = description["evidence"]
        if (set(row["base"]) != set(BASE_KEYS) or description["quality"] != QUALITY
                or description["language"] != "en" or description["source_id"] != SOURCE_ID
                or description["source_date"] != "2026-11-09"
                or not description["text"].startswith("Internal · ")
                or evidence["asset_id"] != asset_id or evidence["source_proven_nonselectable"] is not True):
            raise ValueError("Description schema or source-proven scope is invalid.")
    return records, source


def apply_review(catalog, provenance, review_manifest):
    """Return deep-copied (catalog, provenance, audit); never modify input values.

    The historical base review is pinned per identity. A later real-English name
    may supersede it, and is preserved verbatim; the separate release gate must
    validate that name's evidence. Legitimate updates elsewhere do not invalidate
    this review. No description is used as an asset name or accepted name quality.
    """
    records, source = _validate_review(review_manifest)
    if (not isinstance(catalog, dict) or not isinstance(catalog.get("assets"), dict)
            or not isinstance(provenance, dict) or not isinstance(provenance.get("sources"), dict)):
        raise ValueError("Catalog assets and registered source objects are required.")
    updated_catalog, updated_provenance = deepcopy(catalog), deepcopy(provenance)
    existing_source = updated_provenance["sources"].get(SOURCE_ID)
    if existing_source is not None and existing_source != source:
        raise ValueError("A different source already uses the internal-description source ID.")
    added, unchanged, future_names = [], [], []
    for asset_id, row in records.items():
        record = updated_catalog["assets"].get(asset_id)
        if not isinstance(record, dict):
            raise ValueError("Approved asset is missing: " + asset_id)
        base = row["base"]
        if any(record.get(key) != base[key] for key in ("kind", "internal_ref", "loot_id")):
            raise ValueError("Approved asset identity changed: " + asset_id)
        current_base = {key: deepcopy(record.get(key)) for key in BASE_KEYS}
        if current_base != base:
            # Do not overwrite a later official/captured real name or its claims.
            # This quality is not granted by the description tool; the strict
            # English-name gate independently validates the name and sources.
            if (record.get("quality") not in NAME_QUALITIES or not isinstance(record.get("name"), str)
                    or not record["name"].strip()):
                raise ValueError("Unreviewed original name/evidence fields changed: " + asset_id)
            future_names.append(asset_id)
        expected = row["internal_description"]
        existing = record.get("internal_description")
        if existing is not None and existing != expected:
            raise ValueError("Conflicting internal description already exists: " + asset_id)
        if existing == expected:
            unchanged.append(asset_id)
        else:
            record["internal_description"] = deepcopy(expected)
            added.append(asset_id)
    updated_provenance["sources"][SOURCE_ID] = deepcopy(source)
    # Catch an implementation regression that touches any original asset field.
    stripped = deepcopy(updated_catalog)
    for asset_id in records:
        if "internal_description" not in catalog["assets"][asset_id]:
            stripped["assets"][asset_id].pop("internal_description", None)
    if stripped != catalog:
        raise ValueError("The description transform modified original catalog fields.")
    audit = {"scope_asset_count": EXPECTED_COUNT, "scope_asset_ids_sha256": EXPECTED_IDS_SHA256,
             "canonical_review_sha256": EXPECTED_REVIEW_SHA256, "source_id": SOURCE_ID,
             "description_quality": QUALITY, "added": len(added), "already_present": len(unchanged),
             "added_ids": added, "preserved_future_real_name_ids": future_names,
             "original_catalog_fields_unchanged": True, "original_name_qualities_unchanged": True,
             "other_19_descriptions_added": 0, "applied": False}
    return updated_catalog, updated_provenance, audit


def _checked_member(plugin, relative):
    current = plugin
    for part in (None, *Path(relative).parts):
        if part is not None:
            current /= part
        metadata = current.lstat()
        if (stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
            raise ValueError("Linked description-input path is not supported.")
    result = current.resolve(strict=True)
    if not result.is_relative_to(plugin) or not result.is_file():
        raise ValueError("Description input escapes its explicit plugin root.")
    return result


def _temp_bytes(path, raw):
    handle, name = tempfile.mkstemp(prefix=".internal-review-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise
    return Path(name)


def _guarded_write_pair(catalog_path, sources_path, review_path, originals, review_raw, updates):
    """Cooperative lock + exact byte guards; rollback ordinary replace failures."""
    lock = catalog_path.parent / ".english-name-import.lock"
    descriptor, temporary, committed = None, [], []
    try:
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as error:
            raise ValueError("Another English import holds the catalog lock; no files were changed.") from error
        targets = (sources_path, catalog_path)  # Source registration precedes use.
        staged = {}
        for path in targets:
            staged[path] = _temp_bytes(path, updates[path])
            temporary.append(staged[path])
        for path, original in originals.items():
            if path.read_bytes() != original:
                raise ValueError("Catalog/source input bytes changed during review; retry the new snapshot.")
        if review_path.read_bytes() != review_raw:
            raise ValueError("Review manifest bytes changed during validation; no files were changed.")
        try:
            for path in targets:
                os.replace(staged[path], path)
                committed.append(path)
        except BaseException as error:
            rollback_errors = []
            for path in reversed(committed):
                try:
                    restored = _temp_bytes(path, originals[path])
                    temporary.append(restored)
                    os.replace(restored, path)
                except BaseException as rollback_error:
                    rollback_errors.append(str(rollback_error))
            if rollback_errors:
                raise RuntimeError("Replacement failed and rollback needs repair: " + "; ".join(rollback_errors)) from error
            raise
    finally:
        for path in temporary:
            path.unlink(missing_ok=True)
        if descriptor is not None:
            os.close(descriptor)
            lock.unlink(missing_ok=True)


def review_files(plugin_path=ROOT / "plugin", review_path=DEFAULT_REVIEW, *, apply=False):
    supplied = Path(plugin_path).absolute()
    metadata = supplied.lstat()
    if (stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
        raise ValueError("Linked plugin root is not supported.")
    plugin = supplied.resolve(strict=True)
    catalog_path = _checked_member(plugin, "cod_hub/data/catalog.json")
    sources_path = _checked_member(plugin, "cod_hub/data/facts-sources.json")
    review_path = Path(review_path).resolve(strict=True)
    originals = {path: path.read_bytes() for path in (catalog_path, sources_path)}
    review_raw = review_path.read_bytes()
    catalog, provenance, audit = apply_review(_decode(originals[catalog_path]), _decode(originals[sources_path]), _decode(review_raw))
    updates = {catalog_path: _encoded(catalog), sources_path: _encoded(provenance)}
    audit["dry_run"] = not apply
    audit["input_sha256"] = {path.name: hashlib.sha256(raw).hexdigest() for path, raw in originals.items()}
    audit["output_sha256"] = {path.name: hashlib.sha256(raw).hexdigest() for path, raw in updates.items()}
    if apply:
        _guarded_write_pair(catalog_path, sources_path, review_path, originals, review_raw, updates)
        audit["applied"] = True
    return audit


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin", type=Path, default=ROOT / "plugin")
    parser.add_argument("--review", type=Path, default=DEFAULT_REVIEW)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(review_files(args.plugin, args.review, apply=args.apply), sort_keys=True, indent=2))
        return 0
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, RuntimeError) as error:
        print(json.dumps({"applied": False, "error": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
