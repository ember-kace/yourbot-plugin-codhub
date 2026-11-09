"""Pure URL parsing/encoding and provider boundaries; no requests are made."""
import unittest
from urllib.parse import quote as reference_quote, unquote, urlencode, urlsplit

from cod_hub import artwork, cards, comparison, meta, reference
from cod_hub.urls import encode_query, percent_encode, split_https


def provenance(url="https://example.invalid/measurements"):
    return {"source_url": url, "source_date": "2026-11-09", "patch": "Synthetic fixture",
            "method": "Synthetic URL-validation fixture only"}


class LocalURLTests(unittest.TestCase):
    def test_supported_https_parts_preserve_text_and_match_standard_parser(self):
        values = ["https://example.invalid", "HTTPS://MeTaRadar.GG:443/weapon_(new)",
                  "https://www.callofduty.com/path?q=a%2Fb&value=x+y#section?more",
                  "https://example.invalid:0443/a b/\u03b1?q=\u00e9 (text)#\u2003note",
                  "https://example.invalid./path?#"]
        for value in values:
            with self.subTest(url=value):
                actual, expected = split_https(value), urlsplit(value)
                for key in ("scheme", "netloc", "path", "query", "fragment", "hostname", "port", "username", "password"):
                    self.assertEqual(getattr(actual, key), getattr(expected, key), key)

    def test_ambiguous_authorities_and_malformed_urls_fail_closed(self):
        values = ["", "https://", "http://example.invalid/", "//example.invalid/", "/relative/path",
                  " https://example.invalid/", "https:////example.invalid/", "https://@example.invalid/",
                  "https://user:pass@example.invalid/", "https://user@example.invalid/", "https://x@@example.invalid/",
                  "https://example.invalid\\@attacker.invalid/", "https://ex\u00e1mple.invalid/",
                  "https://example.invalid\uff0fattacker.invalid/", "https://example%2einvalid/",
                  "https://exa mple.invalid/", "https://example.invalid:/", "https://example.invalid:bad/",
                  "https://example.invalid:+443/", "https://example.invalid:65536/", "https://example.invalid:\uff14\uff14\uff13/",
                  "https://[::1]/", "https://[broken/", "https://a..invalid/", "https://-a.invalid/",
                  "https://a-.invalid/", "https://a_invalid/", "https://" + "a" * 64 + ".invalid/",
                  "https://example.invalid/\nspoof", "https://example.invalid/\x7f", "https://example.invalid/\ud800"]
        for value in values:
            with self.subTest(url=repr(value)), self.assertRaises(ValueError):
                split_https(value)
        for value in (None, b"https://example.invalid/", 123):
            with self.subTest(type=type(value).__name__), self.assertRaises(TypeError):
                split_https(value)

    def test_path_escapes_and_controls_cannot_bypass_provider_path_checks(self):
        suffixes = ["/wiki/../admin", "/wiki/./page", "/wiki/%2E%2e/admin", "/wiki/.%2e/admin",
                    "/wiki/a%2fb", "/wiki/a%5Cb", "/wiki/%00page", "/wiki/page?x=%1f", "/wiki/page#%7F",
                    "/wiki/%", "/wiki/%a", "/wiki/%zz", "/wiki/%1G"]
        for suffix in suffixes:
            with self.subTest(path=suffix), self.assertRaises(ValueError):
                split_https("https://callofduty.fandom.com" + suffix)
        # Opaque query values may contain escaped separators; they cannot change
        # the authority or the path and must survive form-query encoding.
        value = "https://example.invalid/page?query=a%2Fb%5Cc&url=https%3A%2F%2Fexample.invalid"
        self.assertEqual(split_https(value).path, "/page")
        self.assertEqual(split_https(value).query, urlsplit(value).query)

    def test_utf8_percent_encoding_matches_required_standard_semantics(self):
        values = ["", "AZaz09-._~", "a/b?c=d&e=f +%#()[]<>`\"\\", "\u00e9\u03b1\ud55c\uae00\U0001f4a5", "\u2003",
                  "".join(chr(i) for i in range(128))]
        for value in values:
            for safe in ("", "/:"):
                with self.subTest(value=repr(value), safe=safe):
                    self.assertEqual(percent_encode(value, safe), reference_quote(value, safe=safe))
        with self.assertRaises(UnicodeError):
            percent_encode("\ud800")
        for value in (None, b"text", 123):
            with self.assertRaises(TypeError):
                percent_encode(value)

    def test_form_query_encoding_preserves_spaces_plus_percent_and_unicode(self):
        values = {"query": '\ud55c\uae00 + / \\ & "MW4" (map)', "empty": "", "percent": "%20+%2F", "\u00e9": "\u03b1"}
        self.assertEqual(encode_query(values), urlencode(values))
        self.assertEqual(encode_query({}), "")
        for invalid in (None, [], {"query": 7}, {1: "text"}):
            with self.assertRaises(TypeError):
                encode_query(invalid)
        data = {"query": {"rightsinfo": {"text": "CC-BY-SA", "url": "https://www.fandom.com/licensing"}, "pages": []}}
        view = reference._normalize(data, values["query"], "maps", "mw4")
        expected = urlencode({"query": reference._request(values["query"], "maps", "mw4")["gsrsearch"]})
        self.assertEqual(view["source_url"], "https://callofduty.fandom.com/wiki/Special:Search?" + expected)

    def test_card_destinations_keep_literal_spaces_parentheses_and_unicode(self):
        value = "https://example.invalid/Map (\u03b1)/\ud55c\uae00?query=caf\u00e9 + (map)#\u2003note"
        link = cards._link("Source", value)
        destination = link.split("](", 1)[1][:-1]
        self.assertIn("%20", destination)
        self.assertIn("%28", destination)
        self.assertIn("%E2%80%83", destination)
        self.assertEqual(unquote(destination), value)
        encoded = "https://example.invalid/path?query=%2B%2520"
        self.assertIn(encoded, cards._link("Source", encoded))

    def test_provider_host_credentials_port_and_path_rules_remain_enforced(self):
        for suffix in ("@metaradar.gg", "user@metaradar.gg", "metaradar.gg:444", "metaradar.gg.evil.invalid",
                       "metaradar.gg%2e", "metaradar.gg\\@evil.invalid"):
            value = "https://" + suffix + "/modernwarfare4/meta"
            with self.subTest(url=value):
                with self.assertRaises(ValueError):
                    meta._url(value, required=True)
                self.assertIsNone(artwork._url_path(value))
        self.assertEqual(meta._url("HTTPS://WWW.METARADAR.GG:443/modernwarfare4/meta", required=True),
                         "HTTPS://WWW.METARADAR.GG:443/modernwarfare4/meta")
        for value in ("https://@callofduty.fandom.com/wiki/Page", "https://callofduty.fandom.com:444/wiki/Page",
                      "https://callofduty.fandom.com/wiki/%2e%2e/admin", "https://callofduty.fandom.com/other/Page"):
            with self.subTest(url=value), self.assertRaises(ValueError):
                reference._page_url(value)
        self.assertEqual(reference._page_url("https://callofduty.fandom.com:443/wiki/Map_(MW4)"),
                         "https://callofduty.fandom.com:443/wiki/Map_(MW4)")

    def test_measurement_citation_and_component_authorities_fail_closed(self):
        good = provenance("HTTPS://EXAMPLE.INVALID:443/curves?q=\u03b1 (series)")
        self.assertEqual(comparison._provenance(good)["source_url"], good["source_url"])
        for bad in ("https://@example.invalid/", "https://example.invalid:444/", "https://example.invalid\\@other.invalid/",
                    "https://example.invalid/a%2fb", "https://example.invalid/%zz"):
            with self.subTest(url=bad):
                with self.assertRaises(ValueError):
                    comparison._provenance(provenance(bad))
                outer = provenance()
                outer["components"] = [{"metric": "damage", "source_url": bad, "source_date": "2026-11-09"}]
                with self.assertRaises(ValueError):
                    comparison._provenance(outer)
                self.assertEqual(cards._link("Source", bad), "Source")


if __name__ == "__main__":
    unittest.main()
