"""Versioned factual catalog and native-ID resolution, independent of the game."""
import json
from copy import deepcopy
from pathlib import Path
import re

from .codec import CodecSchema, NativeCodec, CodeError


DATA = Path(__file__).parent / "data"
SLOT_LABELS = {
    "apex": "Apex", "barrel": "Barrel", "stock": "Stock", "magazine": "Magazine",
    "night_vision_modifier": "Vision modifier", "muzzle": "Muzzle", "rear_grip": "Rear grip",
    "underbarrel": "Underbarrel grip", "laser": "Laser", "optic": "Optic",
    "launcher": "Underbarrel weapon", "ammunition": "Ammunition",
    "calibration": "Calibration", "dynamic": "Dynamic", "other": "Other",
}
GAME_LABELS = {"mw4": "Modern Warfare 4"}
ENGLISH_QUALITIES = {"user_capture", "published_fixture", "native_localization", "official_reference"}
REFERENCE_CLASS_KEYS = {"la": "U", "me": "melee"}
_cached = {}


def _term(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value).casefold()).strip()


def _search_aliases(record):
    """Retain historical claims in data, without searching rejected labels."""
    preferred = _term(record.get("name"))
    rejected = set()
    claims = record.get("name_claims", [])
    if isinstance(claims, list):
        for claim in claims:
            review = claim.get("preference_review") if isinstance(claim, dict) else None
            if isinstance(review, dict) and review.get("decision") == "prefer_native":
                old_name = review.get("current_name")
                if isinstance(old_name, str) and _term(old_name) != preferred:
                    rejected.add(_term(old_name))
    aliases = record.get("aliases", [])
    if not isinstance(aliases, list):
        return []
    return [deepcopy(alias) for alias in aliases
            if isinstance(alias.get("name") if isinstance(alias, dict) else alias, str)
            and _term(alias.get("name") if isinstance(alias, dict) else alias) not in rejected]


def _game(game):
    aliases = {"mw4": "mw4", "modernwarfare4": "mw4", "modern warfare 4": "mw4"}
    key = aliases.get(str(game).strip().lower())
    if not key:
        raise CodeError("Local native-code imports currently support Modern Warfare 4. Select MW4 for these codes.")
    return key


def _browse_query(value):
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > 160 or any(ord(c) < 32 for c in value):
        raise CodeError("Use a search of at most 160 characters.")
    return "" if value.strip().casefold() in {"all", "*"} else _term(value)


def _browse_rank(query, record, fields):
    if not query:
        return 0
    texts = [_term(record.get(key, "")) for key in fields]
    texts.extend(_term(a.get("name", "") if isinstance(a, dict) else a)
                 for a in _search_aliases(record))
    if query in texts:
        return 0
    if any(text.startswith(query) for text in texts):
        return 1
    if any(query in text for text in texts):
        return 2
    if all(any(part in text for text in texts) for part in query.split()):
        return 3
    return None


def _browse_page(items, page, page_size):
    if type(page) is not int or page < 1:
        raise CodeError("Choose a positive catalog page number.")
    if type(page_size) is not int or not 1 <= page_size <= 25:
        raise CodeError("Catalog pages support between 1 and 25 items.")
    pages = max(1, (len(items) + page_size - 1) // page_size)
    if page > pages:
        raise CodeError("That catalog page doesn't exist. Return to the previous page.")
    start = (page - 1) * page_size
    return {"items": deepcopy(items[start:start + page_size]), "page": page,
            "pages": pages, "total": len(items)}


class Catalog:
    def __init__(self, schema, catalog):
        self.schema_data = schema
        self.schema = CodecSchema.from_dict(schema)
        self.codec = NativeCodec(self.schema)
        self.data = catalog
        self.assets = catalog["assets"]
        self.weapons = catalog["weapons"]
        self.snapshot_date = schema["snapshot_date"]
        self.catalog_version = schema.get("format_version", 1)

    def _weapon(self, prefix, record):
        asset_id = record["asset_id"]
        asset = self.assets.get(asset_id, {})
        quality = asset.get("quality", "internal")
        name = asset.get("name") or f"Weapon {prefix}"
        if quality not in ENGLISH_QUALITIES:
            name = f"Untranslated weapon · {prefix}"
        return {
            "prefix": prefix, "asset_id": asset_id, "name": name,
            "internal_ref": asset.get("internal_ref"), "loot_id": asset.get("loot_id"),
            "quality": quality, "source_ids": asset.get("source_ids", []),
            "aliases": _search_aliases(asset), "metadata_locked": bool(record.get("metadata_locked")),
            "utility": bool(record.get("utility")), "native_supported": True,
            "snapshot_date": self.snapshot_date, "game": self.schema.game,
            "class": record.get("class") or self.schema_data.get("classes", {}).get(prefix[0], {}).get("label", ""),
            "stats": asset.get("stats", {}), "base_stats": asset.get("base_stats", {}),
        }

    def resolve(self, code):
        decoded = self.codec.decode(code)
        record = self.weapons.get(decoded.prefix)
        if not record:
            raise CodeError(f"No assigned MW4 weapon exists for {decoded.prefix} in this catalog snapshot.")
        if record.get("utility"):
            raise CodeError("This prefix identifies an internal utility, not a supported player weapon.")
        weapon = self._weapon(decoded.prefix, record)
        attachments, unknowns, notes = [], [], []
        if decoded.unknown_bits:
            unknowns.append("The code contains packed data outside this snapshot's slot layout; its original data is preserved.")
        locked = weapon["metadata_locked"]
        for slot, index in zip(self.schema.slots, decoded.indexes):
            if index == 0:
                continue
            slot_data = record.get("slots", {}).get(slot.key, {})
            ui_slot = record.get("ui_slot_labels", {}).get(slot.key)
            slot_label = ui_slot.replace("-", " ").title() if ui_slot else SLOT_LABELS.get(slot.key, slot.key)
            selected = slot_data.get("ids", {}).get(str(index))
            if not selected or not selected.get("asset_id"):
                state = "reserved" if index in slot_data.get("reserved_ids", []) else "unassigned"
                unknowns.append(f"{SLOT_LABELS.get(slot.key, slot.key)} ID {index} is {state} in this catalog.")
                attachments.append({
                    "slot": slot.key, "slot_label": slot_label, "index": index,
                    "asset_id": None, "internal_ref": None,
                    "name": f"Unresolved attachment · ID {index}", "quality": "unresolved", "source_ids": [],
                })
                continue
            asset_id = selected["asset_id"]
            asset = self.assets.get(asset_id, {})
            quality = asset.get("quality", "internal")
            label = asset.get("name")
            if not label or quality not in ENGLISH_QUALITIES:
                label = f"Untranslated {slot_label.lower()} · ID {index}"
            if not asset.get("internal_ref"):
                notes.append(f"{SLOT_LABELS.get(slot.key, slot.key)} ID {index} has a known item ID but no readable catalog identifier.")
            item = {
                "slot": slot.key, "slot_label": slot_label, "index": index,
                "asset_id": asset_id, "internal_ref": asset.get("internal_ref"),
                "loot_id": asset.get("loot_id"), "name": label, "quality": quality,
                "source_ids": asset.get("source_ids", []), "aliases": _search_aliases(asset),
                "metadata_locked": bool(selected.get("metadata_locked")),
            }
            attachments.append(item)
            locked = locked or item["metadata_locked"]
        if locked:
            notes.append("The source catalog flags a selected item as locked; in-game availability depends on the current game and account.")
        if not decoded.input_was_canonical:
            notes.append("Spacing, case or code grouping was normalized without changing the packed values.")
        qualities = [weapon["quality"]] + [a["quality"] for a in attachments]
        fallback = any(q not in ENGLISH_QUALITIES for q in qualities)
        label_status = "fallback" if fallback else ("verified" if all(q == "user_capture" for q in qualities) else "mixed")
        return {
            "game": self.schema.game, "game_label": GAME_LABELS.get(self.schema.game, self.schema.game),
            "code": decoded.canonical_code, "weapon": weapon, "attachments": attachments,
            "native_slots": {slot.key: index for slot, index in zip(self.schema.slots, decoded.indexes)},
            "native_version": decoded.version, "unknowns": unknowns, "notes": list(dict.fromkeys(notes)),
            "identity_status": "partial" if unknowns else "resolved", "label_status": label_status,
            "snapshot_date": self.snapshot_date, "catalog_version": self.catalog_version,
            "source_ids": list(dict.fromkeys(weapon["source_ids"] + [s for a in attachments for s in a["source_ids"]])),
        }

    def search(self, query, limit=10):
        query = _term(query)
        if not query or len(query) > 100:
            return []
        limit = max(1, min(int(limit), 25))
        candidates = [self._weapon(p, w) for p, w in self.weapons.items() if not w.get("utility")]
        seen = {(w.get("internal_ref") or "").removesuffix("_mp") for w in candidates}
        for reference in self.data.get("reference_weapons", []):
            if (reference.get("native_prefix") in self.weapons
                    or (reference.get("internal_ref") or "").removesuffix("_mp") in seen):
                continue
            w = dict(reference)
            w.update({"game": self.schema.game, "native_supported": False,
                      "prefix": reference.get("native_prefix"), "snapshot_date": self.snapshot_date})
            w.setdefault("name", reference.get("internal_ref") or "Untranslated weapon")
            w.setdefault("quality", "internal")
            w.setdefault("stats", {})
            w["aliases"] = _search_aliases(w)
            candidates.append(w)
        matches = []
        for weapon in candidates:
            texts = [_term(weapon.get(k, "")) for k in ("name", "prefix", "internal_ref", "class")]
            aliases = _search_aliases(weapon)
            texts.extend(_term(a.get("name", "") if isinstance(a, dict) else a) for a in aliases)
            if query in {"all", "*"}:
                score = 5
            elif query in texts:
                score = 0
            elif any(t.startswith(query) for t in texts):
                score = 1
            elif any(query in t for t in texts):
                score = 2
            elif all(any(part in t for t in texts) for part in query.split()):
                score = 3
            else:
                continue
            matches.append((score, weapon["name"].casefold(), weapon))
        return [w for _, _, w in sorted(matches, key=lambda x: (x[0], x[1]))[:limit]]

    def search_attachments(self, query, weapon=None, limit=10):
        query = _term(query)
        if not query or len(query) > 100:
            return []
        selected_prefix = None
        if weapon:
            wanted = _term(weapon)
            found = [w for w in self.search(weapon, 25)
                     if w.get("prefix") and (wanted == _term(w["prefix"]) or wanted == _term(w["name"]))]
            if len(found) != 1:
                raise CodeError("Choose an exact weapon name or its prefix, such as A01, to filter attachments.")
            selected_prefix = found[0]["prefix"]
        matches = {}
        for prefix, record in self.weapons.items():
            if record.get("utility") or (selected_prefix and selected_prefix != prefix):
                continue
            weapon_info = self._weapon(prefix, record)
            for slot_key, slot in record.get("slots", {}).items():
                for index, selection in slot.get("ids", {}).items():
                    asset_id = selection.get("asset_id")
                    if not asset_id:
                        continue
                    asset = self.assets.get(asset_id, {})
                    quality = asset.get("quality", "internal")
                    name = asset.get("name")
                    # Slash-command search follows the same named-item scope
                    # as the card browser. Keep unresolved identities in the
                    # raw catalog/release audit, never promote them to results.
                    if (quality not in ENGLISH_QUALITIES or not isinstance(name, str)
                            or not name.strip()):
                        continue
                    texts = [_term(name), _term(asset.get("internal_ref")), _term(slot_key)]
                    texts.extend(_term(a.get("name", "") if isinstance(a, dict) else a) for a in _search_aliases(asset))
                    if query == "all":
                        score = 5
                    elif query in texts:
                        score = 0
                    elif any(t.startswith(query) for t in texts):
                        score = 1
                    elif any(query in t for t in texts):
                        score = 2
                    elif all(any(q in t for t in texts) for q in query.split()):
                        score = 3
                    else:
                        continue
                    if asset_id not in matches:
                        ui_slot = record.get("ui_slot_labels", {}).get(slot_key)
                        matches[asset_id] = {
                            "asset_id": asset_id, "name": name, "internal_ref": asset.get("internal_ref"),
                            "loot_id": asset.get("loot_id"), "quality": quality,
                            "slot_label": ui_slot.replace("-", " ").title() if ui_slot else SLOT_LABELS.get(slot_key, slot_key),
                            "source_ids": asset.get("source_ids", []), "aliases": _search_aliases(asset),
                            "configured_for": [], "snapshot_date": self.snapshot_date, "_score": score,
                        }
                    matches[asset_id]["configured_for"].append({
                        "prefix": prefix, "name": weapon_info["name"], "slot": slot_key, "index": int(index),
                        "metadata_locked": bool(selection.get("metadata_locked")),
                    })
        return sorted(matches.values(), key=lambda x: (x["_score"], x["name"].casefold()))[:max(1, min(int(limit), 25))]

    def _browse_weapon_records(self):
        """Named player weapons only; retain all raw identity tables untouched."""
        candidates, seen_ids, seen_refs = [], set(), set()
        for prefix, record in sorted(self.weapons.items()):
            asset = self.assets.get(record["asset_id"], {})
            if (record.get("utility") or asset.get("quality") not in ENGLISH_QUALITIES
                    or not isinstance(asset.get("name"), str) or not asset["name"].strip()):
                continue
            weapon = self._weapon(prefix, record)
            weapon.update(id=prefix, class_key=prefix[0])
            candidates.append(weapon)
            seen_ids.add(weapon["asset_id"])
            if weapon.get("internal_ref"):
                seen_refs.add(weapon["internal_ref"].removesuffix("_mp"))
        for reference in self.data.get("reference_weapons", []):
            asset_id = reference.get("asset_id")
            ref = (reference.get("internal_ref") or "").removesuffix("_mp")
            if (reference.get("utility") or reference.get("quality") not in ENGLISH_QUALITIES
                    or not isinstance(reference.get("name"), str) or not reference["name"].strip()
                    or asset_id in seen_ids or (ref and ref in seen_refs)):
                continue
            # An assigned native record must never re-enter as a reference-only
            # weapon just because its native name was rejected above.
            if any(r.get("asset_id") == asset_id for r in self.weapons.values()):
                continue
            native_prefix = reference.get("native_prefix")
            parts = ref.split("_")
            class_key = (native_prefix[0] if native_prefix and native_prefix in self.weapons
                         else REFERENCE_CLASS_KEYS.get(parts[1] if len(parts) > 1 else ""))
            weapon = dict(reference)
            weapon["aliases"] = _search_aliases(reference)
            weapon.update(id=asset_id, prefix=None, class_key=class_key,
                          native_supported=False, game=self.schema.game, snapshot_date=self.snapshot_date,
                          metadata_locked=bool(reference.get("metadata_locked")))
            weapon["class"] = self._browse_class_label(class_key)
            weapon.setdefault("stats", {})
            weapon.setdefault("base_stats", {})
            candidates.append(weapon)
            seen_ids.add(asset_id)
            if ref:
                seen_refs.add(ref)
        return sorted(candidates, key=lambda w: (w["name"].casefold(), w["id"]))

    def _browse_class_label(self, key):
        if key == "melee":
            return "Melee"
        return self.schema_data.get("classes", {}).get(key, {}).get("label", "Other weapons")

    def list_weapon_classes(self):
        counts = {}
        for weapon in self._browse_weapon_records():
            key = weapon["class_key"]
            if key:
                counts[key] = counts.get(key, 0) + 1
        keys = [key for key in self.schema_data.get("classes", {}) if key in counts]
        keys.extend(key for key in counts if key not in keys)
        return [{"key": key, "label": self._browse_class_label(key), "count": counts[key]}
                for key in keys]

    def browse_weapons(self, class_key=None, query="", page=1, page_size=10):
        query = _browse_query(query)
        if class_key is not None:
            if not isinstance(class_key, str):
                raise CodeError("Choose a weapon category from the menu.")
            key = class_key.strip()
            class_key = None if key.casefold() in {"", "all"} else ("melee" if key.casefold() == "melee" else key.upper())
            if class_key and class_key not in self.schema_data.get("classes", {}) and class_key != "melee":
                raise CodeError("Choose a weapon category from the menu.")
        matches = []
        for weapon in self._browse_weapon_records():
            if class_key and weapon["class_key"] != class_key:
                continue
            rank = _browse_rank(query, weapon, ("name", "prefix", "asset_id", "internal_ref", "class"))
            if rank is not None:
                matches.append((rank, weapon["name"].casefold(), weapon["id"], weapon))
        matches.sort(key=lambda match: match[:3])
        result = _browse_page([match[3] for match in matches], page, page_size)
        result.update(class_key=class_key, query=query, snapshot_date=self.snapshot_date)
        return result

    def get_weapon(self, identifier):
        if not isinstance(identifier, str) or not identifier.strip() or len(identifier) > 160:
            raise CodeError("Choose a weapon from the catalog.")
        wanted = identifier.strip().casefold()
        found = [weapon for weapon in self._browse_weapon_records()
                 if wanted in {str(weapon.get(key) or "").casefold()
                               for key in ("id", "prefix", "asset_id", "name", "internal_ref")}]
        if len(found) != 1:
            raise CodeError("That weapon isn't in the named player catalog. Choose a weapon from the menu.")
        return deepcopy(found[0])

    def _browse_attachment_records(self, weapon):
        prefix = weapon.get("prefix")
        if not prefix or prefix not in self.weapons:
            return []
        record = self.weapons[prefix]
        rows = []
        slot_order = {slot.key: n for n, slot in enumerate(self.schema.slots)}
        for slot_key, group in record.get("slots", {}).items():
            for index, selection in group.get("ids", {}).items():
                asset_id = selection.get("asset_id")
                asset = self.assets.get(asset_id, {})
                if (asset.get("quality") not in ENGLISH_QUALITIES
                        or not isinstance(asset.get("name"), str) or not asset["name"].strip()):
                    continue
                ui_slot = record.get("ui_slot_labels", {}).get(slot_key)
                slot_label = ui_slot.replace("-", " ").title() if ui_slot else SLOT_LABELS.get(slot_key, slot_key)
                binding = {"prefix": prefix, "name": weapon["name"], "slot": slot_key,
                           "index": int(index), "metadata_locked": bool(selection.get("metadata_locked"))}
                rows.append({"id": f"{slot_key}:{index}", "binding_id": f"{slot_key}:{index}",
                             "asset_id": asset_id, "name": asset["name"], "quality": asset["quality"],
                             "slot": slot_key, "slot_label": slot_label, "index": int(index),
                             "internal_ref": asset.get("internal_ref"), "loot_id": asset.get("loot_id"),
                             "source_ids": asset.get("source_ids", []), "aliases": _search_aliases(asset),
                             "metadata_locked": bool(selection.get("metadata_locked")),
                             "configured_for": [binding], "weapon_id": weapon["id"],
                             "snapshot_date": self.snapshot_date})
        return sorted(rows, key=lambda row: (slot_order.get(row["slot"], 99), row["name"].casefold(),
                                              row["index"], row["asset_id"]))

    def browse_attachments(self, weapon, slot=None, query="", page=1, page_size=10):
        weapon_info = self.get_weapon(weapon)
        query = _browse_query(query)
        if slot is not None:
            if not isinstance(slot, str):
                raise CodeError("Choose an attachment slot from the menu.")
            slot = slot.strip().casefold()
            if slot in {"", "all"}:
                slot = None
            elif slot not in SLOT_LABELS:
                raise CodeError("Choose an attachment slot from the menu.")
        rows = self._browse_attachment_records(weapon_info)
        slots = []
        for row in rows:
            entry = next((entry for entry in slots if entry["key"] == row["slot"]), None)
            if entry:
                entry["count"] += 1
            else:
                slots.append({"key": row["slot"], "label": row["slot_label"], "count": 1})
        matches = []
        for row in rows:
            if slot and row["slot"] != slot:
                continue
            rank = _browse_rank(query, row, ("name", "asset_id", "internal_ref", "slot", "slot_label"))
            if rank is not None:
                matches.append((rank, row))
        matches.sort(key=lambda item: item[0])  # Preserve schema-slot/name order inside a search rank.
        result = _browse_page([row for _, row in matches], page, page_size)
        result.update(weapon=weapon_info, weapon_id=weapon_info["id"], slot=slot, slots=slots,
                      query=query, snapshot_date=self.snapshot_date)
        if not weapon_info.get("native_supported"):
            result["note"] = "Attachment data is unavailable for this reference-only weapon."
        return result

    def get_attachment(self, weapon, identifier):
        weapon_info = self.get_weapon(weapon)
        if not isinstance(identifier, str) or not identifier or len(identifier) > 100:
            raise CodeError("Choose an attachment from the menu.")
        wanted = identifier.strip().casefold()
        matches = [row for row in self._browse_attachment_records(weapon_info)
                   if wanted in {row["binding_id"], row["asset_id"]}]
        if len(matches) != 1:
            raise CodeError("That attachment isn't in this weapon's named catalog. Choose it from the menu.")
        return deepcopy(matches[0])


def get_catalog(game="mw4"):
    game = _game(game)
    if game not in _cached:
        schema = json.loads((DATA / "schema.json").read_text(encoding="utf8"))
        facts = json.loads((DATA / "catalog.json").read_text(encoding="utf8"))
        if schema["game"] != game:
            raise CodeError("The installed catalog does not match the selected game.")
        _cached[game] = Catalog(schema, facts)
    return _cached[game]


def resolve_build(code, game="mw4"):
    return get_catalog(game).resolve(code)


def search_weapons(query, limit=10, game="mw4"):
    return get_catalog(game).search(query, limit)


def search_attachments(query, weapon=None, limit=10, game="mw4"):
    return get_catalog(game).search_attachments(query, weapon, limit)


def snapshot_info(game="mw4"):
    c = get_catalog(game)
    return {"game": c.schema.game, "date": c.snapshot_date,
            "weapons": sum(not w.get("utility") for w in c.weapons.values()),
            "assets": len(c.assets), "native_version": c.schema.version}


def list_weapon_classes(game="mw4"):
    return get_catalog(game).list_weapon_classes()


def browse_weapons(class_key=None, query="", page=1, page_size=10, game="mw4"):
    return get_catalog(game).browse_weapons(class_key, query, page, page_size)


def get_weapon(identifier, game="mw4"):
    return get_catalog(game).get_weapon(identifier)


def browse_attachments(weapon, slot=None, query="", page=1, page_size=10, game="mw4"):
    return get_catalog(game).browse_attachments(weapon, slot, query, page, page_size)


def get_attachment(weapon, identifier, game="mw4"):
    return get_catalog(game).get_attachment(weapon, identifier)
