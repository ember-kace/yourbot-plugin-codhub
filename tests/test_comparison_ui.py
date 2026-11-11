"""Actual SDK journeys, source-scoped graphs and explicit public posting."""
import base64
from copy import deepcopy
from io import BytesIO
import json
import unittest
from unittest.mock import patch

from PIL import Image
from yourbot_sdk import Context
from yourbot_sdk.testing import MockContext, make_event
from cod_hub import app, comparison_ui as ui, hub, telemetry

CAPS = ["interaction:respond", "storage:kv", "discord:send_message", "proxy:http"]
CODE_A = "A01-42J19-BU11"
CODE_B = "A01-A11NP-B11"


def event(user="111", **kwargs):
    values = {"interaction_type": 3, "user_id": user, "channel_id": "333"}
    values.update(kwargs)
    return make_event("interaction_create", **values)


def components(payload):
    return [c for row in payload.get("components", [])
            for c in (row.to_dict() if hasattr(row, "to_dict") else row)["components"]]


def button(payload, label):
    return next(c for c in components(payload) if c.get("label") == label)


def menu(payload, placeholder):
    return next(c for c in components(payload) if c.get("placeholder") == placeholder)


class ComparisonJourneys(unittest.TestCase):
    def setUp(self):
        self.ctx = MockContext(server_id="999", plugin_id="rmg84ete7r8b", capabilities=CAPS)

    def open(self, left="A01", right="A05", view="overview", mode="multiplayer"):
        ui.handle_command(self.ctx, event(interaction_type=2, options={"left": left, "right": right, "view": view, "mode": mode}))
        return self.ctx.interaction.followups[-1]

    def test_invalid_pasted_comparison_keeps_a_gui_recovery_path(self):
        ui.handle_modal(self.ctx, event(interaction_type=5, modal_values={"left": "Kastov 762", "right": ""}))
        setup = self.ctx.interaction.followups[-1]
        self.assertTrue(setup["ephemeral"])
        self.assertEqual(setup["embeds"][0]["title"], "Set up a comparison")
        self.assertIn("**B needs another selection.**", setup["content"])
        self.assertIn("Selection **A** is kept", setup["content"])
        self.assertEqual([field["value"] for field in setup["embeds"][0]["fields"]], ["Kastov 762", "Not selected"])
        self.assertEqual(menu(setup, "Choose weapon for B")["type"], 3)
        self.assertEqual(self.ctx.interaction.responses, [])
        ui.handle_component(self.ctx, event(custom_id=button(setup, "Paste names / codes")["custom_id"]))
        fields = [field.to_dict() for field in self.ctx.interaction.modals_sent[-1]["fields"]]
        self.assertEqual([field.get("value", "") for field in fields], ["Kastov 762", ""])
        self.assertEqual(self.ctx.messages_sent, [])
        self.assertEqual(self.ctx.kv_writes, [])

    def test_invalid_a_retains_valid_build_b_and_owner_bound_recovery(self):
        invalid = "<@everyone>:" + "x" * 240
        ui.handle_modal(self.ctx, event(interaction_type=5, modal_values={"left": invalid, "right": CODE_B}))
        setup = self.ctx.interaction.followups[-1]
        self.assertIn("**A needs another selection.**", setup["content"])
        self.assertIn("Selection **B** is kept", setup["content"])
        self.assertIn(CODE_B, setup["embeds"][0]["fields"][1]["value"])
        self.assertEqual(menu(setup, "Choose weapon for A")["type"], 3)
        retry = button(setup, "Paste names / codes")["custom_id"]
        self.assertLessEqual(len(retry), 100)
        self.assertNotIn(invalid, retry)
        ui.handle_component(self.ctx, event("222", custom_id=retry))
        self.assertIn("another person", self.ctx.interaction.responses[-1]["content"])
        self.assertEqual(self.ctx.interaction.modals_sent, [])
        ui.handle_component(self.ctx, event(custom_id=retry))
        fields = [field.to_dict() for field in self.ctx.interaction.modals_sent[-1]["fields"]]
        self.assertEqual([field.get("value", "") for field in fields], ["", CODE_B])
        self.assertEqual(self.ctx.kv_writes, [])
        self.assertEqual(self.ctx.messages_sent, [])

    def test_two_invalid_modal_sides_identify_both_and_start_with_a(self):
        ui.handle_modal(self.ctx, event(interaction_type=5, modal_values={"left": "not a weapon", "right": ""}))
        setup = self.ctx.interaction.followups[-1]
        self.assertIn("**A needs another selection.**", setup["content"])
        self.assertIn("**B needs another selection.**", setup["content"])
        self.assertEqual([field["value"] for field in setup["embeds"][0]["fields"]], ["Not selected", "Not selected"])
        self.assertEqual(menu(setup, "Choose weapon for A")["type"], 3)
        self.assertEqual(self.ctx.kv_writes, [])
        self.assertEqual(self.ctx.messages_sent, [])

    def test_completed_setup_has_one_primary_compare_action(self):
        embed, rows = ui.setup_view("111", left="wA01", right="wA05")
        controls = components({"components": rows})
        self.assertEqual([item["label"] for item in controls if item.get("style") == 1], ["Compare A / B"])
        self.assertIn("Multiplayer", embed["footer"]["text"])

    def test_home_and_seeded_weapon_setup_acknowledge_without_requiring_a_modal(self):
        self.assertTrue(any(c.get("custom_id") == "chc:open" for c in components({"components": hub.home_controls()})))
        ui.handle_component(self.ctx, event(custom_id="chc:open:wR03"))
        self.assertEqual(self.ctx.interaction.defers, [])
        self.assertEqual(self.ctx.kv_writes, [])
        self.assertEqual(self.ctx.interaction.modals_sent, [])
        setup = self.ctx.interaction.responses[-1]
        self.assertTrue(setup["ephemeral"])
        self.assertEqual(setup["embeds"][0]["fields"][0]["value"], "Astaroth .57")
        self.assertEqual(setup["embeds"][0]["fields"][1]["value"], "Not selected")
        self.assertTrue(button(setup, "Compare A / B")["disabled"])
        self.assertEqual(menu(setup, "Choose weapon for B")["type"], 3)
        ui.handle_component(self.ctx, event(custom_id=button(setup, "Paste names / codes")["custom_id"]))
        modal = self.ctx.interaction.modals_sent[-1]
        self.assertEqual(modal["custom_id"], ui.MODAL)
        self.assertEqual(modal["fields"][0].to_dict()["value"], "Astaroth .57")
        ui.handle_modal(self.ctx, event(interaction_type=5, modal_values={"left": "Astaroth .57", "right": "M4"}))
        result = self.ctx.interaction.followups[-1]
        self.assertTrue(result["ephemeral"])
        self.assertIn("Astaroth .57", result["embeds"][0]["description"])
        self.assertEqual(self.ctx.messages_sent, [])

    def test_asteroth_card_choose_m4_and_compare_works_entirely_through_dropdowns(self):
        ui.handle_component(self.ctx, event(custom_id="chc:open:wR03"))
        setup = self.ctx.interaction.responses[-1]
        ui.handle_component(self.ctx, event(custom_id=menu(setup, "Filter comparison weapons")["custom_id"], values=["A"]))
        setup = self.ctx.interaction.responses[-1]
        weapons = menu(setup, "Choose weapon for B")
        self.assertIn("A05", {item["value"] for item in weapons["options"]})
        ui.handle_component(self.ctx, event(custom_id=weapons["custom_id"], values=["A05"]))
        setup = self.ctx.interaction.responses[-1]
        self.assertFalse(button(setup, "Compare A / B").get("disabled", False))
        self.assertEqual([field["value"] for field in setup["embeds"][0]["fields"]], ["Astaroth .57", "M4"])
        ui.handle_component(self.ctx, event(custom_id=button(setup, "Compare A / B")["custom_id"]))
        result = self.ctx.interaction.responses[-1]
        self.assertTrue(result["update_message"])
        self.assertIn("Astaroth .57", result["embeds"][0]["description"])
        self.assertIn("M4", result["embeds"][0]["description"])
        self.assertTrue(button(result, "Post graphs to channel")["disabled"])
        self.assertEqual(self.ctx.interaction.modals_sent, [])
        self.assertEqual(self.ctx.kv_writes, [])
        self.assertEqual(self.ctx.messages_sent, [])

    def test_setup_pages_cover_every_named_weapon_and_preserve_build_seed(self):
        from cod_hub import catalog
        first_page = catalog.browse_weapons(page_size=25)
        expected = {item["id"] for page in range(1, first_page["pages"] + 1)
                    for item in catalog.browse_weapons(page=page, page_size=25)["items"]}
        seen = set()
        ui.handle_component(self.ctx, event(custom_id="chc:open:c" + CODE_A))
        setup = self.ctx.interaction.responses[-1]
        for _ in range(10):
            self.assertIn(CODE_A, setup["embeds"][0]["fields"][0]["value"])
            seen.update(item["value"] for item in menu(setup, "Choose weapon for B")["options"])
            next_button = button(setup, "Next weapons")
            if next_button.get("disabled"):
                break
            ui.handle_component(self.ctx, event(custom_id=next_button["custom_id"]))
            setup = self.ctx.interaction.responses[-1]
        self.assertEqual(seen, expected)
        ui.handle_component(self.ctx, event(custom_id=button(setup, "Paste names / codes")["custom_id"]))
        self.assertEqual(self.ctx.interaction.modals_sent[-1]["fields"][0].to_dict()["value"], CODE_A)

    def test_setup_is_owner_bound_and_rejects_unlisted_weapons_or_missing_selection(self):
        ui.handle_component(self.ctx, event(custom_id="chc:open"))
        setup = self.ctx.interaction.responses[-1]
        ui.handle_component(self.ctx, event("222", custom_id=button(setup, "Choose B")["custom_id"]))
        self.assertIn("another person", self.ctx.interaction.responses[-1]["content"])
        ui.handle_component(self.ctx, event(custom_id=menu(setup, "Choose weapon for A")["custom_id"], values=["not_in_menu"]))
        self.assertIn("Choose one", self.ctx.interaction.responses[-1]["content"])
        ui.handle_component(self.ctx, event(custom_id=button(setup, "Compare A / B")["custom_id"]))
        self.assertIn("Choose both", self.ctx.interaction.responses[-1]["content"])
        self.assertEqual(self.ctx.messages_sent, [])
        self.assertEqual(self.ctx.kv_writes, [])

    def test_setup_fits_discord_limits_for_longest_owner_and_two_build_codes(self):
        embed, rows = ui.setup_view("9" * 22, "b", "cA09-43QCD-D4HTW-VI11", "c" + CODE_A, "melee")
        self.assertLessEqual(len(rows), 5)
        self.assertLessEqual(len(embed["description"]), 4096)
        for component in components({"components": rows}):
            self.assertLessEqual(len(component.get("custom_id", "")), 100)
            if component.get("type") == 3:
                self.assertLessEqual(len(component["options"]), 25)

    def test_real_context_rejected_modal_returns_working_setup_and_safe_diagnostics(self):
        class RejectedModal(RuntimeError):
            code = -32602

        class Wire:
            calls, notifications = [], []

            def call(self, method, params):
                payload = json.loads(json.dumps(params))
                self.calls.append((method, payload))
                if method == "interaction.send_modal":
                    raise RejectedModal("Synthetic host rejection with private request details")
                return {}

            def notify(self, method, params):
                self.notifications.append((method, json.loads(json.dumps(params))))

        wire = Wire()
        ctx = Context(server_id="999", plugin_id="rmg84ete7r8b", version="0.1.1", capabilities=CAPS, transport=wire)
        ctx._current_interaction_id = "synthetic-interaction"
        ui.handle_component(ctx, event(custom_id="chc:open:wR03"))
        setup = wire.calls[-1][1]
        ui.handle_component(ctx, event(custom_id=button(setup, "Paste names / codes")["custom_id"]))
        attempt = next(params for method, params in wire.calls if method == "interaction.send_modal")
        self.assertEqual(attempt["components"][0]["components"][0]["value"], "Astaroth .57")
        method, fallback = wire.calls[-1]
        self.assertEqual(method, "interaction.respond")
        self.assertIn("choose weapons below", fallback["content"])
        self.assertTrue(fallback["ephemeral"])
        self.assertEqual(fallback["embeds"][0]["fields"][0]["value"], "Astaroth .57")
        self.assertEqual(menu(fallback, "Choose weapon for B")["type"], 3)
        self.assertIn("-32602", str(wire.notifications))
        self.assertNotIn("private request details", str(wire.notifications))

    def test_two_builds_compare_actual_selections_without_adjusted_damage(self):
        card = self.open(CODE_A, CODE_B)
        text = str(card["embeds"])
        self.assertIn("FSS Tac90 Grip", text)
        self.assertIn("Only A", text)
        self.assertIn(CODE_A, text)
        self.assertIn(CODE_B, text)
        self.assertTrue(button(card, "Post graphs to channel")["disabled"])
        selector = menu(card, "Comparison view")
        self.assertEqual({option["value"] for option in selector["options"]}, {"overview", "details"})
        ui.handle_component(self.ctx, event(custom_id=selector["custom_id"], values=["dps"]))
        view = self.ctx.interaction.responses[-1]
        self.assertTrue(view["update_message"])
        self.assertIn("No attachment-adjusted measurements", str(view["embeds"]))
        self.assertEqual(self.ctx.messages_sent, [])

    def test_graph_choices_and_posting_primary_follow_reviewed_coverage(self):
        card = self.open()
        self.assertEqual({option["value"] for option in menu(card, "Comparison view")["options"]}, {"overview", "dps", "details"})
        self.assertEqual(button(card, "Post graphs to channel")["style"], 1)
        self.assertEqual(button(card, "Post to channel")["style"], 2)
        self.assertIn("Needs matching reviewed measurements: Recoil / gun kick, Aiming sway", str(card["embeds"]))
        missing = self.open("R03", "A05")
        self.assertEqual({option["value"] for option in menu(missing, "Comparison view")["options"]}, {"overview", "details"})
        self.assertEqual(button(missing, "Post to channel")["style"], 1)
        self.assertEqual(button(missing, "Post graphs to channel")["style"], 2)
        self.assertTrue(button(missing, "Post graphs to channel")["disabled"])
        self.assertIn("No reviewed graphs match these selections in this mode", str(missing["embeds"]))
        self.assertEqual(self.ctx.messages_sent, [])

    def test_both_stability_views_are_distinct_and_missing_data_is_explicit(self):
        card = self.open()
        for metric in ("recoil", "sway"):
            ui.handle_component(self.ctx, event(custom_id=menu(card, "Comparison view")["custom_id"], values=[metric]))
            card = self.ctx.interaction.responses[-1]
            self.assertTrue(card["update_message"])
            self.assertIn("not available", card["embeds"][0]["description"])
            self.assertTrue(button(card, "Post graphs to channel")["disabled"])
        self.assertEqual(self.ctx.messages_sent, [])

    def test_real_dps_dates_location_switch_and_mode_isolation(self):
        card = self.open(view="dps")
        text = str(card["embeds"])
        for value in ("300.00", "310.50", "2026-11-05", "2026-10-19", "region unspecified"):
            self.assertIn(value, text)
        selector = menu(card, "Damage profile / hit location")
        self.assertEqual({o["value"] for o in selector["options"]}, {"base_profile", "head"})
        ui.handle_component(self.ctx, event(custom_id=selector["custom_id"], values=["head"]))
        head = self.ctx.interaction.responses[-1]
        self.assertIn("405.00", str(head["embeds"]))
        self.assertIn("403.65", str(head["embeds"]))
        for mode in ("dmz", "warzone"):
            ui.handle_component(self.ctx, event(custom_id=menu(head, "Comparison mode")["custom_id"], values=[mode]))
            empty = self.ctx.interaction.responses[-1]
            self.assertIn("not available", empty["embeds"][0]["description"])
            self.assertTrue(button(empty, "Post graphs to channel")["disabled"])

    def test_post_graph_is_owner_bound_explicit_and_uses_real_png(self):
        card = self.open(view="dps")
        custom_id = button(card, "Post graphs to channel")["custom_id"]
        ui.handle_component(self.ctx, event("222", custom_id=custom_id))
        self.assertIn("another person", self.ctx.interaction.responses[-1]["content"])
        self.assertEqual(self.ctx.messages_sent, [])
        from cod_hub.comparison_charts import render_chart
        def render(*args):
            self.assertTrue(self.ctx.interaction.defers[-1]["ephemeral"])
            return render_chart(*args)
        with patch("cod_hub.comparison_charts.render_chart", side_effect=render):
            ui.handle_component(self.ctx, event(custom_id=custom_id))
        posted = self.ctx.messages_sent[-1]
        self.assertEqual(posted["channel_id"], "333")
        self.assertEqual(posted["allowed_mentions"], {"parse": []})
        self.assertEqual(posted["embeds"][0]["image"]["url"], "attachment://comparison-dps.png")
        png = base64.b64decode(posted["files"][0]["data_b64"])
        with Image.open(BytesIO(png)) as image:
            self.assertEqual(image.size, (760, 700))
        notes = next(item for item in posted["files"] if item["filename"] == "comparison-measurements.txt")
        text = base64.b64decode(notes["data_b64"]).decode("utf8")
        for series in ui._resolve("A01", "A05", "multiplayer", "base_profile")["metrics"]["dps"]["series"]:
            for caveat in series["provenance"]["caveats"]:
                self.assertIn(caveat, text)
            for source in series["provenance"]["components"]:
                self.assertIn(source["source_url"], text)
                self.assertIn(source["source_date"], text)
                self.assertIn(source["note"], text)
        self.assertEqual(self.ctx.http.requests, [])
        copy_id = button(posted, "Open comparison")["custom_id"]
        ui.handle_component(self.ctx, event("222", custom_id=copy_id))
        private_copy = self.ctx.interaction.responses[-1]
        self.assertTrue(private_copy["ephemeral"])
        self.assertFalse(private_copy["update_message"])
        self.assertIn(":222:", menu(private_copy, "Comparison view")["custom_id"])

    def test_share_text_card_has_no_chart_attachment_controls(self):
        card = self.open()
        ui.handle_component(self.ctx, event(custom_id=button(card, "Post to channel")["custom_id"]))
        posted = self.ctx.messages_sent[-1]
        self.assertFalse(posted.get("files"))
        self.assertFalse(any(c.get("placeholder") == "Graph view" for c in components(posted)))
        self.assertNotIn("image", posted["embeds"][0])

    def test_invalid_inputs_and_tampered_controls_never_write_or_post(self):
        for inputs in (("", "A05"), ("x"*257, "A05"), ("A01-1Z1", "A05")):
            result = self.open(*inputs)
            self.assertIn("content", result)
        for raw, values in (("chc:v:111:m:wA01:wA05:d:b", [{}]),
                            ("chc:v:111:unknown:wA01:wA05:d:b", ["dps"]),
                            ("chc:bad:111:m:wA01:wA05:d:b", []), ("chc:"+"x"*101, [])):
            ui.handle_component(self.ctx, event(custom_id=raw, values=values))
            self.assertTrue(self.ctx.interaction.responses[-1]["ephemeral"])
        self.assertEqual(self.ctx.kv_writes, [])
        self.assertEqual(self.ctx.messages_sent, [])

    def test_saved_build_entry_and_maximum_component_lengths(self):
        navigation = {"components": [hub.build_navigation(CODE_A)]}
        self.assertEqual(button(navigation, "Compare build")["custom_id"], "chc:open:c"+CODE_A)
        result = ui._resolve("A09-43QCD-D4HTW-VI11", CODE_A, "multiplayer", "base_profile")
        for component in components({"components": ui.controls(result, "9"*22, "overview", "base_profile")}):
            self.assertLessEqual(len(component.get("custom_id", "")), 100)
            if component.get("type") == 3:
                self.assertLessEqual(len(component["options"]), 25)

    def test_existing_public_graph_cannot_relabel_new_measurement_snapshot(self):
        state = ["m", "wA01", "wA05", "d", "b"]
        custom_id = ui._id("t", "111", state, "deadbeef")
        ui.handle_component(self.ctx, event(custom_id=custom_id, values=["dps"]))
        self.assertIn("changed", self.ctx.interaction.responses[-1]["content"])
        self.assertFalse(self.ctx.interaction.responses[-1]["update_message"])

    def test_attached_graph_toggle_selects_existing_file_when_reviewed_metrics_exist(self):
        # Synthetic UI-only trajectory fixture. It is never written to the
        # reviewed data or represented as a real weapon measurement.
        result = ui._resolve("A01", "A05", "multiplayer", "base_profile")
        result["metrics"]["recoil"] = {"available": True, "reason": None, "series": [
            {"side": side, "label": "Synthetic UI fixture", "points": [{"shot": 1, "x": 0, "y": 0}, {"shot": 2, "x": 1, "y": 1}],
             "unit": "degrees", "condition": "Synthetic test only", "statistic": "single_trial", "sample_count": 1, "provenance": {
                 "source_url": "https://example.invalid/synthetic", "source_date": "2026-01-01", "patch": "Synthetic", "method": "UI test"}}
            for side in ("left", "right")]}
        state = ui._state(result, "dps", "base_profile")
        with patch.object(ui, "_resolve", return_value=deepcopy(result)), patch("cod_hub.comparison_charts.render_chart", return_value=b"\x89PNG\r\n\x1a\nTEST"):
            ui.handle_component(self.ctx, event(custom_id=ui._id("g", "111", state)))
            posted = self.ctx.messages_sent[-1]
            self.assertEqual(len(posted["files"]), 3)
            selector = menu(posted, "Graph view")
            ui.handle_component(self.ctx, event(custom_id=selector["custom_id"], values=["recoil"]))
        updated = self.ctx.interaction.responses[-1]
        self.assertTrue(updated["update_message"])
        self.assertEqual(updated["embeds"][0]["image"]["url"], "attachment://comparison-recoil.png")
        self.assertNotIn("Choose **Post graphs to channel**", updated["embeds"][0]["description"])
        self.assertIn("Chart posted below", updated["embeds"][0]["description"])
        self.assertEqual(len(self.ctx.messages_sent), 1)

    def test_graph_snapshot_is_bound_to_the_result_not_a_second_live_read(self):
        result = ui._resolve("A01", "A05", "multiplayer", "base_profile")
        old_fingerprint = result["telemetry_fingerprint"]
        # A reloaded profile cannot supply new captions to an existing PNG.
        newer = deepcopy(result)
        newer["telemetry_fingerprint"] = "cafebabe" if old_fingerprint != "cafebabe" else "deadbeef"
        cid = ui._id("t", "111", ui._state(result, "dps", "base_profile"), old_fingerprint)
        with patch.object(ui, "_resolve", return_value=newer):
            ui.handle_component(self.ctx, event(custom_id=cid, values=["dps"]))
        self.assertIn("changed", self.ctx.interaction.responses[-1]["content"])
        self.assertFalse(self.ctx.interaction.responses[-1]["update_message"])
        # Merely drawing controls must never ask for a different live digest.
        result["metrics"]["recoil"]["available"] = True
        with patch.object(telemetry, "fingerprint", side_effect=AssertionError("No second live fingerprint read")):
            rows = ui._public_controls(result, "111", "dps", "base_profile", graph_bundle=True)
        self.assertTrue(menu({"components": rows}, "Graph view")["custom_id"].endswith(old_fingerprint))

    def test_overview_can_post_available_stability_graph_without_dps(self):
        # Synthetic UI coverage only; no real recoil measurements are created.
        result = ui._resolve("A01", "A05", "multiplayer", "base_profile")
        result["metrics"]["dps"]["available"] = False
        result["metrics"]["recoil"] = {"available": True, "reason": None, "series": [
            {"side": side, "label": "Synthetic UI fixture", "points": [{"shot": 1, "x": 0, "y": 0}, {"shot": 2, "x": 1, "y": 1}],
             "unit": "degrees", "condition": "Synthetic test only", "statistic": "single_trial", "sample_count": 1,
             "provenance": {"source_url": "https://example.invalid/synthetic", "source_date": "2026-01-01",
                            "patch": "Synthetic", "method": "UI test"}}
            for side in ("left", "right")]}
        card = {"components": ui.controls(result, "111", "overview", "base_profile")}
        self.assertFalse(button(card, "Post graphs to channel").get("disabled", False))
        with patch.object(ui, "_resolve", return_value=result), patch("cod_hub.comparison_charts.render_chart", return_value=b"\x89PNG\r\n\x1a\nTEST"):
            ui.handle_component(self.ctx, event(custom_id=button(card, "Post graphs to channel")["custom_id"]))
        posted = self.ctx.messages_sent[-1]
        self.assertEqual(posted["embeds"][0]["image"]["url"], "attachment://comparison-recoil.png")
        self.assertEqual([file["filename"] for file in posted["files"]], ["comparison-recoil.png", "comparison-measurements.txt"])

    def test_details_are_private_paginated_and_keep_complete_measurement_provenance(self):
        card = self.open(view="dps")
        ui.handle_component(self.ctx, event(custom_id=menu(card, "Comparison view")["custom_id"], values=["details"]))
        detail = self.ctx.interaction.responses[-1]
        self.assertTrue(detail["ephemeral"])
        self.assertTrue(detail["update_message"])
        self.assertEqual(self.ctx.messages_sent, [])
        pages = []
        for _ in range(40):
            pages.append(detail["embeds"][0]["description"])
            next_button = button(detail, "Next details")
            if next_button.get("disabled", False):
                break
            ui.handle_component(self.ctx, event(custom_id=next_button["custom_id"]))
            detail = self.ctx.interaction.responses[-1]
        else:
            self.fail("Measurement details pagination never ended")
        text = "\n".join(pages)
        result = ui._resolve("A01", "A05", "multiplayer", "base_profile")
        for series in result["metrics"]["dps"]["series"]:
            for source in series["provenance"]["components"]:
                self.assertIn(source["source_url"], text)
                self.assertIn(source["source_date"], text)
                self.assertIn(source["note"], text)
            for caveat in series["provenance"]["caveats"]:
                self.assertIn(ui._safe(caveat, 600), text)
            for key in ("method", "patch"):
                self.assertIn(series["provenance"][key], text)
        self.assertIn("body region", text)
        self.assertIn("recoil", text)
        self.assertIn("sway", text)
        # Private paging cannot be driven by another person or an invalid index.
        custom_id = button(detail, "Previous details")["custom_id"]
        ui.handle_component(self.ctx, event("222", custom_id=custom_id))
        self.assertIn("another person", self.ctx.interaction.responses[-1]["content"])
        ui.handle_component(self.ctx, event(custom_id=custom_id.rsplit(":", 1)[0] + ":999"))
        self.assertIn("does not exist", self.ctx.interaction.responses[-1]["content"])
        self.assertEqual(self.ctx.messages_sent, [])

    def test_shared_details_open_for_each_viewer_and_share_current_details_page(self):
        detail = self.open(view="details")
        ui.handle_component(self.ctx, event(custom_id=button(detail, "Next details")["custom_id"]))
        detail = self.ctx.interaction.responses[-1]
        expected = deepcopy(detail["embeds"][0])
        ui.handle_component(self.ctx, event(custom_id=button(detail, "Post to channel")["custom_id"]))
        posted = self.ctx.messages_sent[-1]
        self.assertEqual(posted["embeds"][0], expected)
        source_button = button(posted, "Measurements / sources")
        ui.handle_component(self.ctx, event("222", custom_id=source_button["custom_id"]))
        private = self.ctx.interaction.responses[-1]
        self.assertTrue(private["ephemeral"])
        self.assertFalse(private["update_message"])
        self.assertIn(":222:", button(private, "Next details")["custom_id"])
        self.assertEqual(len(self.ctx.messages_sent), 1)

    def test_details_and_condensed_cards_fit_discord_budgets_with_complete_build_selections(self):
        result = ui._resolve(CODE_A, CODE_B, "multiplayer", "base_profile")
        text = "\n".join(page["body"] for page in ui._detail_pages(result))
        for side in (result["left"], result["right"]):
            self.assertIn(side["code"], text)
            for part in side["attachments"]:
                self.assertIn(part["name"], text)
        for view in ui.VIEWS:
            count = len(ui._detail_pages(result)) if view == "details" else 1
            for page in range(count):
                embed = ui.comparison_embed(result, view, page)
                total = len(embed["title"]) + len(embed["description"]) + len(embed["footer"]["text"])
                self.assertLessEqual(len(embed["description"]), 4096)
                for field in embed.get("fields", []):
                    self.assertLessEqual(len(field["value"]), 1024)
                    total += len(field["name"]) + len(field["value"])
                self.assertLessEqual(total, 6000)
                rows = ui.controls(result, "9" * 22, view, "base_profile", page)
                self.assertLessEqual(len(rows), 5)
                for component in components({"components": rows}):
                    self.assertLessEqual(len(component.get("custom_id", "")), 100)
        overview = ui.comparison_embed(result)
        self.assertNotIn("Measurement limits", str(overview))
        self.assertLess(len(str(overview)), 1800)

    def test_expanded_source_url_remains_complete_in_details_title_and_notes(self):
        from cod_hub.comparison_charts import measurement_notes
        result = ui._resolve("A01", "A05", "multiplayer", "base_profile")
        url = "https://example.invalid/" + "(" * 1200
        provenance = result["metrics"]["dps"]["series"][0]["provenance"]
        provenance["source_url"] = url
        provenance["components"][0]["source_url"] = url
        pages = [ui.comparison_embed(result, "details", page) for page in range(len(ui._detail_pages(result)))]
        source = next(page for page in pages if page.get("url") == url)
        self.assertIn("Open this card's title", source["description"])
        self.assertLessEqual(len(source["description"]), 4096)
        self.assertIn(url, measurement_notes(result))

    def test_public_graph_and_shared_card_instructions_match_available_controls(self):
        private = self.open(view="dps")
        self.assertIn("Choose **Post graphs to channel**", private["embeds"][0]["description"])
        self.assertIn("Post graphs to channel", [c.get("label") for c in components(private)])
        for action in ("Post to channel", "Post graphs to channel"):
            ui.handle_component(self.ctx, event(custom_id=button(private, action)["custom_id"]))
            public = self.ctx.messages_sent[-1]
            text = str(public["embeds"])
            self.assertNotIn("Choose **Post graphs to channel**", text)
            self.assertNotIn("Post to channel and Post graphs to channel publish here", text)
            self.assertNotIn("Post graphs to channel", [c.get("label") for c in components(public)])
            self.assertIn("Open comparison", text)
            if action == "Post graphs to channel":
                self.assertIn("Chart posted below", text)
                self.assertIn("Complete source notes attached", text)


if __name__ == "__main__":
    unittest.main()
