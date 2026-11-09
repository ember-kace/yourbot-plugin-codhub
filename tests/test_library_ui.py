"""Real SDK interaction tests for private saved-library controls."""
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch

from yourbot_sdk.testing import MockContext, make_event

from cod_hub import library_ui
from cod_hub.catalog import get_catalog, resolve_build
from cod_hub.store import BuildStore, build_id


CODE = "A01-42J19-BU11"
CAPS = ["interaction:respond", "storage:kv"]


def event(owner="111", **kwargs):
    return make_event("interaction_create", user_id=owner, channel_id="333", **kwargs)


def components(response):
    return [item for row in response.get("components") or []
            for item in row.to_dict()["components"]]


class LibraryUiTests(unittest.TestCase):
    def setUp(self):
        self.ctx = MockContext(server_id="999", plugin_id="yourbot-cod-hub", capabilities=CAPS)
        self.store = BuildStore(self.ctx.kv, self.ctx.server_id)

    def seed(self, owner="111", code=CODE, title="Ranked Kastov"):
        build = resolve_build(code)
        build["title"] = title
        return self.store.save(owner, build)[0]

    def fresh(self):
        ctx = MockContext(server_id="999", plugin_id="yourbot-cod-hub", capabilities=CAPS)
        ctx.kv = self.ctx.kv
        return ctx

    def assert_private(self, ctx):
        self.assertEqual(ctx.messages_sent, [])
        for response in ctx.interaction.responses + ctx.interaction.followups:
            self.assertTrue(response["ephemeral"])
            self.assertEqual(response["allowed_mentions"], {"parse": []})

    def test_open_acknowledges_before_kv_and_empty_library_has_home(self):
        original = BuildStore.list_saved

        def checked(store, owner):
            self.assertEqual(self.ctx.interaction.defers, [{"ephemeral": True}])
            return original(store, owner)

        with patch.object(BuildStore, "list_saved", new=checked):
            library_ui.handle_open(self.ctx, event())
        response = self.ctx.interaction.followups[-1]
        self.assertEqual(response["embeds"][0]["title"], "My builds")
        self.assertIn("Your next build", response["embeds"][0]["description"])
        self.assertEqual(components(response)[0]["custom_id"], "chh:private")
        self.assert_private(self.ctx)

    def test_saved_menu_opens_real_build_card_and_never_leaks_another_library(self):
        record = self.seed()
        self.seed("222", title="Other person's build")
        library_ui.handle_open(self.ctx, event())
        response = self.ctx.interaction.followups[-1]
        menu = next(item for item in components(response) if item["type"] == 3)
        self.assertEqual(menu["custom_id"], "chl:open:111")
        self.assertEqual(len(menu["options"]), 1)
        self.assertEqual(menu["options"][0]["value"], record["id"])
        ctx = self.fresh()
        library_ui.handle_component(ctx, event(interaction_type=3, custom_id=menu["custom_id"], values=[record["id"]]))
        self.assertEqual(ctx.interaction.defers, [{"ephemeral": True}])
        opened = ctx.interaction.followups[-1]
        self.assertEqual(opened["embeds"][0]["title"], "Ranked Kastov")
        self.assertTrue(any(field.get("value", "").find(CODE) >= 0 for field in opened["embeds"][0]["fields"]))
        self.assert_private(ctx)

    def test_pagination_is_bounded_and_preserves_all_saved_options(self):
        codec = get_catalog().codec
        for number in range(12):
            indexes = [0] * len(get_catalog().schema.slots)
            indexes[1], indexes[2] = number % 9 + 1, number // 9
            self.seed(code=codec.encode("A01", indexes), title=f"Saved build {number}")
        library_ui.handle_open(self.ctx, event())
        first = self.ctx.interaction.followups[-1]
        first_menu = next(item for item in components(first) if item["type"] == 3)
        self.assertEqual(len(first_menu["options"]), 10)
        next_id = next(item["custom_id"] for item in components(first) if item.get("label") == "Next")
        ctx = self.fresh()
        library_ui.handle_component(ctx, event(interaction_type=3, custom_id=next_id))
        second = ctx.interaction.followups[-1]
        second_menu = next(item for item in components(second) if item["type"] == 3)
        self.assertEqual(len(second_menu["options"]), 2)
        self.assertEqual(len({item["value"] for item in first_menu["options"] + second_menu["options"]}), 12)
        self.assertNotIn("Next", {item.get("label") for item in components(second)})
        self.assert_private(ctx)

    def test_cross_owner_and_malformed_controls_fail_before_record_access(self):
        record = self.seed("222")
        controls = [f"chl:open:222", f"chl:ask:222:{record['id']}", f"chl:delete:222:{record['id']}",
                    "chl:list:222:1", "chl:list:111:0", "chl:open:111:extra", "chl:delete:111:../key"]
        for control in controls:
            ctx = self.fresh()
            with patch.object(BuildStore, "get", side_effect=AssertionError("No record read expected")):
                library_ui.handle_component(ctx, event(interaction_type=3, custom_id=control, values=[record["id"]]))
            self.assertEqual(ctx.interaction.defers, [{"ephemeral": True}])
            self.assertTrue(ctx.interaction.followups)
            self.assert_private(ctx)
        self.assertIsNotNone(self.store.get("s", "222", record["id"]))

    def test_select_requires_one_valid_owned_existing_record(self):
        record = self.seed("222")
        for values in (None, [], ["bad"], [record["id"], record["id"]], record["id"], [record["id"]]):
            ctx = self.fresh()
            library_ui.handle_component(ctx, event(interaction_type=3, custom_id="chl:open:111", values=values))
            self.assertTrue(ctx.interaction.followups[-1]["content"])
            self.assert_private(ctx)

    def test_delete_requires_visible_confirmation_flow_and_does_not_change_shared_preview(self):
        record = self.seed()
        preview = self.store.preview("111", resolve_build(CODE), "Public preview")
        library_ui.handle_component(self.ctx, event(interaction_type=3, custom_id=f"chl:ask:111:{record['id']}"))
        confirmation = self.ctx.interaction.followups[-1]
        self.assertEqual(confirmation["embeds"][0]["title"], "Delete saved build?")
        self.assertEqual(confirmation["embeds"][0]["fields"][0]["value"], "`" + CODE + "`")
        self.assertIsNotNone(self.store.get("s", "111", record["id"]))
        self.assertEqual({item["label"] for item in components(confirmation)}, {"Delete build", "Keep build"})
        ctx = self.fresh()
        delete = next(item["custom_id"] for item in components(confirmation) if item["label"] == "Delete build")
        library_ui.handle_component(ctx, event(interaction_type=3, custom_id=delete))
        self.assertIsNone(self.store.get("s", "111", record["id"]))
        self.assertIsNotNone(self.store.get("p", "111", preview["id"]))
        self.assertIn("Deleted", ctx.interaction.followups[-1]["content"])
        self.assertEqual(ctx.interaction.followups[-1]["embeds"][0]["title"], "My builds")
        self.assert_private(ctx)

    def test_keep_confirmation_returns_to_library_without_deleting(self):
        record = self.seed()
        library_ui.handle_component(self.ctx, event(interaction_type=3, custom_id="chl:list:111:1"))
        self.assertIsNotNone(self.store.get("s", "111", record["id"]))
        self.assertIn("Ranked Kastov", self.ctx.interaction.followups[-1]["embeds"][0]["description"])

    def test_rename_modal_is_first_response_and_uses_no_kv(self):
        with patch.object(BuildStore, "__init__", side_effect=AssertionError("No KV before modal")):
            library_ui.handle_component(self.ctx, event(interaction_type=3, custom_id=f"chl:rename:111:{CODE}"))
        self.assertEqual(self.ctx.interaction.defers, [])
        self.assertEqual(self.ctx.interaction.responses, [])
        self.assertEqual(self.ctx.interaction.followups, [])
        self.assertEqual(len(self.ctx.interaction.modals_sent), 1)
        modal = self.ctx.interaction.modals_sent[0]
        self.assertEqual(modal["custom_id"], library_ui.RENAME_MODAL)
        fields = [field.to_dict() for field in modal["fields"]]
        self.assertEqual(fields[0]["value"], CODE)
        self.assertEqual(fields[1]["max_length"], 80)
        self.assertTrue(fields[1]["required"])

    def test_cross_owner_rename_cannot_open_a_form_or_access_kv(self):
        with patch.object(BuildStore, "__init__", side_effect=AssertionError("No KV expected")):
            library_ui.handle_component(self.ctx, event(interaction_type=3, custom_id=f"chl:rename:222:{CODE}"))
        self.assertEqual(self.ctx.interaction.defers, [])
        self.assertEqual(self.ctx.interaction.modals_sent, [])
        self.assertIn("another person's", self.ctx.interaction.responses[-1]["content"])
        self.assert_private(self.ctx)

    def test_rename_submission_is_persistent_owner_scoped_and_keeps_code_identity(self):
        own = self.seed()
        other = self.seed("222", title="Other build")
        library_ui.handle_rename(self.ctx, event(interaction_type=5, custom_id=library_ui.RENAME_MODAL,
                                                modal_values={"code": CODE.lower(), "title": "  Ranked `Kastov`  "}))
        self.assertEqual(self.ctx.interaction.defers, [{"ephemeral": True}])
        renamed = self.store.get("s", "111", own["id"])
        self.assertEqual(renamed["title"], "Ranked 'Kastov'")
        self.assertEqual(renamed["code"], own["code"])
        self.assertEqual(renamed["created_at"], own["created_at"])
        self.assertEqual(renamed["id"], build_id("mw4", CODE))
        self.assertEqual(self.store.get("s", "222", other["id"])["title"], "Other build")
        self.assertEqual(self.ctx.interaction.followups[-1]["embeds"][0]["title"], "Ranked 'Kastov'")
        self.assert_private(self.ctx)

    def test_rename_cannot_create_a_saved_record_or_accept_oversized_fields(self):
        victim = self.seed("222")
        for values in ({"code": CODE, "title": "My new name"}, {"code": CODE, "title": " "},
                       {"code": CODE, "title": "x" * 81}, {"code": "A01-111" + "x" * 25, "title": "Test"},
                       {"code": CODE, "title": []}, None):
            ctx = self.fresh()
            library_ui.handle_rename(ctx, event(interaction_type=5, custom_id=library_ui.RENAME_MODAL, modal_values=values))
            self.assertEqual(ctx.interaction.defers, [{"ephemeral": True}])
            self.assertTrue(ctx.interaction.followups[-1]["content"])
            self.assertIsNone(self.store.get("s", "111", victim["id"]))
            self.assert_private(ctx)
        self.assertEqual(self.store.get("s", "222", victim["id"])["title"], "Ranked Kastov")

    def test_store_rename_retains_durable_record_under_concurrent_calls(self):
        record = self.seed()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda n: self.store.rename("111", record["id"], f"Build {n}"), range(12)))
        self.assertEqual(len(results), 12)
        current = self.store.get("s", "111", record["id"])
        self.assertEqual(current["id"], record["id"])
        self.assertEqual(current["code"], CODE)
        self.assertIn(current["title"], {f"Build {n}" for n in range(12)})
        self.assertEqual(len(self.store.list_saved("111")), 1)


if __name__ == "__main__":
    unittest.main()
