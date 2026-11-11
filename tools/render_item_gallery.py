"""Create the public gallery index from reviewed plugin resources only."""
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "plugin")]
from cod_hub import item_artwork, item_catalog, native_artwork
from tools.item_catalog_release import evaluate_release


def main():
    report = evaluate_release()
    if not report["ready"]:
        raise ValueError(report["issues"])
    rows = []
    for kind in item_catalog.categories():
        for item, _ in item_catalog._items(kind["key"]):
            art = item_artwork.get_art(item)
            weapon_art = native_artwork.get_art(item) if item["kind"] == "weapon" else None
            rows.append({"id": item["id"], "kind": item["kind"], "name": item_catalog.display_name(item),
                         "image": weapon_art["filename"] if weapon_art else art["url"].rsplit("/", 1)[1] if art else None,
                         "source": "weapon_reference" if weapon_art else "item_artwork",
                         "note": weapon_art["caption"] + ". " + weapon_art["scope_text"] if weapon_art else None,
                         "scope": weapon_art["preview_kind"] if weapon_art else art["scope"] if art else None,
                         "context_labels": item.get("name_source") == "native_context_labels"})
    rows.sort(key=lambda row: (row["name"].casefold(), row["kind"], row["id"]))
    payload = {"snapshot_date": item_catalog.manifest()["snapshot_date"], "native_records": report["native_records"],
               "categories": item_catalog.categories(), "items": rows}
    output = ROOT / "docs/artwork/items/catalog.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf8")
    print(json.dumps({"named_items": len(rows), "items_with_art": sum(bool(row["image"]) for row in rows), "bytes": output.stat().st_size}))


if __name__ == "__main__":
    main()
