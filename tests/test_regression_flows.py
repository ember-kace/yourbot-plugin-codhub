"""Cross-entry-point and live-refresh regressions, using actual SDK mocks."""
from copy import deepcopy
import json
from pathlib import Path
import re
import unittest
from urllib.parse import unquote
from unittest.mock import patch

from yourbot_sdk import Plugin
from yourbot_sdk.testing import MockClock, MockContext, make_event

from cod_hub import app, catalog, hub, library_ui, meta, meta_browser
from cod_hub.store import BuildStore
from test_meta_browser import feed, MP_URL
from test_reference import wiki_response


CAPS = ["interaction:respond", "storage:kv", "discord:send_message", "proxy:http"]
CODE = "A01-42J19-BU11"
UNTRANSLATED_CODE = "A01-UCS11"


def event(user="111", **kwargs):
    return make_event("interaction_create", interaction_type=3, user_id=user, channel_id="333", **kwargs)


def components(payload):
    return [item for row in payload.get("components", [])
            for item in (row.to_dict() if hasattr(row, "to_dict") else row)["components"]]


def build_menu(payload):
    return next(item for item in components(payload) if item.get("placeholder") == "Choose a meta build")


class RefreshedMetaChoiceTests(unittest.TestCase):
    def setUp(self):
        self.clock = MockClock(start=1_000_000)
        self.ctx = MockContext(server_id="999", plugin_id="rmg84ete7r8b", capabilities=CAPS, clock=self.clock)
        self.data = feed()
        self.ctx.http.mock_response(MP_URL, body=json.dumps(self.data))
        clock_patch = patch.object(meta.time, "time", side_effect=self.clock.now)
        clock_patch.start()
        self.addCleanup(clock_patch.stop)

    def open_menu(self):
        meta_browser.handle_open(self.ctx, event())
        return build_menu(self.ctx.interaction.followups[-1])

    def refresh_provider(self, data):
        self.clock.advance(3600)
        self.ctx.http.mock_response(MP_URL, body=json.dumps(data))

    def choose(self, menu, index=0):
        meta_browser.handle_component(self.ctx, event(custom_id=menu["custom_id"], values=[menu["options"][index]["value"]]))
        return self.ctx.interaction.followups[-1]

    def assert_expired(self, result):
        self.assertIn("Recommendations changed", result["content"])
        self.assertFalse(result.get("embeds"))
        self.assertTrue(result["ephemeral"])
        self.assertEqual(result["allowed_mentions"], {"parse": []})
        self.assertEqual(self.ctx.messages_sent, [])

    def test_rank_reorder_cannot_open_the_new_occupant_of_an_old_selection(self):
        original = self.open_menu()
        changed = deepcopy(self.data)
        changed["weapons"][0]["rank"], changed["weapons"][1]["rank"] = 2, 1
        self.refresh_provider(changed)
        self.assert_expired(self.choose(original))
        self.assertEqual(len(self.ctx.http.requests), 2)
        # Reopen the same page using an existing navigation ID. Fresh controls
        # select the correct source row and do not cause another upstream call.
        meta_browser.handle_component(self.ctx, event(custom_id=original["custom_id"].replace(":pick:", ":page:")))
        fresh = build_menu(self.ctx.interaction.followups[-1])
        self.assertEqual(fresh["options"][0]["label"], "Weapon 2")
        selected = self.choose(fresh)
        self.assertEqual(selected["embeds"][0]["title"], "Weapon 2")
        self.assertTrue(selected["embeds"][0]["url"].endswith("/weapon-2"))
        self.assertEqual(len(self.ctx.http.requests), 2)
        # Selection tokens belong to the UI; never modify normalized source rows.
        cached_rows = self.ctx.kv.get("metaradar:v1:mw4")["snapshot"]["weapons"]
        self.assertEqual([row["rank"] for row in cached_rows], list(range(1, 11)))
        self.assertTrue(all("selection_token" not in row for row in cached_rows))

    def test_same_weapon_and_rank_with_changed_attachments_expires_old_choice(self):
        original = self.open_menu()
        changed = deepcopy(self.data)
        changed["weapons"][0]["build"]["attachments"][0]["name"] = "Changed suppressor"
        self.refresh_provider(changed)
        self.assert_expired(self.choose(original))
        fresh = self.open_menu()
        selected = self.choose(fresh)
        self.assertIn("Changed suppressor", str(selected["embeds"][0]))
        self.assertEqual(selected["embeds"][0]["title"], "Weapon 1")
        self.assertEqual(len(self.ctx.http.requests), 2)

    def test_same_weapon_and_rank_with_changed_source_code_expires_old_choice(self):
        original = self.open_menu()
        changed = deepcopy(self.data)
        changed["weapons"][0]["build"]["shareCode"] = CODE
        self.refresh_provider(changed)
        self.assert_expired(self.choose(original))

    def test_unchanged_hourly_refresh_keeps_old_choice_accurate(self):
        original = self.open_menu()
        changed = deepcopy(self.data)
        changed["updatedAt"] = "2026-11-09T16:00:00Z"
        self.refresh_provider(changed)
        selected = self.choose(original)
        self.assertEqual(selected["embeds"][0]["title"], original["options"][0]["label"])
        self.assertIn("2026-11-09T16:00:00Z", selected["embeds"][0]["description"])
        self.assertEqual(len(self.ctx.http.requests), 2)

    def test_same_page_refresh_reuses_hourly_cache_and_has_working_new_choices(self):
        self.open_menu()
        original = self.ctx.interaction.followups[-1]
        refresh = next(item for item in components(original) if item.get("label") == "Refresh")
        meta_browser.handle_component(self.ctx, event(custom_id=refresh["custom_id"]))
        fresh = build_menu(self.ctx.interaction.followups[-1])
        self.assertEqual(self.choose(fresh)["embeds"][0]["title"], "Weapon 1")
        self.assertEqual(len(self.ctx.http.requests), 1)
        self.assertTrue(self.ctx.interaction.followups[-1]["ephemeral"])


class MetaProviderBoundsTests(unittest.TestCase):
    def view(self, *, weapon_url_length=750, credit_character="a"):
        data = feed()
        data["weapons"] = data["weapons"][:5]
        prefix = "https://metaradar.gg/credit-"
        data["attribution"] = {"text": "M" * 200, "url": prefix + credit_character * (1200 - len(prefix))}
        for row in data["weapons"]:
            prefix = "https://metaradar.gg/weapon-" + str(row["rank"]) + "/"
            row.update(name="N" * 180, tier="T" * 80,
                       url=prefix + "x" * (weapon_url_length - len(prefix)))
            row["build"].update(label="L" * 160, shareCode=CODE,
                                 attachments=[{"slot": "S" * 80, "name": "A" * 200} for _ in range(20)])
        ctx = MockContext(server_id="999", plugin_id="rmg84ete7r8b", capabilities=CAPS)
        ctx.http.mock_response(MP_URL, body=json.dumps(data))
        view = meta_browser.get_mode_meta(ctx, "multiplayer", now=1_000_000)
        self.assertTrue(view["available"], view.get("error"))
        self.assertEqual(len(view["weapons"]), 5)
        return ctx, view

    def assert_contract(self, embed):
        self.assertLessEqual(len(embed["description"]), 4096)
        total = len(embed["title"]) + len(embed["description"]) + len(embed.get("footer", {}).get("text", ""))
        for field in embed.get("fields", []):
            self.assertLessEqual(len(field["name"]), 256)
            self.assertLessEqual(len(field["value"]), 1024)
            total += len(field["name"]) + len(field["value"])
        self.assertLessEqual(total, 6000)

    def test_long_valid_browser_rows_keep_complete_links_or_explicit_omission(self):
        _, view = self.view()
        embed = meta_browser.browser_embed(view)
        self.assert_contract(embed)
        self.assertIn("omitted", embed["description"])
        self.assertIn(view["attribution"]["url"], embed["description"])
        complete = {view["attribution"]["url"], *(row["url"] for row in view["weapons"])}
        for destination in re.findall(r"\]\(([^)]+)\)", json.dumps(embed)):
            self.assertIn(unquote(destination), complete)

    def test_overlong_row_source_link_is_available_intact_from_selected_build(self):
        ctx, view = self.view(weapon_url_length=1200)
        browser = meta_browser.browser_embed(view)
        self.assert_contract(browser)
        self.assertIn("shortened", browser["description"])
        with patch.object(meta.time, "time", return_value=1_000_000):
            menu = build_menu({"components": meta_browser.browser_controls("111", view)})
            meta_browser.handle_component(ctx, event(custom_id=menu["custom_id"], values=[menu["options"][0]["value"]]))
        selected = ctx.interaction.followups[-1]
        detail = selected["embeds"][0]
        self.assert_contract(detail)
        self.assertEqual(detail["url"], view["weapons"][0]["url"])
        self.assertIn("shortened", detail["description"])
        self.assertEqual(next(c for c in components(selected) if c.get("label") == "Open provider")["url"], detail["url"])
        self.assertEqual(len(ctx.http.requests), 1)

    def test_expanded_credit_and_maximum_build_details_fit_without_cut_source_or_code(self):
        _, view = self.view(weapon_url_length=1200, credit_character="(")
        for embed in (meta_browser.browser_embed(view), meta_browser.detail_embed(view, view["weapons"][0])):
            self.assert_contract(embed)
            credit = re.findall(r"\]\(([^)]+)\)", embed["description"])[0]
            self.assertEqual(unquote(credit), view["attribution"]["url"])
            self.assertIn("omitted", embed["description"])
        detail = meta_browser.detail_embed(view, view["weapons"][0])
        self.assertIn(CODE, next(field["value"] for field in detail["fields"] if field["name"] == "In-game code (source)"))
        self.assertEqual(detail["url"], view["weapons"][0]["url"])

    def test_unicode_attribution_url_remains_whole_and_within_embed_budgets(self):
        _, view = self.view(weapon_url_length=1200, credit_character="é")
        for embed in (meta_browser.browser_embed(view), meta_browser.detail_embed(view, view["weapons"][0])):
            self.assert_contract(embed)
            self.assertIn(view["attribution"]["url"], embed["description"])

    def test_refresh_controls_fit_middle_pages_and_dmz_without_extra_requests(self):
        ctx, view = self.view()
        for changed in (dict(view, page=2, pages=3), meta_browser.get_mode_meta(ctx, "dmz")):
            controls = meta_browser.browser_controls("9" * 22, changed)
            self.assertLessEqual(len(controls), 5)
            for row in controls:
                self.assertLessEqual(len(row.to_dict()["components"]), 5)
            refresh = next(item for item in components({"components": controls}) if item.get("label") == "Refresh")
            self.assertTrue(refresh["custom_id"].endswith(":" + str(changed["page"])))
        self.assertEqual(len(ctx.http.requests), 1)


class EntryPointNamePolicyTests(unittest.TestCase):
    def setUp(self):
        # The policy fixture stays untranslated even after production English
        # coverage is completed. Keep real codec/ID resolution for all fields.
        resolve = catalog.resolve_build

        def fixture(code, game="mw4"):
            build = resolve(code, game=game)
            if build["code"] == UNTRANSLATED_CODE:
                build["label_status"] = "fallback"
                build["attachments"][0].update(quality="internal", name="Untranslated test fixture")
            return build

        patcher = patch.object(catalog, "resolve_build", side_effect=fixture)
        patcher.start()
        self.addCleanup(patcher.stop)

    def context(self):
        return MockContext(server_id="999", plugin_id="rmg84ete7r8b", capabilities=CAPS)

    def test_slash_and_modal_reject_untranslated_build_before_any_preview_write(self):
        self.assertEqual(catalog.resolve_build(UNTRANSLATED_CODE)["label_status"], "fallback")
        for handler, values in [(app.handle_build, {"options": {"code": UNTRANSLATED_CODE}}),
                                (hub.handle_import, {"modal_values": {"code": UNTRANSLATED_CODE, "title": ""}})]:
            with self.subTest(handler=handler.__name__):
                ctx = self.context()
                handler(ctx, event(**values))
                self.assertEqual(ctx.interaction.defers, [{"ephemeral": True}])
                result = ctx.interaction.followups[-1]
                self.assertIn("without verified English names", result["content"])
                self.assertFalse(result.get("embeds"))
                self.assertEqual(ctx.kv_writes, [])
                self.assertEqual(ctx.messages_sent, [])

    def test_old_untranslated_records_cannot_save_share_render_or_reopen_but_keep_raw_code_and_delete(self):
        ctx = self.context()
        store = BuildStore(ctx.kv, ctx.server_id)
        preview = store.preview("111", catalog.resolve_build(UNTRANSLATED_CODE))
        saved, _ = store.save("111", preview)
        writes = len(ctx.kv_writes)
        for action in ("save", "share", "png"):
            with self.subTest(action=action):
                app.handle_component(ctx, event(custom_id=f"ch:{action}:p:111:{preview['id']}"))
                self.assertIn("without verified English names", ctx.interaction.followups[-1]["content"])
                self.assertEqual(len(ctx.kv_writes), writes)
                self.assertEqual(ctx.messages_sent, [])
        app.handle_saved(ctx, event(options={"action": "show", "id": saved["id"]}))
        self.assertIn("without verified English names", ctx.interaction.followups[-1]["content"])
        self.assertIsNotNone(store.get("s", "111", saved["id"]))
        app.handle_component(ctx, event(custom_id=f"ch:code:s:111:{saved['id']}"))
        self.assertIn(UNTRANSLATED_CODE, ctx.interaction.followups[-1]["content"])
        app.handle_saved(ctx, event(options={"action": "delete", "id": saved["id"]}))
        self.assertIsNone(store.get("s", "111", saved["id"]))
        self.assertEqual(ctx.messages_sent, [])

    def test_legacy_saved_list_neutralizes_title_markdown_like_gui_library(self):
        ctx = self.context()
        store = BuildStore(ctx.kv, ctx.server_id)
        title = "[Official build](https://example.invalid) **spoof**"
        record = store.preview("111", catalog.resolve_build(CODE), title)
        store.save("111", record)
        app.handle_saved(ctx, event(options={"action": "list"}))
        legacy = ctx.interaction.followups[-1]
        library_ui.handle_open(ctx, event())
        gui = ctx.interaction.followups[-1]
        for payload in (legacy, gui):
            text = payload["embeds"][0]["description"]
            self.assertNotIn("[Official build](https://example.invalid)", text)
            self.assertIn(r"\[Official build\]\(https://example.invalid\)", text)
            self.assertIn(r"\*\*spoof\*\*", text)
            self.assertTrue(payload["ephemeral"])
            self.assertEqual(payload["allowed_mentions"], {"parse": []})


class RegisteredInteractionTests(unittest.TestCase):
    def test_every_manifest_command_has_one_acknowledging_sdk_route(self):
        from cod_hub import reference

        plugin = Plugin()
        app.register(plugin)
        examples = {
            "codhub": {}, "codbuild": {"code": CODE}, "codweapon": {"query": "A01"},
            "codattachment": {"query": "FSS Tac90 Grip"}, "codsaved": {},
            "codmeta": {"mode": "dmz"}, "codreference": {"query": "Sample map"},
            "codcompare": {"left": "A01", "right": "A05"},
        }
        manifest = json.loads((Path(__file__).resolve().parents[1] / "plugin" / "manifest.json").read_text(encoding="utf8"))
        self.assertEqual(set(examples), {item["name"] for item in manifest["slash_commands"]})
        for name, options in examples.items():
            with self.subTest(command=name):
                ctx = MockContext(server_id="999", plugin_id="rmg84ete7r8b", capabilities=CAPS)
                ctx.http.mock_response(reference.API_URL, body=json.dumps(wiki_response()))
                command = make_event("interaction_create", interaction_type=2, command_name=name,
                                     user_id="111", channel_id="333", options=options)
                for handler in plugin._event_handlers["interaction_create"]:
                    handler(ctx, command)
                acknowledgments = len(ctx.interaction.defers) + len(ctx.interaction.responses) + len(ctx.interaction.modals_sent)
                self.assertEqual(acknowledgments, 1)
                self.assertEqual(ctx.messages_sent, [])
                if name != "codhub":
                    for response in ctx.interaction.responses + ctx.interaction.followups:
                        self.assertTrue(response["ephemeral"])

    def test_fixed_modal_ids_route_once_and_never_hit_component_handlers(self):
        from cod_hub import comparison_ui, reference

        plugin = Plugin()
        app.register(plugin)
        examples = {
            comparison_ui.MODAL: {"left": "A01", "right": "A05"},
            hub.IMPORT_MODAL: {"code": CODE, "title": "My build"},
            hub.SEARCH_MODAL: {"query": "A01"},
            hub.REFERENCE_MODAL: {"query": "Sample map"},
            library_ui.RENAME_MODAL: {"code": CODE, "title": "New title"},
        }
        for custom_id, values in examples.items():
            with self.subTest(custom_id=custom_id):
                ctx = MockContext(server_id="999", plugin_id="rmg84ete7r8b", capabilities=CAPS)
                ctx.http.mock_response(reference.API_URL, body=json.dumps(wiki_response()))
                submitted = make_event("interaction_create", interaction_type=5, custom_id=custom_id,
                                       user_id="111", channel_id="333", modal_values=values)
                for handler in plugin._event_handlers["interaction_create"]:
                    handler(ctx, submitted)
                acknowledgments = len(ctx.interaction.defers) + len(ctx.interaction.responses) + len(ctx.interaction.modals_sent)
                self.assertEqual(acknowledgments, 1)
                self.assertEqual(ctx.messages_sent, [])
                for response in ctx.interaction.responses + ctx.interaction.followups:
                    self.assertTrue(response["ephemeral"])


if __name__ == "__main__":
    unittest.main()
