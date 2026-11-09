"""Apply the exact eleven-caption release policy without changing any asset name.

Preview by default. Only asset.technical_description and one separate policy
source may be added. The original72 review is independent and unchanged.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import stat

try:
    from .review_internal_descriptions import _checked_member, _decode, _encoded, _guarded_write_pair
except ImportError:
    from review_internal_descriptions import _checked_member, _decode, _encoded, _guarded_write_pair

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REVIEW = ROOT / "metadata/policies/technical-descriptions.json"
SOURCE_ID = "reviewed-technical-descriptions-2026-11-09"
QUALITY = "reviewed_technical_description"
EXPECTED_COUNT = 11
EXPECTED_IDS_SHA256 = "0d176fcb55552685f68d8715d97ed045d93606e685eb35df561e6b17ee65c652"
EXPECTED_POLICY_SHA256 = "2dbf7f6f36526587f546be44708de60381f9671c75e7ab1cb6fd596a8e03352e"
EXPECTED_REVIEW_SHA256 = "b83099465f7c22396363a9b6e5fd07f27d7e64b1a3f1914da014d716d15d2dc9"
EXPECTED_MANIFEST_SHA256 = "db7e3e68536fe706311a9c82604cdb85f884c9dca66174864f3d0f7b0eb3cb9f"
EXPECTED_SOURCE_SHA256 = "92910c52044cf8fd5b383e06bb9bdbeb2f23c744e09ac66394fcd81a6acd395f"
BASE_KEYS = ("name", "quality", "kind", "internal_ref", "loot_id", "aliases", "source_ids", "name_claims", "name_ambiguous")
NAME_QUALITIES = frozenset({"user_capture", "published_fixture", "native_localization", "official_reference"})


def canonical_sha256(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                                    allow_nan=False).encode("ascii")).hexdigest()


def _validate_review(review):
    if not isinstance(review, dict) or canonical_sha256(review) != EXPECTED_MANIFEST_SHA256:
        raise ValueError("Technical-caption manifest differs from the exact reviewed release policy.")
    records = review.get("records")
    if not isinstance(records, dict) or len(records) != EXPECTED_COUNT:
        raise ValueError("Exactly eleven approved technical-caption identities are required.")
    ids = sorted(records)
    scope = hashlib.sha256(("\n".join(ids) + "\n").encode("ascii")).hexdigest()
    if (scope != EXPECTED_IDS_SHA256 or review.get("scope_asset_ids") != ids
            or review.get("scope_asset_ids_sha256") != scope or review.get("scope_asset_count") != EXPECTED_COUNT):
        raise ValueError("The approved eleven-identity scope changed.")
    if canonical_sha256(records) != EXPECTED_REVIEW_SHA256 or review.get("canonical_review_sha256") != EXPECTED_REVIEW_SHA256:
        raise ValueError("Approved captions, original names or per-record evidence changed.")
    policy = review.get("policy")
    if (not isinstance(policy, dict) or policy.get("review_status") != "reviewed"
            or policy.get("review_date") != "2026-11-09"
            or canonical_sha256(policy) != EXPECTED_POLICY_SHA256
            or policy.get("scope_asset_ids_sha256") != EXPECTED_IDS_SHA256):
        raise ValueError("The exact reviewed public policy is required.")
    source = review.get("source")
    if (review.get("source_id") != SOURCE_ID or canonical_sha256(source) != EXPECTED_SOURCE_SHA256
            or not isinstance(source, dict) or source.get("input_sha256") != EXPECTED_REVIEW_SHA256
            or source.get("policy_sha256") != EXPECTED_POLICY_SHA256):
        raise ValueError("The separate technical-caption source changed.")
    for asset_id, row in records.items():
        description = row["technical_description"]
        evidence = description["evidence"]
        if (set(row["base"]) != set(BASE_KEYS) or description["quality"] != QUALITY
                or description["language"] != "en" or description["source_id"] != SOURCE_ID
                or description["source_date"] != "2026-11-09"
                or not description["text"].startswith("Technical record \u00b7 ")
                or evidence["asset_id"] != asset_id
                or evidence["is_canonical_name"] is not False):
            raise ValueError("Technical-caption schema or exact evidence is invalid.")
    return records, source


def apply_review(catalog, provenance, review_manifest):
    """Return deep-copied (catalog, provenance, audit); never rename or mutate inputs."""
    records, source = _validate_review(review_manifest)
    if (not isinstance(catalog, dict) or not isinstance(catalog.get("assets"), dict)
            or not isinstance(provenance, dict) or not isinstance(provenance.get("sources"), dict)):
        raise ValueError("Catalog assets and registered source objects are required.")
    updated_catalog, updated_sources = deepcopy(catalog), deepcopy(provenance)
    existing_source = updated_sources["sources"].get(SOURCE_ID)
    if SOURCE_ID in updated_sources["sources"] and existing_source != source:
        raise ValueError("A different source already uses the technical-caption source ID.")
    added, unchanged, future_names = [], [], []
    for asset_id, reviewed in records.items():
        record = updated_catalog["assets"].get(asset_id)
        if not isinstance(record, dict):
            raise ValueError("Approved technical-caption asset is missing: " + asset_id)
        base = reviewed["base"]
        if any(record.get(key) != base[key] for key in ("kind", "internal_ref", "loot_id")):
            raise ValueError("Approved asset identity changed: " + asset_id)
        current_base = {key: deepcopy(record.get(key)) for key in BASE_KEYS}
        if current_base != base:
            # This does not grant that quality. The release gate independently
            # checks a future real name and its exact evidence before counting it.
            if (record.get("quality") not in NAME_QUALITIES or not isinstance(record.get("name"), str)
                    or not record["name"].strip()):
                raise ValueError("Unreviewed original name/evidence fields changed: " + asset_id)
            future_names.append(asset_id)
        expected = reviewed["technical_description"]
        existing = record.get("technical_description")
        if existing is not None and existing != expected:
            raise ValueError("A conflicting technical caption already exists: " + asset_id)
        if existing == expected:
            unchanged.append(asset_id)
        else:
            record["technical_description"] = deepcopy(expected)
            added.append(asset_id)
    updated_sources["sources"][SOURCE_ID] = deepcopy(source)
    stripped = deepcopy(updated_catalog)
    for asset_id in records:
        if "technical_description" not in catalog["assets"][asset_id]:
            stripped["assets"][asset_id].pop("technical_description", None)
    if stripped != catalog:
        raise ValueError("Technical-caption transform changed original catalog fields.")
    audit = {"scope_asset_count": EXPECTED_COUNT, "scope_asset_ids_sha256": EXPECTED_IDS_SHA256,
             "canonical_review_sha256": EXPECTED_REVIEW_SHA256, "policy_sha256": EXPECTED_POLICY_SHA256,
             "source_id": SOURCE_ID, "description_quality": QUALITY,
             "added": len(added), "already_present": len(unchanged), "added_ids": added,
             "preserved_future_real_name_ids": future_names, "original_catalog_fields_unchanged": True,
             "original_name_qualities_unchanged": True, "original72_policy_unchanged": True,
             "applied": False}
    return updated_catalog, updated_sources, audit


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
    catalog, sources, audit = apply_review(_decode(originals[catalog_path]), _decode(originals[sources_path]), _decode(review_raw))
    updates = {catalog_path: _encoded(catalog), sources_path: _encoded(sources)}
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
