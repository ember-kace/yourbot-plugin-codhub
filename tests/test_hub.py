"""Real catalog/SDK interaction journeys for the public hub and private cards."""
import unittest
import json
from unittest.mock import patch

from yourbot_sdk.testing import MockContext, make_event

from cod_hub import app, catalog, hub, library_ui
from cod_hub.store import BuildStore

CODE = "A01-42J19-BU11"
CAPS = ["interaction:respond", "storage:kv", "discord:send_message", "proxy:http"]


def event(user="111", **kwargs):
    options = {"interaction_type": 3, "user_id": user, "channel_id": "333"}
    options.update(kwargs)
    return make_event("interaction_create", **options)


def components(payload):
    return [component for row in payload.get("components", [])
            for component in (row.to_dict() if hasattr(row, "to_dict") else row)["components"]]


def button(payload, label):
    return next(component["custom_id"] for component in components(payload) if component.get("label") == label)


def menu(payload, placeholder):
    return next(component for component in components(payload) if component.get("placeholder") == placeholder)


class HubJourneys(unittest.TestCase):
    def setUp(self):
        self.ctx = MockContext(server_id="999", plugin_id="rmg84ete7r8b", capabilities=CAPS)

    def test_home_import_button_opens_code_box_and_submits_without_slash_command(self):
        hub.handle_home(self.ctx, event(interaction_type=2))
        home = self.ctx.interaction.followups[-1]
        self.assertEqual(len(home["components"]), 2)
        import_button = next(item for item in components(home) if item.get("label") == "Import code")
        self.assertEqual(import_button["style"], 1)
        before_defers = len(self.ctx.interaction.defers)
        hub.handle_component(self.ctx, event(custom_id=import_button["custom_id"]))
        self.assertEqual(len(self.ctx.interaction.defers), before_defers)
        modal = self.ctx.interaction.modals_sent[-1]
        self.assertEqual(modal["title"], "Import MW4 build code")
        self.assertEqual(modal["custom_id"], hub.IMPORT_MODAL)
        fields = [field.to_dict() for field in modal["fields"]]
        self.assertEqual(fields[0]["custom_id"], "code")
        self.assertEqual(fields[0]["label"], "Paste build code")
        self.assertTrue(fields[0]["required"])
        self.assertFalse(fields[1]["required"])
        self.assertEqual(self.ctx.kv_writes, [])
        hub.handle_import(self.ctx, event(interaction_type=5, custom_id=modal["custom_id"], modal_values={"code": CODE}))
        preview = self.ctx.interaction.followups[-1]
        self.assertEqual(preview["embeds"][0]["title"], "Kastov 762")
        self.assertIn(CODE, str(preview["embeds"]))
        self.assertNotIn("/codbuild", str(preview))
        self.assertTrue(preview["ephemeral"])
        self.assertEqual(self.ctx.messages_sent, [])

    def test_invalid_import_keeps_retry_code_box_and_home_available(self):
        hub.handle_import(self.ctx, event(interaction_type=5, modal_values={"code": "not-a-code"}))
        error = self.ctx.interaction.followups[-1]
        self.assertTrue(error["ephemeral"])
        self.assertEqual(button(error, "Try another code"), "chh:import")
        self.assertEqual(button(error, "Home"), "chh:private")
        self.assertEqual(self.ctx.kv_writes, [])
        hub.handle_component(self.ctx, event(custom_id=button(error, "Try another code")))
        self.assertEqual(self.ctx.interaction.modals_sent[-1]["custom_id"], hub.IMPORT_MODAL)
        self.assertEqual(self.ctx.messages_sent, [])

    def test_public_home_has_balanced_stable_routes_without_personal_state(self):
        with patch.object(BuildStore, "list_saved", side_effect=AssertionError("Public home must not read a personal library")):
            hub.handle_home(self.ctx, event(interaction_type=2))
        home = self.ctx.interaction.followups[-1]
        rows = [row.to_dict()["components"] for row in home["components"]]
        self.assertEqual([[item["label"] for item in row] for row in rows], [
            ["Import code", "My builds", "Compare"], ["Weapons", "Meta builds", "Game guide"]])
        self.assertEqual([[item["custom_id"] for item in row] for row in rows], [
            ["chh:import", "chh:library", "chc:open"], ["chh:explore", "chh:meta", "chh:reference"]])
        self.assertEqual([item["label"] for row in rows for item in row if item["style"] == 1], ["Import code"])
        self.assertFalse(home["ephemeral"])
        self.assertEqual(self.ctx.kv_writes, [])
        self.assertEqual(self.ctx.http.requests, [])
        self.assertEqual(self.ctx.messages_sent, [])

    def test_home_meta_chooser_and_reference_button_work_without_provider_io(self):
        home = {"components": hub.home_controls()}
        self.assertEqual(button(home, "Game guide"), "chh:reference")
        hub.handle_component(self.ctx, event(custom_id=button(home, "Meta builds")))
        choice = self.ctx.interaction.responses[-1]
        self.assertTrue(choice["ephemeral"])
        self.assertEqual(choice["embeds"][0]["title"], "Meta builds")
        selected = menu(choice, "Choose a mode or game")
        self.assertEqual({item["value"] for item in selected["options"]},
                         {"mode-multiplayer", "mode-dmz", "mode-warzone", "meta-bo7"})
        self.assertEqual(self.ctx.interaction.defers, [])
        self.assertEqual(self.ctx.http.requests, [])
        self.assertEqual(self.ctx.kv_writes, [])
        hub.handle_component(self.ctx, event(custom_id=button(home, "Game guide")))
        self.assertEqual(self.ctx.interaction.modals_sent[-1]["custom_id"], hub.REFERENCE_MODAL)

    def test_public_launcher_creates_separate_private_browser_without_kv(self):
        hub.handle_home(self.ctx, event(interaction_type=2))
        home = self.ctx.interaction.followups[-1]
        self.assertFalse(home["ephemeral"])
        self.assertEqual(home["embeds"][0]["title"], "COD Hub")
        hub.handle_component(self.ctx, event(custom_id=button(home, "Weapons")))
        first = self.ctx.interaction.responses[-1]
        self.assertTrue(first["ephemeral"])
        self.assertFalse(first["update_message"])
        hub.handle_component(self.ctx, event(custom_id=button(first, "Next")))
        second = self.ctx.interaction.responses[-1]
        self.assertTrue(second["update_message"])
        self.assertIn("Page 2/", second["embeds"][0]["footer"]["text"])
        self.assertEqual(self.ctx.kv_writes, [])
        self.assertEqual(self.ctx.messages_sent, [])

    def test_class_weapon_slot_attachment_and_back_are_all_clickable(self):
        hub.handle_component(self.ctx, event(custom_id="chh:explore"))
        browser = self.ctx.interaction.responses[-1]
        hub.handle_component(self.ctx, event(custom_id=menu(browser, "Filter by class")["custom_id"], values=["A"]))
        browser = self.ctx.interaction.responses[-1]
        selector = menu(browser, "Choose a weapon")
        self.assertIn("A01", [o["value"] for o in selector["options"]])
        hub.handle_component(self.ctx, event(custom_id=selector["custom_id"], values=["A01"]))
        weapon = self.ctx.interaction.responses[-1]
        self.assertEqual(weapon["embeds"][0]["title"], "Kastov 762")
        hub.handle_component(self.ctx, event(custom_id=button(weapon, "Explore attachments")))
        attachments = self.ctx.interaction.responses[-1]
        hub.handle_component(self.ctx, event(custom_id=menu(attachments, "Filter by attachment slot")["custom_id"], values=["muzzle"]))
        filtered = self.ctx.interaction.responses[-1]
        selector = menu(filtered, "Choose an attachment")
        chosen = selector["options"][0]
        hub.handle_component(self.ctx, event(custom_id=selector["custom_id"], values=[chosen["value"]]))
        detail = self.ctx.interaction.responses[-1]
        self.assertEqual(detail["embeds"][0]["title"], chosen["label"])
        hub.handle_component(self.ctx, event(custom_id=button(detail, "Back to attachments")))
        selected_slot = menu(self.ctx.interaction.responses[-1], "Filter by attachment slot")
        self.assertEqual([o["value"] for o in selected_slot["options"] if o.get("default")], ["muzzle"])
        self.assertEqual(self.ctx.interaction.defers, [])

    def test_search_form_is_first_response_and_no_results_remains_navigable(self):
        hub.handle_component(self.ctx, event(custom_id="chh:search"))
        self.assertEqual(self.ctx.interaction.defers, [])
        self.assertEqual(self.ctx.interaction.responses, [])
        self.assertEqual(self.ctx.interaction.modals_sent[-1]["custom_id"], hub.SEARCH_MODAL)
        hub.handle_search(self.ctx, event(interaction_type=5, modal_values={"query": "no match zzz"}))
        result = self.ctx.interaction.responses[-1]
        self.assertTrue(result["ephemeral"])
        self.assertFalse(result["update_message"])
        self.assertFalse(any(c.get("placeholder") == "Choose a weapon" for c in components(result)))
        self.assertTrue(button(result, "Search"))
        self.assertTrue(button(result, "Home"))

    def test_import_save_share_and_someone_else_save_use_own_library(self):
        hub.handle_component(self.ctx, event(custom_id="chh:import"))
        self.assertEqual(self.ctx.interaction.defers, [])
        self.assertEqual(self.ctx.kv_writes, [])
        hub.handle_import(self.ctx, event(interaction_type=5, modal_values={"code": CODE, "title": "My ranked build"}))
        preview = self.ctx.interaction.followups[-1]
        self.assertTrue(preview["ephemeral"])
        self.assertEqual(self.ctx.messages_sent, [])
        app.handle_component(self.ctx, event(custom_id=button(preview, "Save")))
        saved = self.ctx.interaction.followups[-1]
        self.assertTrue(button(saved, "Rename").startswith("chl:rename:111:"))
        self.assertTrue(button(saved, "Delete").startswith("chl:ask:111:"))
        app.handle_component(self.ctx, event(custom_id=button(saved, "Post to channel")))
        published = self.ctx.messages_sent[-1]
        self.assertEqual(published["channel_id"], "333")
        self.assertEqual(published["allowed_mentions"], {"parse": []})
        self.assertTrue(button(published, "Explore weapon").startswith("chh:openweapon:"))
        app.handle_component(self.ctx, event("222", custom_id=button(published, "Save")))
        store = BuildStore(self.ctx.kv, "999")
        self.assertEqual(len(store.list_saved("111")), 1)
        self.assertEqual(len(store.list_saved("222")), 1)
        self.assertEqual(store.list_saved("222")[0]["title"], "My ranked build")

    def test_private_views_and_tampered_selection_reject_other_user(self):
        hub.handle_component(self.ctx, event(custom_id="chh:explore"))
        browser = self.ctx.interaction.responses[-1]
        private_next = button(browser, "Next")
        hub.handle_component(self.ctx, event("222", custom_id=private_next))
        denial = self.ctx.interaction.responses[-1]
        self.assertIn("another person", denial["content"])
        self.assertFalse(denial["update_message"])
        selector = menu(browser, "Choose a weapon")
        hub.handle_component(self.ctx, event(custom_id=selector["custom_id"], values=["P01"]))
        self.assertIn("current page", self.ctx.interaction.responses[-1]["content"])
        self.assertEqual(self.ctx.kv_writes, [])

    def test_component_and_form_payload_limits_are_checked_server_side(self):
        for raw in ("chh:w:111:all:0:_", "chh:w:111:all:1:!!!!", "chh:bad:111", "chh:"+"x"*101):
            hub.handle_component(self.ctx, event(custom_id=raw))
            self.assertTrue(self.ctx.interaction.responses[-1]["ephemeral"])
        for query in ("a"*41, None, ""):
            hub.handle_search(self.ctx, event(interaction_type=5, modal_values={"query": query}))
            self.assertIn("content", self.ctx.interaction.responses[-1])
        self.assertLessEqual(len(hub._id("p", "9"*22, "melee", 999, hub._pack("a"*40))), 100)
        before = len(self.ctx.interaction.defers)
        hub.handle_import(self.ctx, event(interaction_type=5, modal_values={"code": CODE, "title": "a"*81}))
        self.assertEqual(len(self.ctx.interaction.defers), before+1)
        self.assertIn("80", self.ctx.interaction.followups[-1]["content"])

    def test_base_build_preview_is_private_and_named_only(self):
        hub.handle_component(self.ctx, event(custom_id="chh:b:111:A01"))
        preview = self.ctx.interaction.followups[-1]
        self.assertTrue(preview["ephemeral"])
        self.assertEqual(preview["embeds"][0]["title"], "Kastov 762")
        self.assertEqual(self.ctx.messages_sent, [])
        self.assertIn("Base weapon", str(preview["embeds"]))

    def test_reference_and_meta_branches_defer_privately_before_provider(self):
        hub.handle_component(self.ctx, event(custom_id="chh:more", values=["references"]))
        self.assertEqual(self.ctx.interaction.defers, [])
        self.assertEqual(self.ctx.interaction.modals_sent[-1]["custom_id"], hub.REFERENCE_MODAL)
        def unavailable(*args, **kwargs):
            self.assertTrue(self.ctx.interaction.defers[-1]["ephemeral"])
            raise ValueError("Provider temporarily unavailable")
        with patch("cod_hub.meta.get_meta", side_effect=unavailable):
            hub.handle_component(self.ctx, event(custom_id="chh:more", values=["meta-mw4"]))
        self.assertTrue(self.ctx.interaction.followups[-1]["ephemeral"])
        self.assertEqual(self.ctx.messages_sent, [])

    def test_weapon_art_survives_import_and_public_share_without_proxy_fetch(self):
        hub.handle_import(self.ctx, event(interaction_type=5, modal_values={"code": CODE, "title": "My setup"}))
        private = self.ctx.interaction.followups[-1]
        illustration = private["embeds"][0]
        self.assertEqual(illustration["image"]["url"], "https://metaradar.gg/icons/mw4--kastov-762.webp")
        self.assertIn("Base weapon image", illustration["description"])
        self.assertIn("Data by MetaRadar", illustration["description"])
        self.assertIn("PNG exports are text-only", private["content"])
        app.handle_component(self.ctx, event(custom_id=button(private, "Post to channel")))
        public = self.ctx.messages_sent[-1]["embeds"][0]
        self.assertEqual(public["image"], illustration["image"])
        self.assertEqual(public["description"], illustration["description"])
        self.assertEqual(self.ctx.http.requests, [])

    def test_art_coverage_and_unavailable_images_preserve_working_text_cards(self):
        from cod_hub import artwork, cards
        weapons = catalog.browse_weapons(page_size=25)["items"]
        weapons += catalog.browse_weapons(page=2, page_size=25)["items"]
        self.assertEqual(len(weapons), 35)
        self.assertEqual(sum(artwork.get_weapon_art(w) is not None for w in weapons), 27)
        for weapon in weapons:
            embed = cards.weapon_embed(weapon)
            self.assertEqual(embed["title"], weapon["name"])
            self.assertEqual("image" in embed, artwork.get_weapon_art(weapon) is not None)
        item = catalog.get_attachment("A01", "muzzle:3")
        self.assertNotIn("image", cards.attachment_embed(item))

    def test_mode_and_type_meta_are_reachable_from_slash_and_hub(self):
        def feed(slug, name, kind):
            page = f"https://metaradar.gg/{slug}"
            return {"game": {"slug": slug, "name": slug, "url": page+"/meta"},
                    "attribution": {"text": "Data by MetaRadar", "url": page+"/meta"},
                    "updatedAt": "2026-11-09T15:00:00Z", "weapons": [{"rank": 1, "slug": "sample",
                    "name": name, "class": kind, "url": page+"/weapons/sample", "icons": [],
                    "build": {"attachments": [], "shareCode": None}}]}
        self.ctx.http.mock_response("https://metaradar.gg/api/v1/meta/modernwarfare4", body=json.dumps(feed("modernwarfare4", "M4", "AR")))
        self.ctx.http.mock_response("https://metaradar.gg/api/v1/meta/warzone", body=json.dumps(feed("warzone", "VEL 46", "SMG")))
        app.handle_meta(self.ctx, event(interaction_type=2, options={"mode": "multiplayer", "weapon_type": "ar"}))
        first = self.ctx.interaction.followups[-1]
        self.assertTrue(first["ephemeral"])
        self.assertIn("Assault rifles", first["embeds"][0]["title"])
        hub.handle_component(self.ctx, event(custom_id="chh:more", values=["mode-warzone"]))
        self.assertIn("Warzone", self.ctx.interaction.followups[-1]["embeds"][0]["title"])
        before = len(self.ctx.http.requests)
        hub.handle_component(self.ctx, event(custom_id="chh:more", values=["mode-dmz"]))
        dmz = self.ctx.interaction.followups[-1]
        self.assertEqual(len(self.ctx.http.requests), before)
        self.assertIn("DMZ", dmz["embeds"][0]["title"])
        self.assertNotIn("M4", str(dmz["embeds"]))
        self.assertTrue(any(c.get("url") == "https://dmzradar.com/meta.html" for c in components(dmz)))


if __name__ == "__main__":
    unittest.main()
