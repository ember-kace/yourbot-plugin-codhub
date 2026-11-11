"""Check reviewed item-artwork identities and every content-addressed Pages image."""
from collections import Counter
import argparse
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import warnings

from PIL import Image

try:
    from .native_artwork_release import _lossless_chunks, _safe_file
except ImportError:
    from native_artwork_release import _lossless_chunks, _safe_file


ROOT = Path(__file__).resolve().parents[1]
RESOURCE = "cod_hub/data/item-artwork.json"
SOURCE_ID = "mw4-native-item-artwork-current-2026-11-11"
REVIEWED_INDEX_SHA256 = "c3ccd16e606392379540c580c9d9c0e2c9cc1ca955cc8087860af286b172fdbe"
MAX_INDEX_BYTES = 2_000_000
MAX_IMAGE_BYTES = 3_000_000
_ASSET = re.compile(r"[0-9a-f]{16}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_FIELDS = {"image_asset_id", "filename", "sha256", "width", "height", "alpha_extrema", "rgba_sha256", "format", "lossless", "scope"}


def reviewed_index(raw):
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= MAX_INDEX_BYTES or hashlib.sha256(raw).hexdigest() != REVIEWED_INDEX_SHA256:
        raise ValueError("Item artwork index differs from the reviewed current snapshot.")
    document = json.loads(raw)
    if (document.get("format_version") != 1 or document.get("game") != "mw4"
            or document.get("snapshot_date") != "2026-11-11" or document.get("source_id") != SOURCE_ID
            or document.get("maximum_delivery_edge") != 768 or not isinstance(document.get("images"), dict)
            or not isinstance(document.get("by_asset"), dict) or not 1 <= len(document["images"]) <= 10000):
        raise ValueError("Invalid reviewed item artwork scope.")
    for identity, record in document["images"].items():
        if not isinstance(identity, str) or not _ASSET.fullmatch(identity) or not isinstance(record, dict):
            raise ValueError("Invalid native image identity.")
        scope = record.get("scope")
        fields = _FIELDS | ({"canonical_full_image", "part_index"} if scope == "native_part_preview" else set())
        if (set(record) != fields or scope not in {"native_item_artwork", "native_part_preview"}
                or record.get("image_asset_id") != identity or not isinstance(record.get("sha256"), str)
                or not _HASH.fullmatch(record["sha256"]) or record.get("filename") != record["sha256"] + ".webp"
                or not isinstance(record.get("rgba_sha256"), str) or not _HASH.fullmatch(record["rgba_sha256"])
                or record.get("format") != "WEBP" or record.get("lossless") is not True
                or any(type(record.get(key)) is not int or not 1 <= record[key] <= 768 for key in ("width", "height"))
                or not isinstance(record.get("alpha_extrema"), list) or len(record["alpha_extrema"]) != 2
                or any(type(value) is not int or not 0 <= value <= 255 for value in record["alpha_extrema"])
                or record["alpha_extrema"][0] > record["alpha_extrema"][1]):
            raise ValueError("Invalid reviewed native image declaration.")
        if scope == "native_part_preview" and (record["canonical_full_image"] is not False
                or type(record["part_index"]) is not int or record["part_index"] != 0):
            raise ValueError("A native part preview cannot claim a full image or animation frame.")
    for identity, image in document["by_asset"].items():
        if not isinstance(identity, str) or not _ASSET.fullmatch(identity) or image not in document["images"]:
            raise ValueError("Invalid native artwork field association.")
    return document


def evaluate_captured(captured):
    try:
        document = reviewed_index(captured.get(RESOURCE))
        scopes = Counter(row["scope"] for row in document["images"].values())
        return {"ready": True, "image_identities": len(document["images"]),
                "physical_images": len({row["filename"] for row in document["images"].values()}),
                "asset_associations": len(document["by_asset"]), "scopes": dict(scopes), "issues": []}
    except (ValueError, TypeError, KeyError, UnicodeError) as error:
        return {"ready": False, "issues": [str(error)]}


def _check_image(raw, record):
    if not 1 <= len(raw) <= MAX_IMAGE_BYTES or hashlib.sha256(raw).hexdigest() != record["sha256"] or not _lossless_chunks(raw):
        raise ValueError("Item image bytes differ or contain unsupported metadata.")
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(BytesIO(raw)) as source:
            if source.format != "WEBP" or source.size != (record["width"], record["height"]) or getattr(source, "n_frames", 1) != 1:
                raise ValueError("Item image dimensions or static format differ.")
            source.load()
            image = source.convert("RGBA")
            if list(image.getchannel("A").getextrema()) != record["alpha_extrema"] or hashlib.sha256(image.tobytes()).hexdigest() != record["rgba_sha256"]:
                raise ValueError("Item image pixels or transparency differ.")


def evaluate_release(plugin_path=ROOT / "plugin", hosted_path=ROOT / "docs/artwork/items/v1"):
    try:
        raw = _safe_file(plugin_path, RESOURCE)
        document = reviewed_index(raw)
        records = document["images"]
        expected = {row["filename"] for row in records.values()}
        actual = {path.name for path in Path(hosted_path).iterdir()}
        if actual != expected:
            raise ValueError("Hosted item artwork directory differs from the reviewed file set.")
        checked, byte_count = set(), 0
        for record in records.values():
            # Distinct native identities may intentionally use identical pixels.
            if record["filename"] in checked:
                continue
            body = _safe_file(hosted_path, record["filename"])
            _check_image(body, record)
            checked.add(record["filename"])
            byte_count += len(body)
        return {**evaluate_captured({RESOURCE: raw}), "hosted_files_checked": len(checked), "hosted_bytes": byte_count}
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        return {"ready": False, "issues": [str(error)]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin", type=Path, default=ROOT / "plugin")
    parser.add_argument("--hosted", type=Path, default=ROOT / "docs/artwork/items/v1")
    args = parser.parse_args()
    report = evaluate_release(args.plugin, args.hosted)
    print(json.dumps(report, indent=2))
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
