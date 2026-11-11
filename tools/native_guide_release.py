"""Stage and pin the reviewed offline native guide, without reading game files."""
from copy import deepcopy
import argparse
import hashlib
import json
from pathlib import Path
import stat
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from plugin.cod_hub import native_guide as guide
from tools.check_public_tree import text_issues


MANIFEST = "cod_hub/data/native-guide.json"
SOURCES = "cod_hub/data/native-guide-sources.json"
REVIEWED_DATA_SHA256 = "25bedf93c25cebc6bd714531387bbcf7248f962b66458ca727b023893963e1b4"
REVIEWED_SOURCES_SHA256 = "df72df7aaf47df40ebbbc339d83fc8a5cd298c97bb7c8fe9fa8c8c2698d0bbf0"
REVIEWED_COUNTS = {"records": 683, "resolved": 587, "held": 96, "tables": 8}


def canonical(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf8")


def build_resources(candidate, sources):
    """Accept normalized reference metadata only, never files from a game install."""
    if not isinstance(candidate, dict) or not isinstance(candidate.get("items"), dict):
        raise ValueError("Invalid native guide input.")
    data = deepcopy(candidate)
    rows = {}
    for original, row in data["items"].items():
        if not isinstance(original, str) or not isinstance(row, dict):
            raise ValueError("Invalid guide reference input.")
        identity = f"g{row.get('source_table_hash')}r{row.get('source_row')}"
        if identity in rows:
            raise ValueError("Duplicate source table/row reference.")
        row["id"] = identity
        row["quality"] = "native_localization" if row.get("status") == "resolved" else None
        rows[identity] = row
    data["items"] = rows
    guide.validate_document(data)
    raw = canonical(data)
    if len(raw) > guide.MAX_DATA_BYTES:
        raise ValueError("Native guide exceeds its bounded resource size.")
    if not isinstance(sources, dict) or set(sources) != {"sources"}:
        raise ValueError("Only the normalized guide source declarations may be staged.")
    metadata = {"catalog_sha256": hashlib.sha256(raw).hexdigest(), "catalog_records": len(rows),
                "reference_id_scope": "native_table_and_row_not_loot_id", "sources": deepcopy(sources["sources"])}
    guide.validate_sources(metadata, raw)
    record = metadata["sources"][guide.SOURCE_ID]
    if set(record) != {"kind", "title", "source_date", "sha256", "table_hashes", "english_source_sha256", "scope"}:
        raise ValueError("Guide source declarations contain unrelated metadata.")
    output = {MANIFEST: raw, SOURCES: canonical(metadata)}
    for value in output.values():
        text = value.decode("utf8")
        if text_issues(text) or any(token in text for token in ("Program Files", "cod-image-readonly", "zone_sha256", "cipher_sha256")):
            raise ValueError("Private source material cannot enter the public guide.")
    return output


def required_files():
    return [MANIFEST, SOURCES]


def evaluate_captured(captured):
    """Pin the exact two resources that will enter a plugin archive."""
    try:
        raw, source_raw = captured.get(MANIFEST), captured.get(SOURCES)
        for value, maximum, expected in ((raw, guide.MAX_DATA_BYTES, REVIEWED_DATA_SHA256),
                                         (source_raw, guide.MAX_SOURCE_BYTES, REVIEWED_SOURCES_SHA256)):
            if (not isinstance(value, bytes) or not 1 <= len(value) <= maximum
                    or hashlib.sha256(value).hexdigest() != expected):
                raise ValueError("Captured game guide differs from the reviewed current snapshot.")
        data, sources = guide._document(raw), guide._document(source_raw)
        guide.validate_document(data)
        guide.validate_sources(sources, raw)
        counts = {"records": len(data["items"]),
                  "resolved": sum(r["status"] == "resolved" for r in data["items"].values()),
                  "held": sum(r["status"] == "held" for r in data["items"].values()),
                  "tables": len({r["source_table_hash"] for r in data["items"].values()})}
        if counts != REVIEWED_COUNTS or sources["catalog_records"] != counts["records"]:
            raise ValueError("Captured game guide coverage differs from review.")
        if raw != canonical(data) or source_raw != canonical(sources):
            raise ValueError("Guide resources are not canonical reviewed metadata.")
        return {"ready": True, **counts, "snapshot_date": guide.SNAPSHOT,
                "data_sha256": REVIEWED_DATA_SHA256, "sources_sha256": REVIEWED_SOURCES_SHA256,
                "resource_bytes": len(raw) + len(source_raw), "issues": []}
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError) as error:
        return {"ready": False, "issues": [str(error)]}


def _safe_read(root, relative, maximum):
    root = Path(root).absolute()
    current = root
    for part in (None, *Path(relative).parts):
        if part is not None:
            current /= part
        info = current.lstat()
        if (stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
            raise ValueError("Linked game guide resource.")
    if not stat.S_ISREG(info.st_mode) or not current.resolve(strict=True).is_relative_to(root.resolve(strict=True)):
        raise ValueError("Invalid game guide file.")
    with current.open("rb") as stream:
        return stream.read(maximum + 1)


def evaluate_release(plugin_path=ROOT / "plugin"):
    try:
        return evaluate_captured({MANIFEST: _safe_read(plugin_path, MANIFEST, guide.MAX_DATA_BYTES),
                                  SOURCES: _safe_read(plugin_path, SOURCES, guide.MAX_SOURCE_BYTES)})
    except (OSError, ValueError, TypeError) as error:
        return {"ready": False, "issues": [str(error)]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path, nargs="?")
    parser.add_argument("--sources", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.candidate is None:
            if args.sources or args.output:
                raise ValueError("Staging requires reviewed guide and source metadata.")
            result = evaluate_release()
        else:
            if args.sources is None:
                raise ValueError("Provide the normalized guide source declarations.")
            resources = build_resources(guide._document(args.candidate.read_bytes()), guide._document(args.sources.read_bytes()))
            if args.output:
                if args.output.exists() and any(args.output.iterdir()):
                    raise ValueError("Use an empty staging directory.")
                for name, raw in resources.items():
                    path = args.output / Path(name).name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(raw)
            result = {"ready": True, "files": {name: {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
                                                for name, raw in resources.items()}}
        print(json.dumps(result, indent=2))
        return 0 if result["ready"] else 1
    except (OSError, ValueError, TypeError, KeyError, UnicodeError) as error:
        print(json.dumps({"ready": False, "issues": [str(error)]}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
