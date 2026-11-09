"""Mode provenance, preserved provider ranks and private class-filter journeys."""
import copy
import json
import unittest
from unittest.mock import patch

from yourbot_sdk.testing import MockClock, MockContext, make_event

from cod_hub import meta, meta_browser as browser

MP_URL = "https://metaradar.gg/api/v1/meta/modernwarfare4"
WZ_URL = "https://metaradar.gg/api/v1/meta/warzone"
CAPS = ["interaction:respond", "storage:kv", "discord:send_message", "proxy:http"]


def event(user="111", **kwargs):
    return make_event("interaction_create", interaction_type=3, user_id=user, channel_id="333", **kwargs)


def feed(game="modernwarfare4"):
    rows = []
    for rank, kind in enumerate(["SMG", "AR", "AR", "LMG", "AR", "AR", "AR", "AR", "BR", "Pistols"], 1):
        row = {"rank": rank, "slug": f"weapon-{rank}", "name": f"Weapon {rank}", "class": kind,
               "tier": "Meta", "tierLetter": "S", "role": "Long range",
               "url": f"https://metaradar.gg/{game}/weapons/weapon-{rank}", "icons": [],
               "build": {"label": "Long range", "attachments": [{"slot": "Muzzle", "name": "Sample suppressor"}],
                         "shareCode": None, "updatedAt": "2026-11-09T15:00:00Z"}}
        rows.append(row)
    return {"attribution": {"text": "Data by MetaRadar", "url": f"https://metaradar.gg/{game}/meta"},
            "game": {"slug": game, "name": game, "url": f"https://metaradar.gg/{game}/meta"},
            "season": "Season 1", "updatedAt": "2026-11-09T15:00:00Z", "weapons": rows}


def components(payload):
    return [item for row in payload.get("components", [])
            for item in (row.to_dict() if hasattr(row, "to_dict") else row)["components"]]


def menu(payload, placeholder):
    return next(item for item in components(payload) if item.get("placeholder") == placeholder)


def button(payload, label):
    return next(item for item in components(payload) if item.get("label") == label)


class MetaBrowserTests(unittest.TestCase):
    def setUp(self):
        self.clock = MockClock(start=1_000_000)
        self.ctx = MockContext(server_id="999", plugin_id="rmg84ete7r8b", capabilities=CAPS, clock=self.clock)
        self.ctx.http.mock_response(MP_URL, body=json.dumps(feed()))
        self.ctx.http.mock_response(WZ_URL, body=json.dumps(feed("warzone")))

    def view(self, mode="multiplayer", kind="all", page=1):
        return browser.get_mode_meta(self.ctx, mode, kind, page, now=self.clock.now())

    def test_explicit_mode_routes_and_dmz_never_fetches_or_reuses_mp(self):
        mp = self.view()
        self.assertEqual(mp["mode_scope"], "Modern Warfare 4 Multiplayer")
        self.assertIsNone(mp["weapons"][0]["mode"])
        wz = self.view("warzone")
        self.assertEqual(wz["mode_scope"], "Warzone Battle Royale")
        self.assertEqual(wz["game"], "warzone")
        before = len(self.ctx.http.requests)
        dmz = self.view("dmz")
        self.assertFalse(dmz["available"])
        self.assertEqual(dmz["weapons"], [])
        self.assertEqual(dmz["error"], "dmz_feed_not_configured")
        self.assertEqual(len(self.ctx.http.requests), before)
        self.assertEqual([r["url"] for r in self.ctx.http.requests], [MP_URL, WZ_URL])

    def test_type_aliases_filter_provider_class_preserving_global_ranks(self):
        first = self.view(kind="Assault Rifles")
        self.assertEqual(first["weapon_type"], "ar")
        self.assertEqual([r["rank"] for r in first["weapons"]], [2, 3, 5, 6, 7])
        self.assertEqual(first["total"], 6)
        self.assertEqual(first["pages"], 2)
        second = self.view(kind="AR", page=2)
        self.assertEqual([r["rank"] for r in second["weapons"]], [8])
        self.assertEqual(self.view(kind="Battle Rifles")["weapons"][0]["rank"], 9)
        self.assertEqual(self.view(kind="handgun")["weapons"][0]["rank"], 10)
        self.assertEqual(self.view(kind="DMR")["weapons"], [])
        self.assertEqual(len(self.ctx.http.requests), 1)

    def test_filter_changes_and_worker_restart_share_hourly_game_cache(self):
        original = self.view()
        self.view(kind="SMGs")
        self.view(kind="LMGs")
        self.assertEqual(len(self.ctx.http.requests), 1)
        fresh = MockContext(server_id="999", plugin_id="rmg84ete7r8b", capabilities=CAPS, clock=self.clock)
        fresh.kv = self.ctx.kv
        value = browser.get_mode_meta(fresh, "multiplayer", "AR", now=self.clock.now()+30)
        self.assertTrue(value["available"])
        self.assertEqual(fresh.http.requests, [])
        self.assertEqual(value["updated_at"], original["updated_at"])
        value["weapons"][0]["name"] = "Caller mutation"
        self.assertNotEqual(self.view(kind="AR")["weapons"][0]["name"], "Caller mutation")

    def test_empty_type_retains_provider_availability_and_source_dates(self):
        view = self.view(kind="launchers")
        self.assertTrue(view["available"])
        self.assertEqual(view["weapons"], [])
        self.assertEqual((view["page"], view["pages"], view["total"]), (1, 1, 0))
        embed = browser.browser_embed(view)
        self.assertIn("No provider recommendations", embed["description"])
        self.assertIn("2026-11-09", embed["description"])
        self.assertIn("Data by MetaRadar", embed["description"])

    def test_invalid_mode_type_and_page_are_rejected_without_network(self):
        for kwargs in ({"mode": "mw2dmz"}, {"mode": []}, {"mode": "multiplayer", "weapon_type": "unknown"},
                       {"mode": "multiplayer", "page": 0}, {"mode": "multiplayer", "page": True},
                       {"mode": "multiplayer", "page": 1000}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                browser.get_mode_meta(self.ctx, **kwargs)
        self.assertEqual(self.ctx.http.requests, [])
        with self.assertRaises(ValueError):
            self.view(page=3)

    def test_future_explicit_conflicting_mode_is_not_relabelled(self):
        data = feed()
        data["weapons"][0]["build"]["mode"] = "dmz"
        self.ctx.http.mock_response(MP_URL, body=json.dumps(data))
        view = self.view()
        self.assertNotIn(1, [row["rank"] for row in view["weapons"]])
        self.assertEqual(view["total"], 9)

    def test_ui_defers_privately_before_provider_then_filters_and_opens_details(self):
        original = meta.get_meta
        def checked(*args, **kwargs):
            self.assertEqual(self.ctx.interaction.defers[-1], {"ephemeral": True})
            return original(*args, **kwargs)
        with patch.object(meta, "get_meta", side_effect=checked):
            browser.handle_open(self.ctx, event(), mode="multiplayer", weapon_type="ar")
        first = self.ctx.interaction.followups[-1]
        self.assertTrue(first["ephemeral"])
        self.assertEqual(first["allowed_mentions"], {"parse": []})
        choice = menu(first, "Choose a meta build")
        browser.handle_component(self.ctx, event(custom_id=choice["custom_id"], values=[choice["options"][0]["value"]]))
        detail = self.ctx.interaction.followups[-1]
        self.assertEqual(detail["embeds"][0]["title"], "Weapon 2")
        self.assertIn("Sample suppressor", str(detail["embeds"][0]))
        self.assertIn("Not supplied by this source", str(detail["embeds"][0]))
        self.assertIn("Data by MetaRadar", detail["embeds"][0]["description"])
        self.assertIn("https://metaradar.gg/modernwarfare4/weapons/weapon-2", str(detail["embeds"][0]))
        self.assertEqual(self.ctx.interaction.responses, [])
        self.assertEqual(self.ctx.messages_sent, [])

    def test_menu_changes_and_paging_preserve_owner_and_rank(self):
        browser.handle_open(self.ctx, event())
        start = self.ctx.interaction.followups[-1]
        selector = menu(start, "Filter by weapon type")
        browser.handle_component(self.ctx, event(custom_id=selector["custom_id"], values=["ar"]))
        first = self.ctx.interaction.followups[-1]
        browser.handle_component(self.ctx, event(custom_id=button(first, "Next")["custom_id"]))
        second = self.ctx.interaction.followups[-1]
        self.assertEqual(second["embeds"][0]["fields"][0]["name"], "#8")
        self.assertEqual(len(self.ctx.http.requests), 1)
        browser.handle_component(self.ctx, event("222", custom_id=button(second, "Previous")["custom_id"]))
        self.assertIn("another person", self.ctx.interaction.followups[-1]["content"])
        self.assertEqual(len(self.ctx.http.requests), 1)

    def test_dmz_empty_state_has_working_controls_but_zero_requests(self):
        browser.handle_open(self.ctx, event(), mode="dmz", weapon_type="ar")
        result = self.ctx.interaction.followups[-1]
        self.assertIn("In-card DMZ", result["embeds"][0]["description"])
        self.assertIn("October 28, 2026", result["embeds"][0]["description"])
        self.assertEqual(button(result, "Open external DMZ builds")["url"], browser.DMZ_SOURCE)
        self.assertEqual(button(result, "Import build")["custom_id"], "chh:import")
        self.assertTrue(menu(result, "Choose mode"))
        self.assertTrue(menu(result, "Filter by weapon type"))
        self.assertEqual(self.ctx.http.requests, [])
        self.assertEqual(self.ctx.kv_writes, [])
        self.assertTrue(result["ephemeral"])

    def test_warzone_code_is_only_source_text_never_native_auto_import(self):
        data = feed("warzone")
        code = "A09-23Y1W-DYN6F-11"
        data["weapons"][0]["build"]["shareCode"] = code
        self.ctx.http.mock_response(WZ_URL, body=json.dumps(data))
        view = self.view("warzone")
        embed = browser.detail_embed(view, view["weapons"][0])
        self.assertIn(code, str(embed))
        self.assertIn("not automatically imported", embed["description"])
        self.assertEqual(view["game"], "warzone")

    def test_bad_selects_unknown_controls_and_out_of_page_ranks_remain_private(self):
        bad = [("chm:type:111:multiplayer:all:1", []), ("chm:mode:111:multiplayer:all:1", ["mw2dmz"]),
               ("chm:pick:111:multiplayer:all:1", ["99999"]), ("chm:page:111:multiplayer:all:0", None),
               ("chm:bad:111:multiplayer:all:1", None)]
        for custom_id, values in bad:
            browser.handle_component(self.ctx, event(custom_id=custom_id, values=values))
            self.assertTrue(self.ctx.interaction.followups[-1]["ephemeral"])
            self.assertIn("content", self.ctx.interaction.followups[-1])
        self.assertEqual(self.ctx.messages_sent, [])

    def test_snapshot_failure_and_ui_component_limits(self):
        self.ctx.http.mock_response(MP_URL, status=503, body="unavailable")
        view = self.view()
        self.assertFalse(view["available"])
        self.assertIn("temporarily unavailable", browser.browser_embed(view)["description"])
        for mode in browser.MODE_LABELS:
            value = browser.get_mode_meta(self.ctx, mode, now=self.clock.now())
            rows = browser.browser_controls("9"*22, value)
            self.assertLessEqual(len(rows), 5)
            for row in rows:
                items = row.to_dict()["components"]
                self.assertLessEqual(len(items), 5)
                for item in items:
                    if "custom_id" in item:
                        self.assertLessEqual(len(item["custom_id"]), 100)
                    self.assertLessEqual(len(item.get("options", [])), 25)


if __name__ == "__main__":
    unittest.main()
