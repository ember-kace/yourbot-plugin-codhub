"""Interactive browsing preserves identity and surfaces verified English only."""
import copy
import unittest

from cod_hub.catalog import (Catalog, ENGLISH_QUALITIES, browse_attachments,
                             browse_weapons, get_attachment, get_catalog,
                             get_weapon, list_weapon_classes)
from cod_hub.codec import CodeError


def all_weapon_items():
    first = browse_weapons(page_size=10)
    return [item for page in range(1, first["pages"] + 1)
            for item in browse_weapons(page=page, page_size=10)["items"]]


class BrowseCatalogTests(unittest.TestCase):
    def test_all_weapon_pages_are_deterministic_unique_and_player_only(self):
        items = all_weapon_items()
        self.assertEqual(len(items), 35)
        self.assertEqual(len({item["id"] for item in items}), 35)
        self.assertEqual(len({item["asset_id"] for item in items}), 35)
        self.assertEqual(sum(item["native_supported"] for item in items), 30)
        self.assertNotIn("P01", {item["id"] for item in items})
        self.assertEqual(items, all_weapon_items())
        self.assertEqual(items, sorted(items, key=lambda item: (item["name"].casefold(), item["id"])))
        for item in items:
            self.assertIn(item["quality"], ENGLISH_QUALITIES)
            self.assertEqual(item["id"], item["prefix"] or item["asset_id"])

    def test_classes_cover_native_weapons_and_reference_only_specials(self):
        classes = list_weapon_classes()
        self.assertEqual(sum(row["count"] for row in classes), 35)
        for category in classes:
            page = browse_weapons(class_key=category["key"], page_size=25)
            self.assertEqual(page["total"], category["count"])
            self.assertTrue(all(item["class_key"] == category["key"] for item in page["items"]))
        self.assertEqual(browse_weapons("U")["total"], 4)
        self.assertEqual(browse_weapons("MELEE")["items"][0]["name"], "FSS Carbon Edge 1095")
        self.assertEqual(browse_weapons("all")["total"], 35)

    def test_search_filters_and_empty_pages_have_explicit_behavior(self):
        self.assertEqual(browse_weapons(query="a01")["items"][0]["id"], "A01")
        self.assertEqual(browse_weapons(query="rex_ar_akilo")["items"][0]["name"], "Kastov 762")
        self.assertEqual(browse_weapons("U", query="RPG-8")["items"][0]["name"], "RPG-8")
        empty = browse_weapons("U", query="Kastov")
        self.assertEqual((empty["items"], empty["page"], empty["pages"], empty["total"]), ([], 1, 1, 0))
        self.assertEqual(browse_weapons(query="*")["total"], 35)
        with self.assertRaises(CodeError):
            browse_weapons(query="unmatched weapon query", page=2)

    def test_weapon_lookup_uses_exact_named_identity_and_returns_an_independent_value(self):
        native = get_weapon("a01")
        self.assertEqual(get_weapon(native["asset_id"])["id"], "A01")
        self.assertEqual(get_weapon("KASTOV 762")["id"], "A01")
        native["source_ids"].append("synthetic local mutation")
        self.assertNotIn("synthetic local mutation", get_weapon("A01")["source_ids"])
        for identifier in ("P01", get_catalog().weapons["P01"]["asset_id"], "Kastov", "../data", "", None):
            with self.subTest(identifier=identifier), self.assertRaises(CodeError):
                get_weapon(identifier)

    def test_attachment_pages_keep_native_binding_ids_and_slot_labels(self):
        page = browse_attachments("A01", page_size=25)
        items = [item for number in range(1, page["pages"] + 1)
                 for item in browse_attachments("A01", page=number, page_size=25)["items"]]
        self.assertEqual(len(items), page["total"])
        self.assertEqual(len({item["binding_id"] for item in items}), len(items))
        self.assertEqual(get_attachment("A01", "muzzle:3")["name"], "FIELD TAC 1.4 COMP")
        self.assertEqual(get_attachment("A01", "muzzle:3")["configured_for"][0]["index"], 3)
        bolt_items = browse_attachments("M03", slot="rear_grip")["items"]
        self.assertTrue(bolt_items)
        self.assertEqual({item["slot_label"] for item in bolt_items}, {"Bolt"})
        magazine_items = browse_attachments("A01", slot="magazine")["items"]
        self.assertNotIn(8, {item["index"] for item in magazine_items})

    def test_every_weapon_attachment_page_excludes_unverified_assets(self):
        catalog = get_catalog()
        forbidden = {identity for identity, record in catalog.assets.items()
                     if record.get("quality") not in ENGLISH_QUALITIES}
        for weapon in all_weapon_items():
            first = browse_attachments(weapon["id"], page_size=25)
            for number in range(1, first["pages"] + 1):
                for item in browse_attachments(weapon["id"], page=number, page_size=25)["items"]:
                    self.assertNotIn(item["asset_id"], forbidden)
                    self.assertIn(item["quality"], ENGLISH_QUALITIES)
                    selected = catalog.weapons[weapon["prefix"]]["slots"][item["slot"]]["ids"][str(item["index"])]
                    self.assertEqual(item["asset_id"], selected["asset_id"])

    def test_reference_weapon_has_no_invented_attachment_catalog(self):
        reference = browse_weapons("U")["items"][0]
        page = browse_attachments(reference["id"])
        self.assertEqual((page["items"], page["total"], page["pages"], page["slots"]), ([], 0, 1, []))
        self.assertIn("unavailable", page["note"])
        with self.assertRaises(CodeError):
            get_attachment(reference["id"], "muzzle:1")

    def test_invalid_filters_and_pages_are_rejected_without_data_changes(self):
        before = copy.deepcopy(get_catalog().data)
        for kwargs in ({"page": 0}, {"page": True}, {"page": 999}, {"page": "1"},
                       {"page_size": 26}, {"page_size": False}, {"page_size": 0},
                       {"class_key": "invented"}, {"query": "x" * 161}, {"query": "x\n"},
                       {"game": "bo7"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(CodeError):
                browse_weapons(**kwargs)
        for kwargs in ({"slot": "invented"}, {"page": 1000}, {"slot": True}, {"query": []}):
            with self.subTest(kwargs=kwargs), self.assertRaises(CodeError):
                browse_attachments("A01", **kwargs)
        self.assertEqual(get_catalog().data, before)

    def test_an_unverified_native_weapon_cannot_reenter_via_its_reference_copy(self):
        source = get_catalog()
        facts = copy.deepcopy(source.data)
        facts["assets"][facts["weapons"]["A01"]["asset_id"]]["quality"] = "internal"
        catalog = Catalog(source.schema_data, facts)
        items = catalog.browse_weapons(page_size=25)["items"]
        self.assertNotIn("A01", {row["id"] for row in items})
        self.assertNotIn(facts["weapons"]["A01"]["asset_id"], {row["asset_id"] for row in items})


if __name__ == "__main__":
    unittest.main()
