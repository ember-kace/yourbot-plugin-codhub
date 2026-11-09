"""Accepted HTTP provider data must still fit complete, attributed Discord cards."""
import json
import unittest
from urllib.parse import unquote

from yourbot_sdk.testing import MockContext

from cod_hub import cards, meta, reference


def context():
    return MockContext(server_id="999", plugin_id="yourbot-cod-hub",
                       capabilities=["storage:kv", "proxy:http"])


def meta_feed():
    rows = []
    for n in range(5):
        rows.append({"rank": n + 1, "slug": f"weapon-{n}", "name": f"Weapon {n}",
                     "url": f"https://metaradar.gg/weapons/weapon-{n}", "tier": "S",
                     "build": {"label": "Published recommendation", "shareCode": f"A0{n}-TEST-CODE",
                               "attachments": [{"slot": "S" * 80, "name": "N" * 200}] * 8}})
    return {"game": {"slug": "modernwarfare4", "name": "Modern Warfare 4",
                     "url": "https://metaradar.gg/modernwarfare4"},
            "updatedAt": "2026-11-09T12:00:00Z", "weapons": rows,
            "attribution": {"text": "Data by MetaRadar", "url": "https://metaradar.gg/"}}


def meta_view(data):
    ctx = context()
    ctx.http.mock_response("https://metaradar.gg/api/v1/meta/modernwarfare4", body=json.dumps(data))
    return meta.get_meta(ctx, "mw4", now=100000)


def wiki_data(path_length=250):
    pages = []
    for n in range(4):
        pages.append({"ns": 0, "index": n, "title": "A" * 249 + str(n),
                      "fullurl": "https://callofduty.fandom.com/wiki/" + "A" * (path_length - 1) + str(n),
                      "revisions": [{"revid": 100 + n, "timestamp": "2026-11-09T12:00:00Z",
                                     "slots": {"main": {"content": "Verified test excerpt " * 60}}}]})
    return {"query": {"rightsinfo": {"text": "CC BY-SA", "url": "https://www.fandom.com/licensing"},
                      "pages": pages}}


def wiki_view(data):
    ctx = context()
    ctx.http.mock_response(reference.API_URL, body=json.dumps(data))
    return reference.get_reference(ctx, "long title", now=100000)


class ProviderCardContracts(unittest.TestCase):
    def assert_limits(self, embed):
        self.assertLessEqual(len(embed.get("title", "")), 256)
        self.assertLessEqual(len(embed.get("description", "")), 4096)
        fields = embed.get("fields", [])
        self.assertLessEqual(len(fields), 25)
        total = len(embed.get("title", "")) + len(embed.get("description", ""))
        total += len(embed.get("footer", {}).get("text", ""))
        for field in fields:
            self.assertLessEqual(len(field["name"]), 256)
            self.assertLessEqual(len(field["value"]), 1024)
            total += len(field["name"]) + len(field["value"])
        self.assertLessEqual(total, 6000)

    def test_long_accepted_meta_retains_whole_credit_source_and_codes(self):
        data = meta_feed()
        data["attribution"]["text"] = "M" * 200
        prefix = "https://metaradar.gg/credit-"
        data["attribution"]["url"] = prefix + "a" * (1200 - len(prefix))
        view = meta_view(data)
        self.assertTrue(view["available"])
        embed = cards.meta_embed(view)
        self.assert_limits(embed)
        self.assertIn(data["attribution"]["url"], embed["description"])
        self.assertIn("shortened or omitted", embed["description"])
        for field in embed["fields"]:
            source = view["weapons"][int(field["name"][1:]) - 1]
            self.assertIn(source["url"], field["value"])
            self.assertIn("`" + source["code"] + "`", field["value"])

    def test_unicode_credit_is_preserved_without_utf8_escape_expansion(self):
        data = meta_feed()
        prefix = "https://metaradar.gg/"
        data["attribution"]["url"] = prefix + "界" * (1200 - len(prefix))
        view = meta_view(data)
        self.assertTrue(view["available"])
        embed = cards.meta_embed(view)
        self.assert_limits(embed)
        self.assertIn(data["attribution"]["url"], embed["description"])

    def test_expanded_credit_moves_to_complete_title_link_when_needed(self):
        data = meta_feed()
        prefix = "https://metaradar.gg/"
        data["attribution"]["text"] = "M" * 200
        data["attribution"]["url"] = prefix + "(" * (1200 - len(prefix))
        data["updatedAt"] = "2026-11-09T12:00:00Z" + "D" * 60
        view = meta_view(data)
        self.assertTrue(view["available"])
        embed = cards.meta_embed(view)
        self.assert_limits(embed)
        self.assertEqual(embed["url"], data["attribution"]["url"])
        self.assertIn("Open this card's title", embed["description"])

    def test_unfittable_meta_source_omits_whole_rows_with_honest_count(self):
        data = meta_feed()
        for row in data["weapons"]:
            prefix = "https://metaradar.gg/"
            row["url"] = prefix + "a" * (1200 - len(prefix))
        view = meta_view(data)
        self.assertTrue(view["available"])
        embed = cards.meta_embed(view)
        self.assert_limits(embed)
        self.assertEqual(embed["fields"], [])
        self.assertIn("5 omitted", embed["description"])
        self.assertIn("https://metaradar.gg/", embed["description"])

    def test_accepted_wiki_excerpts_shorten_around_complete_revision_links(self):
        view = wiki_view(wiki_data())
        self.assertTrue(view["available"])
        embed = cards.reference_embed(view)
        self.assert_limits(embed)
        self.assertEqual(len(embed["fields"]), 4)
        for field, item in zip(embed["fields"], view["items"]):
            self.assertIn(item["url"], field["value"])
            self.assertIn("2026-11-09", field["value"])
            self.assertIn("…", field["value"])
        self.assertIn("Call of Duty Wiki contributors", embed["description"])
        self.assertIn("https://www.fandom.com/licensing", embed["description"])
        self.assertIn("shortened further", embed["description"])

    def test_wiki_oversize_revision_links_omit_rows_without_cutting_links(self):
        view = wiki_view(wiki_data(path_length=1400))
        self.assertTrue(view["available"])
        embed = cards.reference_embed(view)
        self.assert_limits(embed)
        self.assertEqual(embed["fields"], [])
        self.assertIn("4 omitted", embed["description"])
        self.assertIn(reference.WIKI_URL, embed["description"])
        self.assertIn("https://www.fandom.com/licensing", embed["description"])

    def test_parenthesized_wiki_path_keeps_revision_destination_after_normalization(self):
        data = wiki_data()
        data['query']['pages'] = data['query']['pages'][:1]
        data['query']['pages'][0]['fullurl'] = "https://callofduty.fandom.com/wiki/Map_(Modern_Warfare_4)"
        view = wiki_view(data)
        self.assertTrue(view['available'])
        embed = cards.reference_embed(view)
        self.assert_limits(embed)
        value = embed['fields'][0]['value']
        encoded = value.split('[Source and revision](', 1)[1].split(')', 1)[0]
        self.assertEqual(unquote(encoded), view['items'][0]['url'])

    def test_links_preserve_destinations_and_reject_unsafe_protocols_controls(self):
        url = "https://callofduty.fandom.com/wiki/Map_(Modern_Warfare_4)?oldid=987"
        link = cards._link("Source and revision", url)
        self.assertIn("%28Modern_Warfare_4%29", link)
        self.assertEqual(unquote(link.split("](", 1)[1][:-1]), url)
        long_url = "https://example.com/" + "a" * 2400
        self.assertIn(long_url, cards._link("Source", long_url))
        for unsafe in ("http://example.com/", "javascript:alert(1)", "https://", "https://x:bad/",
                       "https://example.com/\nspoof", "https://example.com/\x01", "https://example.com/\x7f",
                       "https://user:password@example.com/", "https://@example.com/"):
            with self.subTest(url=unsafe):
                self.assertEqual(cards._link("Source", unsafe), "Source")


if __name__ == "__main__":
    unittest.main()
