"""Dated, licensed article references and bounded provider behavior."""
import copy
import json
import unittest
from unittest.mock import patch

from yourbot_sdk.testing import MockClock, MockContext
from cod_hub import reference


def wiki_response():
    return {
        "batchcomplete": True,
        "query": {
            "rightsinfo": {"text": "CC-BY-SA", "url": "https://www.fandom.com/licensing"},
            "pages": [{"pageid": 123, "ns": 0, "title": "Sample map", "index": 1,
                       "fullurl": "https://callofduty.fandom.com/wiki/Sample_map",
                       "revisions": [{"revid": 987, "timestamp": "2026-11-08T19:26:38Z",
                                      "slots": {"main": {"content":
                                          "{{game|bo7}}{{Infobox/map|name=Sample|nested={{other|x}}}}\n"
                                          "'''Sample''' is a [[Multiplayer|multiplayer]] map. "
                                          "<ref>Reference text removed</ref>It has two routes.<br>"
                                          "[[File:Art.png|thumb|Art caption]] "
                                          "<gallery>PrivateImage.png|Caption</gallery>"
                                          "[https://example.com More details] &amp; a courtyard."}}}]}],
        },
    }


class ReferenceTests(unittest.TestCase):
    def context(self, data=None):
        clock = MockClock(start=1_000_000)
        ctx = MockContext(clock=clock)
        ctx.http.mock_response(reference.API_URL, body=json.dumps(wiki_response() if data is None else data))
        return ctx, clock

    def get(self, ctx, clock, query="Sample map", category="maps", game="bo7"):
        return reference.get_reference(ctx, query, category, game, now=clock.now())

    def test_supported_api_shape_and_revision_license_attribution(self):
        ctx, clock = self.context()
        value = self.get(ctx, clock)
        self.assertTrue(value["available"])
        self.assertFalse(value["stale"])
        item = value["items"][0]
        self.assertEqual(item["extract"], "Sample is a multiplayer map. It has two routes. More details & a courtyard.")
        self.assertEqual(item["url"], "https://callofduty.fandom.com/wiki/Sample_map?oldid=987")
        self.assertEqual(item["revision"], 987)
        self.assertEqual(item["timestamp"], "2026-11-08T19:26:38Z")
        self.assertEqual(item["license_url"], "https://www.fandom.com/licensing")
        self.assertEqual(value["attribution"]["text"], "Call of Duty Wiki contributors")
        self.assertIn("formatting removed", value["adaptation"])
        call = ctx.http.requests[0]
        self.assertEqual(call["url"], reference.API_URL)
        self.assertEqual(call["params"]["gsrlimit"], 5)
        self.assertEqual(call["params"]["rvsection"], 0)
        self.assertEqual(call["params"]["meta"], "siteinfo")
        self.assertNotIn("extracts", call["params"]["prop"])
        self.assertNotIn("rvlimit", call["params"])
        self.assertIn('"Black Ops 7"', call["params"]["gsrsearch"])

    def test_twelve_hour_cache_survives_restart_and_case_variants(self):
        ctx, clock = self.context()
        self.get(ctx, clock)
        restarted = MockContext(clock=clock)
        restarted.kv = ctx.kv
        restarted.http.mock_response(reference.API_URL, body=json.dumps(wiki_response()))
        clock.advance(43_199)
        self.assertTrue(self.get(restarted, clock, "sample MAP")["available"])
        self.assertEqual(restarted.http.requests, [])
        clock.advance(1)
        self.assertTrue(self.get(restarted, clock)["available"])
        self.assertEqual(len(restarted.http.requests), 1)

    def test_outage_retains_revision_and_does_not_retry_per_click(self):
        ctx, clock = self.context()
        first = self.get(ctx, clock)
        clock.advance(43_200)
        ctx.http.mock_response(reference.API_URL, status=403, body="denied")
        value = self.get(ctx, clock)
        self.assertTrue(value["available"])
        self.assertTrue(value["stale"])
        self.assertEqual(value["items"], first["items"])
        clock.advance(60)
        self.get(ctx, clock)
        self.assertEqual(len(ctx.http.requests), 2)

    def test_incomplete_unsafe_unlicensed_and_truncated_data_are_not_displayed(self):
        no_revision = wiki_response()
        no_revision["query"]["pages"][0]["revisions"][0].pop("revid")
        wrong_host = wiki_response()
        wrong_host["query"]["pages"][0]["fullurl"] = "https://other.example/wiki/Sample"
        different_license = wiki_response()
        different_license["query"]["rightsinfo"]["text"] = "All rights reserved"
        missing_license = wiki_response()
        missing_license["query"].pop("rightsinfo")
        too_many = wiki_response()
        too_many["query"]["pages"] *= 6
        warning = wiki_response()
        warning["warnings"] = {"query": "unsupported parameter"}
        for data in [no_revision, wrong_host, different_license, missing_license, too_many, warning,
                     {"error": {"code": "invalidparammix"}}]:
            with self.subTest(data=data):
                ctx, clock = self.context(data)
                value = self.get(ctx, clock)
                self.assertFalse(value["available"])
                self.assertEqual(value["items"], [])
        ctx, clock = self.context()
        with patch.object(ctx.http, "request", return_value={"status": 200, "truncated": True,
                                                           "body_bytes": json.dumps(wiki_response())}):
            self.assertFalse(self.get(ctx, clock)["available"])

    def test_empty_search_is_a_cached_valid_result(self):
        data = wiki_response()
        data["query"].pop("pages")
        ctx, clock = self.context(data)
        result = self.get(ctx, clock)
        self.assertTrue(result["available"])
        self.assertEqual(result["items"], [])
        self.assertIn("No matching", result["warning"])
        self.get(ctx, clock)
        self.assertEqual(len(ctx.http.requests), 1)

    def test_long_excerpts_are_bounded_and_media_is_not_republished(self):
        data = wiki_response()
        data["query"]["pages"][0]["revisions"][0]["slots"]["main"]["content"] += " Long description." * 200
        ctx, clock = self.context(data)
        item = self.get(ctx, clock)["items"][0]
        self.assertLessEqual(len(item["extract"]), 900)
        self.assertTrue(item["extract"].endswith("…"))
        self.assertNotIn("Art caption", item["extract"])
        self.assertNotIn("image", item)

    def test_query_context_keys_do_not_share_incompatible_cached_results(self):
        ctx, clock = self.context()
        self.get(ctx, clock)
        self.get(ctx, clock, category="camos")
        self.get(ctx, clock, game="mw4")
        self.assertEqual(len(ctx.http.requests), 3)
        self.assertIn("camouflage", ctx.http.requests[1]["params"]["gsrsearch"])
        self.assertIn('"Modern Warfare 4"', ctx.http.requests[2]["params"]["gsrsearch"])

    def test_perks_and_equipment_have_distinct_search_context(self):
        ctx, clock = self.context()
        for category, term in [("perks", "perk"), ("equipment", "equipment")]:
            with self.subTest(category=category):
                value = self.get(ctx, clock, query="Ghost", category=category, game="bo7")
                self.assertTrue(value["available"])
                self.assertEqual(value["category"], category)
                self.assertEqual(ctx.http.requests[-1]["params"]["gsrsearch"],
                                 'Ghost ' + term + ' "Black Ops 7"')
        self.assertEqual(len(ctx.http.requests), 2)

    def test_invalid_input_and_storage_failure_never_fetch(self):
        ctx, clock = self.context()
        for query, category, game in [("", "maps", "bo7"), ("x" * 121, "maps", "bo7"),
                                      ("name", "bad", "bo7"), ("name", "maps", "bad")]:
            with self.subTest(query=query, category=category, game=game), self.assertRaises(ValueError):
                self.get(ctx, clock, query, category, game)
        self.assertEqual(ctx.http.requests, [])
        with patch.object(ctx.kv, "set", side_effect=RuntimeError("storage unavailable")):
            self.assertFalse(self.get(ctx, clock)["available"])
        self.assertEqual(ctx.http.requests, [])

    def test_returned_items_do_not_mutate_cached_copy(self):
        ctx, clock = self.context()
        result = self.get(ctx, clock)
        result["items"][0]["extract"] = "caller edit"
        self.assertNotEqual(self.get(ctx, clock)["items"][0]["extract"], "caller edit")

    def test_proxy_exception_is_nonfatal(self):
        ctx, clock = self.context()
        with patch.object(ctx.http, "request", side_effect=RuntimeError("proxy unavailable")):
            value = self.get(ctx, clock)
        self.assertFalse(value["available"])
        self.assertEqual(value["error"], "refresh_failed")


if __name__ == "__main__":
    unittest.main()
