"""Public technical-caption policy stays separate from real item names."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from yourbot_sdk.testing import MockContext

from cod_hub import app, cards, catalog, hub
from cod_hub.codec import CodeError

try:
    from .test_internal_description_runtime import event, native_bindings, probe, read
except ImportError:
    from test_internal_description_runtime import event, native_bindings, probe, read

ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "metadata/policies/technical-descriptions.json"
INTERNAL = ROOT / "metadata/policies/internal-descriptions.json"
UTILITY = "0f8717576adcedb5"
EXPECTED_BINDINGS = {
    "082948453ab4d9e3": ("M02", "dynamic", 1),
    "110091e80861c775": ("P02", "calibration", 2),
    "1e7b5b0fc5497fbe": ("S08", "dynamic", 1),
    "252f48bbd0918446": ("R03", "dynamic", 1),
    "409a40a9e315c521": ("L03", "dynamic", 1),
    "427899df06f61aac": ("L02", "dynamic", 1),
    "456f6831d04ffc02": ("P03", "dynamic", 1),
    "4d268a4bccd417d0": ("R02", "dynamic", 1),
    "57cdf8fd235aa7b4": ("C03", "dynamic", 1),
    "67f19c6bad5b1c0d": ("A01", "dynamic", 1),
}
CAPS = ["interaction:respond", "storage:kv", "discord:send_message", "proxy:http"]


class TechnicalDescriptionRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = read(ROOT / "plugin/cod_hub/data/catalog.json")
        cls.sources = read(ROOT / "plugin/cod_hub/data/facts-sources.json")["sources"]
        cls.review = read(REVIEW)
        cls.scope = set(cls.review["records"])
        cls.schema = read(ROOT / "plugin/cod_hub/data/schema.json")
        cls.source = catalog.Catalog(deepcopy(cls.schema), deepcopy(cls.document))
        cls.bindings = native_bindings(cls.document, set(EXPECTED_BINDINGS))

    def test_exact_eleven_captions_preserve_original_identity_name_alias_and_claim_fields(self):
        self.assertEqual(self.scope, set(EXPECTED_BINDINGS) | {UTILITY})
        self.assertEqual({key for key, row in self.document["assets"].items() if row.get("technical_description")}, self.scope)
        self.assertNotIn("reviewed_technical_description", catalog.ENGLISH_QUALITIES)
        for asset_id, review in self.review["records"].items():
            with self.subTest(asset=asset_id):
                asset = self.document["assets"][asset_id]
                description = asset["technical_description"]
                self.assertEqual(description, review["technical_description"])
                self.assertEqual({key: asset.get(key) for key in review["base"]}, review["base"])
                self.assertEqual((description["quality"], description["language"]), ("reviewed_technical_description", "en"))
                self.assertTrue(description["text"].startswith("Technical record "))
                self.assertNotEqual(asset["name"], description["text"])
                self.assertNotIn(description["text"], asset.get("aliases", []))
                self.assertNotIn(description["text"], json.dumps(asset.get("name_claims", [])))
                self.assertEqual(self.sources[description["source_id"]]["kind"], "reviewed_technical_description")

    def test_original_seventy_two_internal_descriptions_remain_a_separate_policy(self):
        internal = read(INTERNAL)["records"]
        self.assertEqual(len(internal), 72)
        self.assertFalse(set(internal) & self.scope)
        for asset_id, expected in internal.items():
            self.assertEqual(self.document["assets"][asset_id]["internal_description"], expected["internal_description"])
            self.assertNotIn("technical_description", self.document["assets"][asset_id])
        self.assertEqual(len(self.document["reference_weapons"]), 35)

    def test_captions_and_internal_ids_stay_out_of_named_search_and_browse(self):
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
            self.assertNotIn("technical_description", json.dumps(rows))
        for asset_id in self.scope:
            asset = self.document["assets"][asset_id]
            for query in (asset_id, asset.get("internal_ref"), asset["technical_description"]["text"]):
                if not query:
                    continue
                for matches in (self.source.search(query, 25), self.source.search_attachments(query, limit=25)):
                    self.assertFalse(self.scope & {row["asset_id"] for row in matches})
                    self.assertNotIn("technical_description", json.dumps(matches))
        with self.assertRaises(CodeError):
            self.source.get_weapon("P01")

    def test_ten_native_attachment_probes_preserve_ids_and_reject_named_cards(self):
        self.assertEqual(sum(map(len, self.bindings.values())), 10)
        for asset_id, expected in EXPECTED_BINDINGS.items():
            with self.subTest(asset=asset_id):
                self.assertEqual(self.bindings[asset_id], [expected])
                code = probe(self.source, expected)
                native = self.source.codec.decode(code)
                self.assertEqual(self.source.codec.encode(native.prefix, native.indexes), code)
                build = self.source.resolve(code)
                selected = next(row for row in build["attachments"] if row["slot"] == expected[1])
                self.assertEqual((selected["asset_id"], selected["index"]), (asset_id, expected[2]))
                self.assertEqual(build["label_status"], "fallback")
                self.assertNotIn("technical_description", json.dumps(build))
                self.assertNotIn(self.document["assets"][asset_id]["technical_description"]["text"], json.dumps(cards.build_embed(build)))
                with self.assertRaisesRegex(ValueError, "without verified English names"):
                    app._named_build(build)
                with self.assertRaises(CodeError):
                    self.source.get_attachment(expected[0], asset_id)

    def test_sdk_slash_and_gui_reject_all_eleven_without_storage_public_or_http_writes(self):
        codes = {asset_id: probe(self.source, binding) for asset_id, binding in EXPECTED_BINDINGS.items()}
        self.assertTrue(self.document["weapons"]["P01"]["utility"])
        self.assertEqual(self.document["weapons"]["P01"]["asset_id"], UTILITY)
        utility_code = self.source.codec.encode("P01", [0] * len(self.source.schema.slots))
        native = self.source.codec.decode(utility_code)
        self.assertEqual(self.source.codec.encode(native.prefix, native.indexes), utility_code)
        with self.assertRaisesRegex(CodeError, "internal utility"):
            self.source.resolve(utility_code)
        codes[UTILITY] = utility_code
        for asset_id, code in codes.items():
            expected_error = "internal utility" if asset_id == UTILITY else "without verified English names"
            for handler, values in ((app.handle_build, {"options": {"code": code}}),
                                    (hub.handle_import, {"modal_values": {"code": code, "title": ""}})):
                with self.subTest(asset=asset_id, handler=handler.__name__):
                    ctx = MockContext(server_id="999", plugin_id="rmg84ete7r8b", capabilities=CAPS)
                    handler(ctx, event(**values))
                    response = ctx.interaction.followups[-1]
                    self.assertIn(expected_error, response["content"])
                    self.assertFalse(response.get("embeds"))
                    self.assertEqual(ctx.kv_writes, [])
                    self.assertEqual(ctx.messages_sent, [])
                    self.assertEqual(ctx.http.requests, [])

    def test_all_eight_recovered_names_remain_usable_without_technical_captions(self):
        records = read(ROOT / "tests/fixtures/name-regressions.json")["records"]
        self.assertEqual(len(records), 8)
        for asset_id, expected in records.items():
            with self.subTest(asset=asset_id):
                self.assertNotIn("technical_description", self.document["assets"][asset_id])
                build = app._named_build(self.source.resolve(expected["code"]))
                self.assertEqual((build["attachments"][0]["asset_id"], build["attachments"][0]["name"]),
                                 (asset_id, expected["name"]))
                embed = cards.build_embed(build)
                self.assertTrue(any(row["value"] == expected["name"] for row in embed["fields"]))
                self.assertNotIn("Technical record", json.dumps(embed))

    def test_future_genuine_name_supersedes_caption_without_copying_it_into_card_or_alias(self):
        # Synthetic future evidence only; never a production name or claim.
        asset_id, binding = next(iter(EXPECTED_BINDINGS.items()))
        document = deepcopy(self.document)
        name = "Verified Future Technical Attachment Test Fixture"
        description = document["assets"][asset_id]["technical_description"]["text"]
        document["assets"][asset_id].update(name=name, quality="official_reference")
        source = catalog.Catalog(deepcopy(self.schema), document)
        self.assertIn(asset_id, {row["asset_id"] for row in source.search_attachments(name, limit=25)})
        item = source.get_attachment(binding[0], asset_id)
        self.assertEqual(item["name"], name)
        self.assertNotIn("technical_description", json.dumps(item))
        self.assertNotIn(description, item.get("aliases", []))
        self.assertNotIn(asset_id, {row["asset_id"] for row in source.search_attachments(description, limit=25)})
        embed = cards.build_embed(app._named_build(source.resolve(probe(source, binding))))
        self.assertIn(name, json.dumps(embed))
        self.assertNotIn(description, json.dumps(embed))


if __name__ == "__main__":
    unittest.main()
