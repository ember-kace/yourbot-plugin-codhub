"""Public policy metadata never becomes a player-facing attachment name."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from yourbot_sdk.testing import MockContext, make_event

from cod_hub import app, cards, catalog, hub
from cod_hub.codec import CodeError

ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "metadata/policies/internal-descriptions.json"
TECHNICAL = ROOT / "metadata/policies/technical-descriptions.json"
CAPS = ["interaction:respond", "storage:kv", "discord:send_message", "proxy:http"]


def read(path):
    return json.loads(path.read_text(encoding="utf8"))


def native_bindings(document, wanted):
    result = {asset_id: [] for asset_id in wanted}
    for prefix, weapon in document["weapons"].items():
        for slot, group in weapon["slots"].items():
            for index, selection in group["ids"].items():
                if selection["asset_id"] in result:
                    result[selection["asset_id"]].append((prefix, slot, int(index)))
    return result


def probe(source, binding):
    prefix, slot, index = binding
    vector = [0] * len(source.schema.slots)
    vector[next(i for i, item in enumerate(source.schema.slots) if item.key == slot)] = index
    return source.codec.encode(prefix, vector)


def event(**values):
    return make_event("interaction_create", interaction_type=3, user_id="111", channel_id="333", **values)


class InternalDescriptionRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = read(ROOT / "plugin/cod_hub/data/catalog.json")
        cls.sources = read(ROOT / "plugin/cod_hub/data/facts-sources.json")["sources"]
        cls.review = read(REVIEW)
        cls.scope = set(cls.review["records"])
        cls.schema = read(ROOT / "plugin/cod_hub/data/schema.json")
        cls.source = catalog.Catalog(deepcopy(cls.schema), deepcopy(cls.document))
        cls.bindings = native_bindings(cls.document, cls.scope)

    def test_exact_policy_scope_keeps_descriptions_separate_and_original_fields(self):
        self.assertEqual(len(self.scope), 72)
        self.assertEqual({key for key, row in self.document["assets"].items() if row.get("internal_description")}, self.scope)
        self.assertNotIn("reviewed_internal_description", catalog.ENGLISH_QUALITIES)
        for asset_id, review in self.review["records"].items():
            with self.subTest(asset=asset_id):
                asset = self.document["assets"][asset_id]
                description = asset["internal_description"]
                self.assertEqual(description, review["internal_description"])
                self.assertEqual({key: asset.get(key) for key in review["base"]}, review["base"])
                self.assertEqual(description["quality"], "reviewed_internal_description")
                self.assertEqual(description["language"], "en")
                self.assertTrue(description["text"].startswith("Internal "))
                self.assertNotEqual(asset["name"], description["text"])
                self.assertNotIn(description["text"], asset.get("aliases", []))
                self.assertNotIn(description["text"], json.dumps(asset.get("name_claims", [])))
                self.assertEqual(self.sources[description["source_id"]]["kind"], "reviewed_internal_description")

    def test_unverified_descriptions_stay_out_of_named_search_and_browse(self):
        first = self.source.browse_weapons(page_size=25)
        weapons = list(first["items"])
        for page in range(2, first["pages"] + 1):
            weapons += self.source.browse_weapons(page=page, page_size=25)["items"]
        self.assertFalse(self.scope & {row["asset_id"] for row in weapons})
        for weapon in weapons:
            first = self.source.browse_attachments(weapon["id"], page_size=25)
            rows = list(first["items"])
            for page in range(2, first["pages"] + 1):
                rows += self.source.browse_attachments(weapon["id"], page=page, page_size=25)["items"]
            self.assertFalse(self.scope & {row["asset_id"] for row in rows})
            self.assertNotIn("internal_description", json.dumps(rows))
        for asset_id in self.scope:
            asset = self.document["assets"][asset_id]
            for query in (asset_id, asset.get("internal_ref"), asset["internal_description"]["text"]):
                if not query:
                    continue
                for matches in (self.source.search(query, 25), self.source.search_attachments(query, limit=25)):
                    self.assertFalse(self.scope & {row["asset_id"] for row in matches})
                    self.assertNotIn("internal_description", json.dumps(matches))

    def test_all_native_probes_preserve_identity_and_block_unverified_named_cards(self):
        self.assertEqual(sum(map(len, self.bindings.values())), 202)
        for asset_id, bindings in self.bindings.items():
            self.assertTrue(bindings, asset_id)
            for binding in bindings:
                with self.subTest(asset=asset_id, binding=binding):
                    code = probe(self.source, binding)
                    native = self.source.codec.decode(code)
                    self.assertEqual(self.source.codec.encode(native.prefix, native.indexes), code)
                    build = self.source.resolve(code)
                    selected = next(row for row in build["attachments"] if row["slot"] == binding[1])
                    self.assertEqual((selected["asset_id"], selected["index"]), (asset_id, binding[2]))
                    self.assertNotIn("internal_description", json.dumps(build))
                    with self.assertRaisesRegex(ValueError, "without verified English names"):
                        app._named_build(build)
                    with self.assertRaises(CodeError):
                        self.source.get_attachment(binding[0], asset_id)

    def test_sdk_slash_and_gui_rejection_has_no_storage_public_message_or_http(self):
        for asset_id, bindings in self.bindings.items():
            code = probe(self.source, bindings[0])
            for handler, values in ((app.handle_build, {"options": {"code": code}}),
                                    (hub.handle_import, {"modal_values": {"code": code, "title": ""}})):
                with self.subTest(asset=asset_id, handler=handler.__name__):
                    ctx = MockContext(server_id="999", plugin_id="yourbot-cod-hub", capabilities=CAPS)
                    handler(ctx, event(**values))
                    response = ctx.interaction.followups[-1]
                    self.assertIn("without verified English names", response["content"])
                    self.assertFalse(response.get("embeds"))
                    self.assertEqual(ctx.kv_writes, [])
                    self.assertEqual(ctx.messages_sent, [])
                    self.assertEqual(ctx.http.requests, [])

    def test_future_genuine_name_remains_eligible_without_using_description_as_alias(self):
        # Synthetic future evidence only; no production record is changed.
        asset_id = next(iter(self.scope))
        document = deepcopy(self.document)
        name = "Verified Future Attachment Test Fixture"
        document["assets"][asset_id].update(name=name, quality="official_reference")
        source = catalog.Catalog(deepcopy(self.schema), document)
        binding = self.bindings[asset_id][0]
        description = document["assets"][asset_id]["internal_description"]["text"]
        self.assertIn(asset_id, {row["asset_id"] for row in source.search_attachments(name, limit=25)})
        item = source.get_attachment(binding[0], asset_id)
        self.assertEqual(item["name"], name)
        self.assertNotIn("internal_description", json.dumps(item))
        self.assertNotIn(description, item.get("aliases", []))
        embed = cards.build_embed(app._named_build(source.resolve(probe(source, binding))))
        self.assertIn(name, json.dumps(embed))
        self.assertNotIn(description, json.dumps(embed))

    def test_separate_technical_policy_and_eight_recovered_names_do_not_expand_internal_scope(self):
        technical = set(read(TECHNICAL)["records"])
        recovered = set(read(ROOT / "tests/fixtures/name-regressions.json")["records"])
        self.assertEqual(len(technical), 11)
        self.assertEqual(len(recovered), 8)
        self.assertFalse(self.scope & (technical | recovered))
        for asset_id in technical | recovered:
            self.assertNotIn("internal_description", self.document["assets"][asset_id])


if __name__ == "__main__":
    unittest.main()
