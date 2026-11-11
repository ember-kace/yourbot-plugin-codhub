"""The expanded catalog keeps native identities, private navigation and bounded reads."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from yourbot_sdk.testing import MockContext, make_event

from cod_hub import item_catalog as catalog, item_catalog_ui as ui
from tests.test_hub_cards import assert_embed_limits


def record(identifier, kind, name, **extra):
    return {"id": identifier, "kind": kind, "name": name, "status": "resolved",
            "quality": "native_localization", "internal_ref": "synthetic_" + str(identifier),
            "season": "s0", "description": None, "unlock": None, **extra}


def fixture(root, records):
    """Write only synthetic item data, never production identity/name evidence."""
    categories = {}
    for kind in sorted({row["kind"] for row in records}):
        rows = sorted((row for row in records if row["kind"] == kind), key=lambda row: row["id"])
        category = {"total": len(rows), "resolved": 0, "held": 0, "source_internal": 0, "shards": []}
        for row in rows:
            category[row["status"]] += 1
        for index, start in enumerate(range(0, len(rows), 100)):
            chunk = rows[start:start + 100]
            raw = json.dumps(chunk, ensure_ascii=False, sort_keys=True).encode("utf8")
            digest = hashlib.sha256(raw).hexdigest()
            name = f"items/{kind}-{index:03d}-{digest}.json"
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            category["shards"].append({"file": name, "sha256": digest, "count": len(chunk)})
        categories[kind] = category
    result = {"format_version": 1, "game": "mw4", "snapshot_date": "2026-11-11",
              "native_records": len(records), "categories": categories}
    (root / "item-catalog.json").write_text(json.dumps(result), encoding="utf8")
    return result


def event(user="111", **extra):
    return make_event("interaction_create", interaction_type=3, user_id=user, channel_id="333", **extra)


def components(payload):
    return [item for row in payload.get("components", [])
            for item in (row.to_dict() if hasattr(row, "to_dict") else row)["components"]]


class ItemCatalogFixture:
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="cod-hub-item-catalog-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.rows = [record(index, "camo", f"Synthetic camo {index:03d}") for index in range(1, 206)]
        self.rows += [record(900, "attachment", "Synthetic angled grip"),
                      record(901, "weapon", "Synthetic rifle"),
                      record(902, "camo", None, status="held", quality=None),
                      record(903, "attachment", None, status="source_internal", quality=None)]
        self.document = fixture(self.root, self.rows)
        for key, value in (("DATA", self.root), ("MANIFEST_PATH", self.root / "item-catalog.json")):
            patcher = patch.object(catalog, key, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        catalog.clear_cache()
        self.addCleanup(catalog.clear_cache)

    def write_manifest(self, document):
        (self.root / "item-catalog.json").write_text(json.dumps(document), encoding="utf8")
        catalog.clear_cache()


class ItemCatalogTests(ItemCatalogFixture, unittest.TestCase):
    def test_context_labels_are_searchable_without_assigning_a_canonical_name(self):
        labels = [{"name": "Synthetic supply box", "name_hash": "1" * 16, "context_ids": ["1" * 64]},
                  {"name": "Synthetic ammunition box", "name_hash": "2" * 16, "context_ids": ["2" * 64]}]
        self.rows.append(record(904, "super", None, name_source="native_context_labels", display_labels=labels))
        fixture(self.root, self.rows)
        catalog.clear_cache()
        selected = catalog.browse(query="ammunition")['items'][0]
        item = catalog.get_item(selected['kind'], selected['shard'], selected['id'])
        self.assertIsNone(item['name'])
        self.assertEqual(catalog.display_name(item), "Synthetic supply box / Synthetic ammunition box")
        embed, _ = ui.item_view('111', item)
        self.assertIn('Native labels vary by context.', embed['description'])
        assert_embed_limits(self, embed)

    def test_all_pages_preserve_unique_ids_and_count_held_records_separately(self):
        first = catalog.browse("camo")
        self.assertEqual((first["total"], first["pages"], first["native_records"]), (205, 21, 209))
        rows = [row for page in range(1, first["pages"] + 1) for row in catalog.browse("camo", page=page)["items"]]
        self.assertEqual([row["id"] for row in rows], list(range(1, 206)))
        self.assertEqual(len({row["id"] for row in rows}), 205)
        categories = {row["key"]: row for row in catalog.categories()}
        self.assertEqual((categories["camo"]["total"], categories["camo"]["held"]), (206, 1))
        self.assertEqual(categories["attachment"]["source_internal"], 1)
        self.assertEqual(catalog.browse()["total"], 207)
        self.assertLessEqual(catalog._shard.cache_info().currsize, 2)

    def test_exact_lookup_and_search_work_across_shards_without_http_or_storage(self):
        self.assertEqual(catalog.browse(query="SYNTHETIC angled")["items"][0]["id"], 900)
        self.assertEqual(catalog.browse(query="205")["items"][0]["id"], 205)
        self.assertEqual(catalog.browse(query="synthetic_205")["items"][0]["id"], 205)
        found = catalog.get_item("camo", 2, 205)
        self.assertEqual((found["name"], found["snapshot_date"]), ("Synthetic camo 205", "2026-11-11"))
        found["name"] = "mutation"
        self.assertEqual(catalog.get_item("camo", 2, 205)["name"], "Synthetic camo 205")
        self.assertEqual(catalog.browse(query="unmatched")["items"], [])
        with self.assertRaises(ValueError):
            catalog.get_item("camo", 2, 902)

    def test_invalid_filters_and_paging_fail_cleanly(self):
        for kwargs in ({"kind": []}, {"kind": "absent"}, {"query": None}, {"query": "x" * 101},
                       {"page": 0}, {"page": True}, {"page": 999}, {"page_size": 26}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                catalog.browse(**kwargs)
        for args in (([], 0, 1), ("camo", True, 1), ("camo", -1, 1), ("camo", 0, True)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                catalog.get_item(*args)

    def test_corrupt_missing_and_escaping_resources_cannot_be_displayed(self):
        descriptor = self.document["categories"]["camo"]["shards"][0]
        path = self.root / descriptor["file"]
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "integrity"):
            catalog.browse("camo")
        path.unlink()
        catalog.clear_cache()
        with self.assertRaises(OSError):
            catalog.browse("camo")
        for relative in ("../escape.json", "/escape.json", "items\\escape.json", "items:stream"):
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                catalog._read(relative, 100)

    def test_invalid_count_duplicate_json_or_name_cannot_bypass_integrity_checks(self):
        wrong = deepcopy(self.document)
        wrong["native_records"] += 1
        self.write_manifest(wrong)
        with self.assertRaisesRegex(ValueError, "totals"):
            catalog.manifest()
        with self.assertRaises(ValueError):
            catalog._document(b'{"a":1,"a":2}')
        with self.assertRaises(ValueError):
            catalog._document(b'{"a":NaN}')
        for override in ({"name": ""}, {"quality": "guessed"}, {"id": True}, {"description": 7}):
            row = record(1, "camo", "Synthetic")
            row.update(override)
            fixture(self.root, [row])
            catalog.clear_cache()
            with self.subTest(override=override), self.assertRaises(ValueError):
                catalog.browse("camo")


class ItemCatalogJourneys(ItemCatalogFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.ctx = MockContext(server_id="999", plugin_id="rmg84ete7r8b",
                               capabilities=["interaction:respond", "storage:kv"])

    def test_gui_category_item_navigation_is_private_and_preserves_source_identity(self):
        ui.handle_component(self.ctx, event(custom_id="chx:open"))
        home = self.ctx.interaction.followups[-1]
        self.assertTrue(home["ephemeral"])
        self.assertEqual(self.ctx.interaction.defers, [{"ephemeral": True}])
        self.assertIn("209", home["embeds"][0]["description"])
        category = next(row for row in components(home) if row.get("placeholder") == "Choose an item category")
        ui.handle_component(self.ctx, event(custom_id=category["custom_id"], values=["camo"]))
        results = self.ctx.interaction.responses[-1]
        menu = next(row for row in components(results) if row.get("placeholder") == "Choose an item")
        self.assertTrue(results["ephemeral"])
        ui.handle_component(self.ctx, event(custom_id=menu["custom_id"], values=[menu["options"][0]["value"]]))
        card = self.ctx.interaction.responses[-1]
        self.assertEqual(card["embeds"][0]["title"], "Synthetic camo 001")
        self.assertIn({"name": "Catalog ID", "value": "1", "inline": True}, card["embeds"][0]["fields"])
        self.assertEqual(card["allowed_mentions"], {"parse": []})
        self.assertEqual(self.ctx.messages_sent, [])
        for payload in (home, results, card):
            assert_embed_limits(self, payload["embeds"][0])
            self.assertLessEqual(len(payload["components"]), 5)
            for component in components(payload):
                self.assertLessEqual(len(component["custom_id"]), 100)

    def test_other_users_cannot_read_or_mutate_a_personal_catalog_view(self):
        with patch.object(catalog, "categories", side_effect=AssertionError("read before owner check")):
            ui.handle_component(self.ctx, event("222", custom_id="chx:h:111:1"))
        self.assertIn("your own view", self.ctx.interaction.responses[-1]["content"])
        self.assertEqual(self.ctx.messages_sent, [])

    def test_slash_search_and_invalid_selection_return_private_responses(self):
        ui.handle_command(self.ctx, event(options=[{"name": "query", "value": "angled"}]))
        payload = self.ctx.interaction.followups[-1]
        self.assertIn("angled grip", payload["embeds"][0]["description"])
        self.assertTrue(payload["ephemeral"])
        ui.handle_component(self.ctx, event(custom_id="chx:i:111", values=["camo:2:902"]))
        self.assertIn("isn't available", self.ctx.interaction.responses[-1]["content"])
        ui.handle_component(self.ctx, event(custom_id="chx:c:111:0", values=["camo"]))
        self.assertIn("category page", self.ctx.interaction.responses[-1]["content"])

    def test_posting_requires_an_explicit_owner_action_and_uses_only_the_current_channel(self):
        self.ctx = MockContext(server_id="999", plugin_id="rmg84ete7r8b",
                               capabilities=["interaction:respond", "discord:send_message"])
        ui.handle_component(self.ctx, event(custom_id="chx:i:111", values=["camo:0:1"]))
        preview = self.ctx.interaction.responses[-1]
        post = next(row for row in components(preview) if row.get("label") == "Post card to channel")
        self.assertEqual(self.ctx.messages_sent, [])
        ui.handle_component(self.ctx, event("222", custom_id=post["custom_id"]))
        self.assertEqual(self.ctx.messages_sent, [])
        ui.handle_component(self.ctx, event(custom_id=post["custom_id"]))
        self.assertEqual(len(self.ctx.messages_sent), 1)
        posted = self.ctx.messages_sent[0]
        self.assertEqual(posted["channel_id"], "333")
        self.assertEqual(posted["embeds"][0]["title"], "Synthetic camo 001")
        self.assertEqual(posted["allowed_mentions"], {"parse": []})
        self.assertEqual(components(posted)[0]["custom_id"], "chx:open")
        self.assertTrue(self.ctx.interaction.followups[-1]["ephemeral"])


if __name__ == "__main__":
    unittest.main()
