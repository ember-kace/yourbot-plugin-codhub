import base64
import json
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
import runpy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from yourbot_sdk.testing import MockClock, MockContext, make_event

from cod_hub import app
from cod_hub.store import BuildStore, MAX_SAVED, PREVIEW_SLOTS, PREVIEW_TTL


CODE = "A01-42J19-BU11"
CAPS = ["interaction:respond", "storage:kv", "discord:send_message", "proxy:http"]


def event(user="111", **kwargs):
    return make_event("interaction_create", user_id=user, channel_id="333", **kwargs)


def build(code=CODE):
    return {"game": "mw4", "code": code, "weapon": {"name": "Kastov 762", "prefix": "A01"},
            "attachments": [], "unknowns": ["Unknown test attachment remains in the code"], "notes": [],
            "identity_status": "partial", "snapshot_date": "2026-11-09"}


def buttons(response):
    rows = response.get("components") or []
    return [b for row in rows for b in (row.to_dict() if hasattr(row, "to_dict") else row)["components"]]


class AppFlowTests(unittest.TestCase):
    def setUp(self):
        self.ctx = MockContext(server_id="999", plugin_id="yourbot-cod-hub", capabilities=CAPS,
                               clock=MockClock(start=1000))
        self.catalog = SimpleNamespace(
            resolve_build=Mock(side_effect=lambda code, game="mw4": build(code)),
            search_weapons=Mock(return_value=[{"name": "Kastov 762", "prefix": "A01"}]),
            search_attachments=Mock(return_value=[{"name": "FSS Tac90 Grip", "internal_ref": "rex_grip"}]),
        )
        self.cards = SimpleNamespace(
            build_embed=Mock(side_effect=lambda b: {"title": b.get("title") or b["weapon"]["name"],
                                                   "description": b["code"] + "\n" + "\n".join(b["unknowns"])}),
            weapon_embed=Mock(return_value={"title": "Kastov 762"}),
            attachment_embed=Mock(return_value={"title": "FSS Tac90 Grip"}),
            render_build_png=Mock(return_value=b"\x89PNG\r\n\x1a\nTEST"),
            meta_embed=Mock(side_effect=lambda p: {"title": "MetaRadar", "description": p.get("warning") or "Ready"}),
        )
        for target, value in [("_catalog", self.catalog), ("_cards", self.cards)]:
            patcher = patch.object(app, target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def preview(self):
        app.handle_build(self.ctx, event(options=[{"name": "code", "value": CODE}]))
        response = self.ctx.interaction.followups[-1]
        cid = next(b["custom_id"] for b in buttons(response) if b["label"] == "Save")
        return cid

    def test_build_acknowledges_before_resolution_and_preserves_unknowns(self):
        def resolve(code, game):
            self.assertEqual(self.ctx.interaction.defers, [{"ephemeral": True}])
            return build(code)
        self.catalog.resolve_build.side_effect = resolve
        self.preview()
        result = self.ctx.interaction.followups[-1]
        self.assertIn("Unknown test attachment", result["embeds"][0]["description"])
        self.assertEqual(result["allowed_mentions"], {"parse": []})
        self.assertIn("current channel", result["content"])

    def test_public_save_makes_own_copy_and_other_controls_cannot_mutate_owner(self):
        save_id = self.preview()
        actor = "222"
        app.handle_component(self.ctx, event(actor, custom_id=save_id))
        identifier = save_id.rsplit(":", 1)[-1]
        store = BuildStore(self.ctx.kv, self.ctx.server_id)
        self.assertIsNotNone(store.get("s", actor, identifier))
        self.assertIsNone(store.get("s", "111", identifier))
        for action in ("share", "png", "code"):
            app.handle_component(self.ctx, event(actor, custom_id=save_id.replace("ch:save:", "ch:" + action + ":")))
            self.assertIn("belongs", self.ctx.interaction.followups[-1]["content"])
        self.assertEqual(self.ctx.messages_sent, [])
        app.handle_component(self.ctx, event(custom_id=save_id))
        app.handle_component(self.ctx, event(actor, custom_id=f"ch:delete:s:111:{identifier}"))
        self.assertIsNotNone(store.get("s", "111", identifier))

    def test_saved_record_survives_preview_expiration_and_restart_context(self):
        cid = self.preview()
        app.handle_component(self.ctx, event(custom_id=cid))
        identifier = cid.rsplit(":", 1)[-1]
        self.ctx.clock.advance(PREVIEW_TTL + 1)
        store = BuildStore(self.ctx.kv, self.ctx.server_id)
        self.assertIsNone(store.get("p", "111", identifier))
        self.assertIsNotNone(store.get("s", "111", identifier))
        fresh = MockContext(server_id="999", plugin_id="yourbot-cod-hub", capabilities=CAPS)
        fresh.kv = self.ctx.kv
        app.handle_saved(fresh, event(options={"action": "show", "id": identifier}))
        self.assertEqual(fresh.interaction.defers, [{"ephemeral": True}])
        self.assertIn(CODE, fresh.interaction.followups[-1]["embeds"][0]["description"])

    def test_png_is_public_only_after_owner_click_and_private_ack(self):
        cid = self.preview().replace("ch:save:", "ch:png:")
        def render(value):
            self.assertTrue(self.ctx.interaction.defers[-1]["ephemeral"])
            return b"\x89PNG\r\n\x1a\nTEST"
        self.cards.render_build_png.side_effect = render
        app.handle_component(self.ctx, event(custom_id=cid))
        self.assertEqual(len(self.ctx.messages_sent), 1)
        message = self.ctx.messages_sent[0]
        self.assertEqual(message["channel_id"], "333")
        self.assertEqual(message["allowed_mentions"], {"parse": []})
        self.assertTrue(base64.b64decode(message["files"][0]["data_b64"]).startswith(b"\x89PNG"))
        self.assertTrue(self.ctx.interaction.followups[-1]["ephemeral"])

    def test_wrong_title_and_validation_errors_do_not_write_state(self):
        app.handle_build(self.ctx, event(options={"code": CODE, "game": "bo7"}))
        self.assertIn("MW4", self.ctx.interaction.followups[-1]["content"])
        self.catalog.resolve_build.assert_not_called()
        self.assertEqual(self.ctx.kv_writes, [])
        self.catalog.resolve_build.side_effect = ValueError("Unsupported code version.")
        app.handle_build(self.ctx, event(options={"code": CODE}))
        self.assertEqual(self.ctx.interaction.followups[-1]["content"], "Unsupported code version.")
        self.assertEqual(self.ctx.kv_writes, [])

    def test_saved_list_and_deletion_only_use_current_user(self):
        cid = self.preview()
        app.handle_component(self.ctx, event(custom_id=cid))
        identifier = cid.rsplit(":", 1)[-1]
        app.handle_saved(self.ctx, event("222", options={"action": "delete", "id": identifier}))
        self.assertIn("wasn't found", self.ctx.interaction.followups[-1]["content"])
        app.handle_saved(self.ctx, event(options={"action": "list"}))
        self.assertIn(identifier, self.ctx.interaction.followups[-1]["embeds"][0]["description"])
        app.handle_saved(self.ctx, event(options={"action": "delete", "id": identifier}))
        self.assertIsNone(BuildStore(self.ctx.kv, "999").get("s", "111", identifier))

    def test_saved_list_pagination_is_private_and_owner_bound(self):
        store = BuildStore(self.ctx.kv, "999")
        for i in range(21):
            store.save("111", {"game": "mw4", "code": "A01-TEST" + str(i), "title": f"Saved {i}"})
        app.handle_saved(self.ctx, event(options={"action": "list"}))
        first = self.ctx.interaction.followups[-1]
        self.assertEqual(first["embeds"][0]["description"].count("ID:"), 10)
        next_id = buttons(first)[0]["custom_id"]
        app.handle_component(self.ctx, event("222", custom_id=next_id))
        self.assertIn("belongs", self.ctx.interaction.followups[-1]["content"])
        app.handle_component(self.ctx, event(custom_id=next_id))
        second = self.ctx.interaction.followups[-1]
        self.assertTrue(second["ephemeral"])
        self.assertIn("Page 2/3", second["embeds"][0]["footer"]["text"])

    def test_send_permission_failure_does_not_report_success(self):
        cid = self.preview().replace("ch:save:", "ch:png:")
        denied = MockContext(capabilities=["storage:kv", "interaction:respond"])
        denied.kv = self.ctx.kv
        app.handle_component(denied, event(custom_id=cid))
        self.assertEqual(denied.messages_sent, [])
        self.assertIn("couldn't complete", denied.interaction.followups[-1]["content"])
        self.assertNotIn("Posted", denied.interaction.followups[-1]["content"])

    def test_optional_meta_deferred_and_offline_failures_keep_weapon_lookup_working(self):
        from cod_hub import meta
        def fetch(ctx, game):
            self.assertTrue(ctx.interaction.defers)
            return {"available": False, "warning": "MetaRadar unavailable; try later."}
        with patch.object(meta, "get_meta", side_effect=fetch):
            app.handle_meta(self.ctx, event(options={"game": "warzone"}))
        self.assertIn("unavailable", self.ctx.interaction.followups[-1]["embeds"][0]["description"])
        app.handle_weapon(self.ctx, event(options={"query": "A01"}))
        self.assertEqual(self.ctx.interaction.followups[-1]["embeds"][0]["title"], "Kastov 762")
        app.handle_attachment(self.ctx, event(options={"query": "FSS Tac90 Grip", "weapon": "A01"}))
        self.catalog.search_attachments.assert_called_once_with("FSS Tac90 Grip", weapon="A01", limit=10, game="mw4")


class DurableStoreTests(unittest.TestCase):
    def setUp(self):
        self.ctx = MockContext(capabilities=CAPS)
        self.store = BuildStore(self.ctx.kv, "999")

    def test_concurrent_duplicate_saves_are_idempotent(self):
        source = self.store.preview("111", build())
        with ThreadPoolExecutor(max_workers=12) as pool:
            values = list(pool.map(lambda _: self.store.save("111", source), range(36)))
        self.assertEqual(sum(created for _, created in values), 1)
        self.assertEqual(len(self.store.list_saved("111")), 1)

    def test_concurrent_distinct_saves_respect_limit_without_losing_records(self):
        def save(i):
            try:
                source = build("A01-TEST" + str(i))
                return self.store.save("111", {"code": source["code"], "game": "mw4", "title": str(i)})
            except ValueError:
                return None
        with ThreadPoolExecutor(max_workers=12) as pool:
            values = list(pool.map(save, range(65)))
        self.assertEqual(sum(v is not None for v in values), MAX_SAVED)
        self.assertEqual(len(self.store.list_saved("111")), MAX_SAVED)

    def test_preview_space_is_bounded_and_collision_cannot_leak_another_owner(self):
        for i in range(PREVIEW_SLOTS + 120):
            self.store.preview("111", build("A01-TEST" + str(i)))
        self.assertLessEqual(self.ctx.kv.count(prefix="codhub:preview:"), PREVIEW_SLOTS)
        with patch("cod_hub.store.PREVIEW_SLOTS", 1):
            first = self.store.preview("111", build())
            self.store.preview("222", build("A09-43QCD-D4HTW-VI11"))
            self.assertIsNone(self.store.get("p", "111", first["id"]))


class EntryPointTests(unittest.TestCase):
    def test_entrypoint_can_be_imported_without_starting_runner(self):
        path = Path(__file__).resolve().parents[1] / "plugin" / "__main__.py"
        with patch("yourbot_sdk.Plugin.run", side_effect=AssertionError("run during import")):
            value = runpy.run_path(str(path), run_name="cod_hub_import_test")
        self.assertIn("plugin", value)


class RealServiceFlowTests(unittest.TestCase):
    def test_reference_command_defers_privately_and_keeps_revision_credit_in_cached_result(self):
        from cod_hub import reference

        ctx = MockContext(server_id="999", plugin_id="yourbot-cod-hub", capabilities=CAPS)
        data = {"batchcomplete": True, "query": {
            "rightsinfo": {"text": "CC-BY-SA", "url": "https://www.fandom.com/licensing"},
            "pages": [{"pageid": 123, "ns": 0, "title": "Sample map", "index": 1,
                       "fullurl": "https://callofduty.fandom.com/wiki/Sample_map",
                       "revisions": [{"revid": 987, "timestamp": "2026-11-08T19:26:38Z",
                                      "slots": {"main": {"content": "'''Sample''' is a [[Multiplayer|multiplayer]] map."}}}]}]}}
        ctx.http.mock_response(reference.API_URL, body=json.dumps(data))
        request = ctx.http.request

        def fetch(*args, **kwargs):
            self.assertEqual(ctx.interaction.defers[-1], {"ephemeral": True})
            return request(*args, **kwargs)

        with patch.object(ctx.http, "request", side_effect=fetch):
            app.handle_reference(ctx, event(options={"query": "Sample", "category": "maps", "game": "bo7"}))
        self.assertEqual(len(ctx.http.requests), 1)
        result = ctx.interaction.followups[-1]
        rendered = json.dumps(result["embeds"])
        for text in ["Sample is a multiplayer map", "oldid=987", "2026-11-08",
                     "Call of Duty Wiki contributors", "https://www.fandom.com/licensing", "formatting removed"]:
            self.assertIn(text, rendered)
        self.assertTrue(result["ephemeral"])
        self.assertEqual(result["allowed_mentions"], {"parse": []})
        self.assertEqual(ctx.messages_sent, [])
        restarted = MockContext(server_id="999", plugin_id="yourbot-cod-hub", capabilities=CAPS)
        restarted.kv = ctx.kv
        app.handle_reference(restarted, event(options={"query": "sample", "category": "maps", "game": "bo7"}))
        self.assertEqual(restarted.http.requests, [])
        self.assertEqual(restarted.interaction.followups[-1]["embeds"], result["embeds"])

    def test_reference_invalid_inputs_are_private_and_do_not_fetch(self):
        ctx = MockContext(server_id="999", plugin_id="yourbot-cod-hub", capabilities=CAPS)
        for options in [{"query": ""}, {"query": "x" * 121}, {"query": "map", "category": "unsupported"},
                        {"query": "map", "game": "mw3"}]:
            with self.subTest(options=options):
                app.handle_reference(ctx, event(options=options))
                self.assertTrue(ctx.interaction.defers[-1]["ephemeral"])
                self.assertTrue(ctx.interaction.followups[-1]["ephemeral"])
                self.assertIn("content", ctx.interaction.followups[-1])
        self.assertEqual(ctx.http.requests, [])
        self.assertEqual(ctx.kv_writes, [])

    def test_packaged_catalog_save_reopen_and_png_without_game_files(self):
        from PIL import Image

        ctx = MockContext(server_id="999", plugin_id="yourbot-cod-hub", capabilities=CAPS)
        app.handle_build(ctx, event(options={"code": "A09-43QCD-D4HTW-VI11", "game": "mw4"}))
        card = ctx.interaction.followups[-1]
        self.assertEqual(card["embeds"][0]["title"], "Hyeon Burst")
        cid = next(b["custom_id"] for b in buttons(card) if b["label"] == "Save")
        app.handle_component(ctx, event(custom_id=cid))
        identifier = cid.rsplit(":", 1)[-1]
        app.handle_saved(ctx, event(options={"action": "show", "id": identifier}))
        self.assertEqual(ctx.interaction.followups[-1]["embeds"][0]["title"], "Hyeon Burst")
        app.handle_component(ctx, event(custom_id=cid.replace("ch:save:", "ch:png:")))
        self.assertEqual(len(ctx.messages_sent), 1)
        png = base64.b64decode(ctx.messages_sent[0]["files"][0]["data_b64"])
        with Image.open(BytesIO(png)) as image:
            self.assertEqual(image.format, "PNG")
            self.assertGreaterEqual(image.width, 800)
        self.assertEqual(ctx.log_entries, [])


if __name__ == "__main__":
    unittest.main()
