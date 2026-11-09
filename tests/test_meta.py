"""Provider contract, durable cooldown and nonfatal outage behavior."""
import copy
import json
import unittest
from unittest.mock import patch

from yourbot_sdk.testing import MockClock, MockContext
from cod_hub import meta


URL = "https://metaradar.gg/api/v1/meta/modernwarfare4"


def feed():
    return {
        "attribution": {"text": "Data by MetaRadar", "url": "https://metaradar.gg/modernwarfare4/meta",
                        "html": "<a>unused HTML</a>", "terms": "https://metaradar.gg/developers"},
        "game": {"slug": "modernwarfare4", "name": "Modern Warfare 4",
                 "url": "https://metaradar.gg/modernwarfare4/meta"},
        "season": "Season 1", "updatedAt": "2026-11-08T13:27:53+00:00",
        "new_provider_field": "forward compatible",
        "weapons": [{"rank": 1, "slug": "sample", "name": "Sample weapon", "class": "AR",
                     "tier": "Meta", "tierLetter": "S", "role": "Long range",
                     "url": "https://metaradar.gg/modernwarfare4/weapons/sample",
                     "icons": ["http://invalid.example/icon.webp", "https://metaradar.gg/icons/sample.webp"],
                     "build": {"label": "Long range", "attachments": [{"slot": "Optic", "name": "Sample optic"}],
                               "shareCode": None, "updatedAt": "2026-11-08T14:00:00Z"}}],
    }


def response(data=None, **extra):
    value = {"status": 200, "body_bytes": json.dumps(feed() if data is None else data), "truncated": False}
    value.update(extra)
    return value


class MetaTests(unittest.TestCase):
    def context(self):
        clock = MockClock(start=1_000_000)
        ctx = MockContext(clock=clock)
        ctx.http.mock_response(URL, body=json.dumps(feed()))
        return ctx, clock

    def get(self, ctx, clock, game="mw4"):
        return meta.get_meta(ctx, game, now=clock.now())

    def test_verified_schema_credit_links_and_nullable_code(self):
        ctx, clock = self.context()
        value = self.get(ctx, clock)
        self.assertTrue(value["available"])
        self.assertFalse(value["stale"])
        self.assertEqual(value["game"], "mw4")
        self.assertEqual(value["provider_game"], "modernwarfare4")
        self.assertEqual(value["attribution"]["text"], "Data by MetaRadar")
        self.assertEqual(value["attribution"]["url"], "https://metaradar.gg/modernwarfare4/meta")
        self.assertEqual(value["weapons"][0]["attachments"], [{"slot": "Optic", "name": "Sample optic"}])
        self.assertIsNone(value["weapons"][0]["code"])
        self.assertIsNone(value["weapons"][0]["mode"])
        self.assertEqual(value["weapons"][0]["build_label"], "Long range")
        self.assertEqual(value["weapons"][0]["icon_url"], "https://metaradar.gg/icons/sample.webp")
        self.assertIn("not a complete", value["coverage"])
        self.assertEqual(ctx.http.requests, [{"method": "GET", "url": URL,
                                            "headers": {"Accept": "application/json"}, "body": None,
                                            "params": None, "secret_auth": None, "auth": None}])

    def test_durable_rolling_cooldown_survives_worker_restart(self):
        first, clock = self.context()
        self.get(first, clock)
        restarted = MockContext(clock=clock)
        restarted.kv = first.kv  # Same installation, fresh process-local/ephemeral state.
        restarted.http.mock_response(URL, body=json.dumps(feed()))
        clock.advance(3599)
        self.assertTrue(self.get(restarted, clock)["available"])
        self.assertEqual(len(restarted.http.requests), 0)
        clock.advance(1)
        self.assertTrue(self.get(restarted, clock)["available"])
        self.assertEqual(len(restarted.http.requests), 1)

    def test_failed_refresh_preserves_cache_and_waits_another_hour(self):
        ctx, clock = self.context()
        original = self.get(ctx, clock)
        clock.advance(3600)
        ctx.http.mock_response(URL, status=503, body="maintenance")
        old = self.get(ctx, clock)
        self.assertTrue(old["available"])
        self.assertTrue(old["stale"])
        self.assertEqual(old["fetched_at"], original["fetched_at"])
        self.assertEqual(old["weapons"], original["weapons"])
        self.assertEqual(old["error"], "http_status")
        clock.advance(3599)
        self.get(ctx, clock)
        self.assertEqual(len(ctx.http.requests), 2)
        changed = feed()
        changed["weapons"][0]["name"] = "New recommendation"
        ctx.http.mock_response(URL, body=json.dumps(changed))
        clock.advance(1)
        new = self.get(ctx, clock)
        self.assertFalse(new["stale"])
        self.assertEqual(new["weapons"][0]["name"], "New recommendation")
        self.assertEqual(len(ctx.http.requests), 3)

    def test_invalid_or_partial_response_never_replaces_complete_cache(self):
        wrong_game = feed()
        wrong_game["game"]["slug"] = "warzone"
        no_credit = feed()
        no_credit.pop("attribution")
        bad_part = feed()
        bad_part["weapons"][0]["build"]["attachments"].append({"slot": "Muzzle"})
        duplicate = feed()
        duplicate["weapons"].append(copy.deepcopy(duplicate["weapons"][0]))
        unsafe_link = feed()
        unsafe_link["weapons"][0]["url"] = "https://metaradar.gg:bad/path"
        cases = [response(truncated=True), response(body_bytes="<html>not JSON</html>"),
                 response(wrong_game), response(no_credit), response(bad_part), response(duplicate),
                 response(unsafe_link), response(body_bytes="x" * 200_001),
                 response(body_bytes=json.dumps(feed())[:-1])]
        for bad in cases:
            with self.subTest(bad=bad):
                ctx, clock = self.context()
                original = self.get(ctx, clock)
                clock.advance(3600)
                with patch.object(ctx.http, "request", return_value=bad):
                    result = self.get(ctx, clock)
                self.assertTrue(result["stale"])
                self.assertEqual(result["weapons"], original["weapons"])
                self.assertEqual(result["attribution"], original["attribution"])
                self.assertTrue(result["error"])

    def test_first_outage_is_nonfatal_and_does_not_retry_per_click(self):
        ctx, clock = self.context()
        ctx.http.mock_response(URL, status=429, body="limited")
        first = self.get(ctx, clock)
        self.assertFalse(first["available"])
        self.assertEqual(first["weapons"], [])
        self.assertIn("Offline", first["warning"])
        clock.advance(30)
        self.get(ctx, clock)
        self.assertEqual(len(ctx.http.requests), 1)

    def test_storage_failure_prevents_uncached_upstream_request(self):
        for operation in ["get", "set"]:
            with self.subTest(operation=operation):
                ctx, clock = self.context()
                with patch.object(ctx.kv, operation, side_effect=RuntimeError("storage offline")):
                    result = self.get(ctx, clock)
                self.assertFalse(result["available"])
                self.assertEqual(result["error"], "cache_unavailable")
                self.assertEqual(ctx.http.requests, [])

    def test_dedup_claim_loser_does_not_fetch(self):
        ctx, clock = self.context()
        self.assertTrue(ctx.ephemeral.dedup("codhub:metaradar:refresh:mw4", ttl_seconds=3600))
        result = self.get(ctx, clock)
        self.assertFalse(result["available"])
        self.assertEqual(ctx.http.requests, [])

    def test_oversized_normalized_cache_is_rejected_without_partial_rows(self):
        ctx, clock = self.context()
        original = self.get(ctx, clock)
        large = feed()
        large["weapons"] = []
        for index in range(25):
            row = copy.deepcopy(feed()["weapons"][0])
            row.update({"rank": index + 1, "slug": "weapon" + str(index)})
            row["build"]["attachments"] = [{"slot": "Optic", "name": "x" * 200}] * 20
            large["weapons"].append(row)
        self.assertLess(len(json.dumps(large).encode()), meta.MAX_RESPONSE_BYTES)
        clock.advance(3600)
        ctx.http.mock_response(URL, body=json.dumps(large))
        result = self.get(ctx, clock)
        self.assertEqual(result["error"], "cache_size")
        self.assertEqual(result["weapons"], original["weapons"])

    def test_http_exception_does_not_escape_optional_adapter(self):
        ctx, clock = self.context()
        with patch.object(ctx.http, "request", side_effect=RuntimeError("proxy unavailable")):
            value = self.get(ctx, clock)
        self.assertFalse(value["available"])
        self.assertEqual(value["error"], "refresh_failed")

    def test_returned_payload_does_not_mutate_durable_cache(self):
        ctx, clock = self.context()
        value = self.get(ctx, clock)
        value["weapons"][0]["name"] = "caller edit"
        self.assertEqual(self.get(ctx, clock)["weapons"][0]["name"], "Sample weapon")

    def test_aliases_and_unsupported_game(self):
        ctx, clock = self.context()
        self.assertEqual(self.get(ctx, clock, "modernwarfare4")["game"], "mw4")
        before = len(ctx.http.requests)
        with self.assertRaises(ValueError):
            self.get(ctx, clock, "unsupported")
        self.assertEqual(len(ctx.http.requests), before)

    def test_each_game_has_its_own_feed_and_cache(self):
        ctx, clock = self.context()
        self.get(ctx, clock, "mw4")
        bo7 = feed()
        bo7["game"]["slug"] = "blackops7"
        bo7["weapons"][0]["name"] = "BO7 recommendation"
        ctx.http.mock_response("https://metaradar.gg/api/v1/meta/blackops7", body=json.dumps(bo7))
        result = self.get(ctx, clock, "bo7")
        self.assertEqual(result["game"], "bo7")
        self.assertEqual(result["weapons"][0]["name"], "BO7 recommendation")
        self.assertEqual(self.get(ctx, clock, "mw4")["weapons"][0]["name"], "Sample weapon")
        self.assertEqual([r["url"] for r in ctx.http.requests],
                         [URL, "https://metaradar.gg/api/v1/meta/blackops7"])


if __name__ == "__main__":
    unittest.main()
