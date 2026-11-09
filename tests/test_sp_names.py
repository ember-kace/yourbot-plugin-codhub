"""Public name, source and native-code regressions for two campaign items."""
import json
from pathlib import Path
import unittest

from yourbot_sdk.testing import MockContext, make_event

from cod_hub import app, cards, catalog, hub

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/name-regressions.json"
INVENTORY = ROOT / "metadata/name-inventory.json"
SP_IDS = {"6af8eddcdc523762", "39083489619f2934"}
CAPS = ["interaction:respond", "storage:kv", "discord:send_message", "proxy:http"]


def read(path):
    return json.loads(path.read_text(encoding="utf8"))


class NativeSPNameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = read(ROOT / "plugin/cod_hub/data/catalog.json")
        cls.sources = read(ROOT / "plugin/cod_hub/data/facts-sources.json")["sources"]
        cls.records = {key: row for key, row in read(FIXTURE)["records"].items() if key in SP_IDS}

    def test_exact_names_raw_values_and_registered_english_source_claims(self):
        self.assertEqual(set(self.records), SP_IDS)
        for asset_id, expected in self.records.items():
            with self.subTest(asset=asset_id):
                asset = self.data["assets"][asset_id]
                self.assertEqual((asset["name"], asset["quality"]), (expected["name"], "native_localization"))
                self.assertEqual((asset["internal_ref"], asset["loot_id"]), (expected["internal_ref"], expected["loot_id"]))
                claims = [claim for claim in asset["name_claims"] if claim["source_id"] == expected["source_id"]]
                self.assertEqual(len(claims), 1)
                claim = claims[0]
                self.assertEqual((claim["name_hash"], claim["raw_name"], claim["name"]),
                                 (expected["selected_name_hash"], expected["raw_name"], expected["name"]))
                self.assertEqual((claim["quality"], claim["language"]), ("native_localization", "en"))
                source = self.sources[claim["source_id"]]
                self.assertEqual((source["kind"], source["language"]), ("native_localization", "en"))
                self.assertEqual(claim["source_date"], source["source_date"])
                self.assertNotIn("technical_description", asset)
                self.assertNotIn("internal_description", asset)

    def test_public_inventory_hashes_join_only_the_intended_native_items(self):
        inventory = read(INVENTORY)["assets"]
        self.assertEqual(len(inventory), 1264)
        for asset_id, expected in self.records.items():
            matches = [row for row in inventory if expected["selected_name_hash"] in row["localize_hashes"]]
            self.assertEqual([row["asset_id"] for row in matches], [asset_id])
            row = matches[0]
            self.assertEqual((row["internal_ref"], row["loot_id"]), (expected["internal_ref"], expected["loot_id"]))
        magazine = self.records["39083489619f2934"]
        self.assertTrue(magazine["root_name_is_placeholder"])
        self.assertNotEqual(magazine["root_name_hash"], magazine["nested_name_hash"])
        asset = self.data["assets"]["39083489619f2934"]
        self.assertFalse(any(c.get("name_hash") == magazine["root_name_hash"] for c in asset["name_claims"]))
        self.assertNotIn(magazine["root_raw_name"], asset["aliases"])

    def test_native_diagnostic_codes_preserve_bindings_and_render_verified_cards(self):
        cc = catalog.get_catalog()
        for asset_id, expected in self.records.items():
            with self.subTest(code=expected["code"]):
                native = cc.codec.decode(expected["code"])
                self.assertEqual(cc.codec.encode(native.prefix, native.indexes), expected["code"])
                selection = self.data["weapons"][expected["prefix"]]["slots"][expected["slot"]]["ids"][str(expected["native_id"])]
                self.assertEqual(selection["asset_id"], asset_id)
                build = app._named_build(catalog.resolve_build(expected["code"]))
                self.assertEqual(build["native_slots"][expected["slot"]], expected["native_id"])
                part = build["attachments"][0]
                self.assertEqual((part["asset_id"], part["loot_id"], part["name"]),
                                 (asset_id, expected["loot_id"], expected["name"]))
                embed = cards.build_embed(build)
                self.assertTrue(any(field["value"] == expected["name"] for field in embed["fields"]))
                self.assertIn("Verified English names", embed["footer"]["text"])
                self.assertNotIn("#PH:", json.dumps(embed))

    def test_real_sdk_slash_and_gui_import_create_private_named_cards(self):
        for expected in self.records.values():
            for handler, values in ((app.handle_build, {"options": {"code": expected["code"]}}),
                                    (hub.handle_import, {"modal_values": {"code": expected["code"], "title": ""}})):
                with self.subTest(name=expected["name"], handler=handler.__name__):
                    ctx = MockContext(server_id="999", plugin_id="yourbot-cod-hub", capabilities=CAPS)
                    event = make_event("interaction_create", interaction_type=3, user_id="111", channel_id="333", **values)
                    handler(ctx, event)
                    response = ctx.interaction.followups[-1]
                    self.assertTrue(response["ephemeral"])
                    self.assertTrue(any(f["value"] == expected["name"] for f in response["embeds"][0]["fields"]))
                    self.assertEqual(ctx.messages_sent, [])


if __name__ == "__main__":
    unittest.main()
