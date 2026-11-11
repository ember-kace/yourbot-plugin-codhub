"""Native references retain source identities and private, explicit sharing flows."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from yourbot_sdk.testing import MockContext, make_event

from cod_hub import native_guide as guide, native_guide_ui as ui
from tests.test_hub_cards import assert_embed_limits
from tools import native_guide_release as release


PLUGIN = Path(__file__).resolve().parents[1] / "plugin"
CAPTURED = {name: (PLUGIN / name).read_bytes() for name in release.required_files()}
DOCUMENT = json.loads(CAPTURED[release.MANIFEST])
SOURCE_DOCUMENT = json.loads(CAPTURED[release.SOURCES])


def event(user="111", **extra):
    options = dict(interaction_type=3, user_id=user, channel_id="333")
    options.update(extra)
    return make_event("interaction_create", **options)


def components(payload):
    return [component for row in payload.get("components", [])
            for component in (row.to_dict() if hasattr(row, "to_dict") else row)["components"]]


def menu(payload, placeholder):
    return next(c for c in components(payload) if c.get("placeholder") == placeholder)


def button(payload, label):
    return next(c["custom_id"] for c in components(payload) if c.get("label") == label)


def write_resources(root, document=DOCUMENT, sources=SOURCE_DOCUMENT):
    document, sources = deepcopy(document), deepcopy(sources)
    raw = release.canonical(document)
    sources["catalog_sha256"] = hashlib.sha256(raw).hexdigest()
    sources["catalog_records"] = len(document["items"])
    (root / "native-guide.json").write_bytes(raw)
    (root / "native-guide-sources.json").write_bytes(release.canonical(sources))


class NativeGuideDataTests(unittest.TestCase):
    def setUp(self):
        guide.clear_cache()
        self.addCleanup(guide.clear_cache)

    def test_every_resolved_reference_can_be_paged_without_fusing_duplicate_names(self):
        categories = guide.categories()
        self.assertEqual(sum(c["total"] for c in categories), 683)
        self.assertEqual(sum(c["resolved"] for c in categories), 587)
        self.assertEqual(sum(c["held"] for c in categories), 96)
        first = guide.browse()
        rows = [row for p in range(1, first["pages"] + 1) for row in guide.browse(page=p)["items"]]
        self.assertEqual(len(rows), 587)
        self.assertEqual(len({row["id"] for row in rows}), 587)
        for row in rows:
            item = guide.get_reference(row["id"])
            self.assertEqual(item["id"], f"g{item['source_table_hash']}r{item['source_row']}")
            self.assertIsInstance(item["native_id"], str)
            self.assertNotIn("loot_id", item)
        hajin = guide.browse("maps", "Hajin")["items"]
        self.assertGreater(len(hajin), 1)
        self.assertEqual(len({r["id"] for r in hajin}), len(hajin))
        self.assertGreater(len({r["internal_ref"] for r in hajin}), 1)
        self.assertEqual(guide.browse(query="Scavenger's Edge")["items"][0]["name"], "Scavenger's Edge")

    def test_native_numbers_are_not_loot_lookup_ids_and_held_rows_stay_hidden(self):
        held = next(row for row in DOCUMENT["items"].values() if row["status"] == "held")
        for identifier in (39450, "39450", held["id"], "g3717489cf4f58cber99999"):
            with self.subTest(identifier=identifier), self.assertRaises(ValueError):
                guide.get_reference(identifier)
        chosen = guide.browse("dmz")["items"][0]
        item = guide.get_reference(chosen["id"])
        operands = deepcopy(item["native_operands"])
        item["name"] = "Mutation"
        item["native_operands"][0] = "Mutation"
        unchanged = guide.get_reference(chosen["id"])
        self.assertEqual(unchanged["name"], chosen["name"])
        self.assertEqual(unchanged["native_operands"], operands)

    def test_bad_queries_categories_and_pages_are_rejected_before_file_reads(self):
        invalid = ({"category": []}, {"category": "loot"}, {"query": None}, {"query": "x" * 37},
                   {"page": True}, {"page": 0}, {"page_size": 26})
        with patch.object(guide, "_data", side_effect=AssertionError("read before validation")):
            for kwargs in invalid:
                with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                    guide.browse(**kwargs)
        self.assertEqual(guide.browse(query="no match zzz")["items"], [])
        with self.assertRaisesRegex(ValueError, "doesn't exist"):
            guide.browse(page=1000)

    def test_unexpanded_requirements_are_never_rendered_as_counts(self):
        example = next(row for row in DOCUMENT["items"].values()
                       if row["status"] == "resolved" and row["description_status"] == "source_template_operands_uninterpreted")
        item = guide.get_reference(example["id"])
        self.assertIn("&&", item["description_template"])
        embed, _ = ui.reference_view("111", item)
        self.assertEqual(embed["description"], ui.CONTEXT_REQUIREMENTS)
        self.assertNotIn("&&", str(embed))
        self.assertNotIn(item["native_operands"][0], embed["description"])
        for row in DOCUMENT["items"].values():
            if row["status"] != "resolved":
                continue
            embed, _ = ui.reference_view("111", guide.get_reference(row["id"]))
            assert_embed_limits(self, embed)
            self.assertNotIn("&&", str(embed))
            self.assertNotIn("#x", str(embed))


class NativeGuideResourceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="cod-hub-guide-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.patcher = patch.object(guide, "DATA", self.root)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        guide.clear_cache()
        self.addCleanup(guide.clear_cache)
        write_resources(self.root)

    def test_missing_corrupt_oversized_and_linked_fixed_resources_fail_closed(self):
        (self.root / "native-guide.json").write_bytes(b"{}")
        with self.assertRaisesRegex(ValueError, "integrity"):
            guide.browse()
        (self.root / "native-guide.json").write_bytes(b" " * (guide.MAX_DATA_BYTES + 1))
        with self.assertRaisesRegex(ValueError, "exceeds"):
            guide.browse()
        (self.root / "native-guide.json").unlink()
        with self.assertRaisesRegex(ValueError, "unavailable"):
            guide.browse()
        with patch.object(Path, "lstat", return_value=SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)):
            with self.assertRaisesRegex(ValueError, "Linked"):
                guide._read("native-guide.json", 100)
        with self.assertRaises(ValueError):
            guide._read("../native-guide.json", 100)
        with self.assertRaises(ValueError):
            guide._document(b'{"a":1,"a":2}')
        with self.assertRaises(ValueError):
            guide._document(b'{"a":NaN}')

    def test_resealed_metadata_cannot_invent_names_counts_or_loot_joins(self):
        named = next(key for key, row in DOCUMENT["items"].items() if row["status"] == "resolved")
        held = next(key for key, row in DOCUMENT["items"].items() if row["status"] == "held")
        templated = next(key for key, row in DOCUMENT["items"].items() if row["description_status"] == "source_template_operands_uninterpreted")
        for identifier, override in ((named, {"quality": "guessed"}), (held, {"name": "Invented"}),
                                     (named, {"loot_id": 39450}), (named, {"source_row": True}),
                                     (templated, {"description_display": "Get20 eliminations."})):
            document = deepcopy(DOCUMENT)
            document["items"][identifier].update(override)
            write_resources(self.root, document)
            guide.clear_cache()
            with self.subTest(override=override), self.assertRaises(ValueError):
                guide.browse()
        document = deepcopy(DOCUMENT)
        document["coverage"]["map"]["resolved"] += 1
        write_resources(self.root, document)
        guide.clear_cache()
        with self.assertRaisesRegex(ValueError, "coverage"):
            guide.browse()


class NativeGuideJourneys(unittest.TestCase):
    def setUp(self):
        guide.clear_cache()
        self.addCleanup(guide.clear_cache)
        self.ctx = MockContext(server_id="999", plugin_id="rmg84ete7r8b",
                               capabilities=["interaction:respond", "discord:send_message"])

    def test_launcher_category_detail_back_and_search_paging_are_private_and_offline(self):
        ui.handle_component(self.ctx, event(custom_id="chg:open"))
        home = self.ctx.interaction.followups[-1]
        self.assertTrue(home["ephemeral"])
        category = menu(home, "Choose a guide category")
        ui.handle_component(self.ctx, event(custom_id=category["custom_id"], values=["maps"]))
        browser = self.ctx.interaction.responses[-1]
        selector = menu(browser, "Choose a guide reference")
        chosen = selector["options"][0]
        ui.handle_component(self.ctx, event(custom_id=selector["custom_id"], values=[chosen["value"]]))
        card = self.ctx.interaction.responses[-1]
        self.assertEqual(card["embeds"][0]["title"], chosen["label"])
        self.assertIn("Reference ID", str(card["embeds"]))
        self.assertNotIn("Loot ID", str(card["embeds"]))
        ui.handle_component(self.ctx, event(custom_id=button(card, "Back to references")))
        self.assertIn("Page 1/3", self.ctx.interaction.responses[-1]["embeds"][0]["footer"]["text"])
        ui.handle_command(self.ctx, event(interaction_type=2, options={"category": "mastery", "query": "camo", "page": 1}))
        search = self.ctx.interaction.followups[-1]
        ui.handle_component(self.ctx, event(custom_id=button(search, "Next")))
        second = self.ctx.interaction.responses[-1]
        self.assertIn("Search: **camo**", second["embeds"][0]["description"])
        self.assertIn("Page 2/", second["embeds"][0]["footer"]["text"])
        for payload in (home, browser, card, search, second):
            self.assertTrue(payload["ephemeral"])
            self.assertEqual(payload["allowed_mentions"], {"parse": []})
            assert_embed_limits(self, payload["embeds"][0])
            self.assertLessEqual(len(payload["components"]), 5)
            for component in components(payload):
                self.assertLessEqual(len(component["custom_id"]), 100)
        self.assertEqual(self.ctx.messages_sent, [])
        self.assertEqual(self.ctx.http.requests, [])
        self.assertEqual(self.ctx.kv_writes, [])

    def test_other_owners_are_rejected_before_any_catalog_read_or_post(self):
        with patch.object(guide, "categories", side_effect=AssertionError("read before owner check")), patch.object(guide, "get_reference", side_effect=AssertionError("read before owner check")):
            for custom_id in ("chg:h:111", "chg:s:111:g3717489cf4f58cber1"):
                ui.handle_component(self.ctx, event("222", custom_id=custom_id))
                self.assertIn("your own private guide", self.ctx.interaction.responses[-1]["content"])
        self.assertEqual(self.ctx.messages_sent, [])
        ui.handle_component(self.ctx, event("222", custom_id="chg:open"))
        self.assertTrue(menu(self.ctx.interaction.followups[-1], "Choose a guide category")["custom_id"].startswith("chg:c:222:"))

    def test_posting_requires_an_explicit_owner_action_in_the_current_channel(self):
        ui.handle_command(self.ctx, event(options={"category": "maps", "query": "Hajin"}))
        browser = self.ctx.interaction.followups[-1]
        selector = menu(browser, "Choose a guide reference")
        ui.handle_component(self.ctx, event(custom_id=selector["custom_id"], values=[selector["options"][0]["value"]]))
        card = self.ctx.interaction.responses[-1]
        post = button(card, "Post card to channel")
        self.assertEqual(self.ctx.messages_sent, [])
        ui.handle_component(self.ctx, event("222", custom_id=post))
        self.assertEqual(self.ctx.messages_sent, [])
        ui.handle_component(self.ctx, event(custom_id=post, channel_id="444"))
        self.assertEqual(len(self.ctx.messages_sent), 1)
        published = self.ctx.messages_sent[0]
        self.assertEqual(published["channel_id"], "444")
        self.assertEqual(published["allowed_mentions"], {"parse": []})
        self.assertEqual(components(published)[0]["custom_id"], "chg:open")
        self.assertTrue(self.ctx.interaction.followups[-1]["ephemeral"])

    def test_invalid_or_out_of_page_selection_does_not_open_or_post_a_reference(self):
        ui.handle_component(self.ctx, event(custom_id="chg:i:111:maps:1:_", values=["39450"]))
        self.assertIn("this page", self.ctx.interaction.responses[-1]["content"])
        ui.handle_component(self.ctx, event(custom_id="chg:s:111:39450"))
        self.assertIn("Choose a reference", self.ctx.interaction.followups[-1]["content"])
        ui.handle_component(self.ctx, event(custom_id="chg:c:111:_", values=["loot"]))
        self.assertIn("category", self.ctx.interaction.responses[-1]["content"])
        ui.handle_component(self.ctx, event(custom_id="chg:p:111:all:0:_"))
        self.assertIn("page", self.ctx.interaction.responses[-1]["content"])
        self.assertEqual(self.ctx.messages_sent, [])

    def test_controls_fit_long_owners_and_queries_without_losing_search_context(self):
        owner = "9" * 22
        token = ui._pack("a" * guide.MAX_QUERY)
        self.assertLessEqual(len(ui._id("p", owner, "calling_cards", 1000, token)), 100)
        ui.handle_command(self.ctx, event(user=owner, options={"query": "a" * guide.MAX_QUERY}))
        payload = self.ctx.interaction.followups[-1]
        self.assertIn("No verified names match", payload["embeds"][0]["description"])
        self.assertTrue(payload["ephemeral"])


class NativeGuideReleaseTests(unittest.TestCase):
    def test_source_and_capture_pins_accept_only_the_reviewed_two_resources(self):
        self.assertTrue(release.evaluate_release()["ready"])
        self.assertEqual(release.evaluate_captured(CAPTURED)["resolved"], 587)
        rebuilt = release.build_resources(DOCUMENT, {"sources": SOURCE_DOCUMENT["sources"]})
        self.assertEqual(rebuilt, CAPTURED)
        for target in release.required_files():
            changed = dict(CAPTURED)
            changed[target] += b" "
            self.assertFalse(release.evaluate_captured(changed)["ready"])
            changed.pop(target)
            self.assertFalse(release.evaluate_captured(changed)["ready"])
        sources = deepcopy(SOURCE_DOCUMENT)
        sources["sources"][guide.SOURCE_ID]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "provenance"):
            release.build_resources(DOCUMENT, {"sources": sources["sources"]})
        document = deepcopy(DOCUMENT)
        next(iter(document["items"].values()))["loot_id"] = 39450
        with self.assertRaises(ValueError):
            release.build_resources(document, {"sources": SOURCE_DOCUMENT["sources"]})


if __name__ == "__main__":
    unittest.main()
