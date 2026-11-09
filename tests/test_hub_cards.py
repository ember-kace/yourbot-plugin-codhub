"""Presentation limits and safety for the interactive chat workspace."""
import unittest

from cod_hub import hub_cards


def assert_embed_limits(test, embed):
    test.assertLessEqual(len(embed.get("title", "")), 256)
    test.assertLessEqual(len(embed.get("description", "")), 4096)
    test.assertLessEqual(len(embed.get("footer", {}).get("text", "")), 2048)
    fields = embed.get("fields", [])
    test.assertLessEqual(len(fields), 25)
    total = len(embed.get("title", "")) + len(embed.get("description", "")) + len(embed.get("footer", {}).get("text", ""))
    for field in fields:
        test.assertLessEqual(len(field["name"]), 256)
        test.assertLessEqual(len(field["value"]), 1024)
        total += len(field["name"]) + len(field["value"])
    test.assertLessEqual(total, 6000)


class HubCardsTests(unittest.TestCase):
    def test_home_has_clear_paths_and_explicit_private_browsing(self):
        embed = hub_cards.home_embed()
        self.assertEqual(embed["title"], "COD Hub")
        self.assertEqual([field["name"] for field in embed["fields"]], ["Import a build", "Explore weapons", "Compare", "My builds"])
        self.assertIn("privately", embed["footer"]["text"])
        self.assertNotIn("complete catalog", str(embed).lower())
        assert_embed_limits(self, embed)

    def test_weapon_page_has_snapshot_and_reference_distinction(self):
        embed = hub_cards.weapons_embed({"items": [
            {"name": "Kastov 762", "prefix": "A01", "class": "Assault rifles", "snapshot_date": "2026-11-09"},
            {"name": "PILA", "native_supported": False, "class": "Launchers"}],
            "page": 2, "pages": 4, "total": 35}, "Assault rifles")
        self.assertIn("`A01`", embed["description"])
        self.assertIn("Reference weapon", embed["description"])
        self.assertIn("Page 2/4", embed["footer"]["text"])
        self.assertIn("2026-11-09", embed["footer"]["text"])
        assert_embed_limits(self, embed)

    def test_saved_library_empty_state_explains_next_step(self):
        embed = hub_cards.saved_embed([], total=0)
        self.assertIn("Import a code", embed["description"])
        self.assertIn("**Save**", embed["description"])
        self.assertIn("Private library", embed["footer"]["text"])
        assert_embed_limits(self, embed)

    def test_attachment_page_and_empty_reference_are_clear(self):
        weapon = {"name": "Kastov 762", "snapshot_date": "2026-11-09"}
        embed = hub_cards.attachments_embed(weapon, {"items": [{"name": "Field Tac 1.4 Comp", "slot_label": "Muzzle"}], "page": 1, "pages": 1, "total": 1}, "Muzzle")
        self.assertIn("Field Tac 1.4 Comp", embed["description"])
        self.assertIn("1 attachment", embed["footer"]["text"])
        empty = hub_cards.attachments_embed(weapon, {"items": [], "page": 1, "pages": 1, "total": 0, "note": "Sharing is not defined for this reference weapon."})
        self.assertIn("Sharing is not defined", empty["description"])
        assert_embed_limits(self, embed)
        assert_embed_limits(self, empty)

    def test_attachment_filter_uses_weapon_specific_ui_label(self):
        embed = hub_cards.attachments_embed({"name": "Mojave .357"}, {
            "items": [{"name": "Match Cylinder", "slot_label": "Cylinder"}],
            "slots": [{"key": "magazine", "label": "Cylinder", "count": 1}],
            "page": 1, "pages": 1, "total": 1}, "magazine")
        self.assertIn("**Cylinder**", embed["description"])
        self.assertNotIn("magazine", embed["description"])

    def test_user_titles_cannot_inject_mentions_markdown_or_extra_rows(self):
        hostile = "@everyone\n**spoof** [click](https://example.invalid) `code`\x00\u200b"
        saved = hub_cards.saved_embed([{"title": hostile, "code": "A01-42J19-BU11"}], total=1)
        self.assertNotIn("@everyone", saved["description"])
        self.assertNotIn("**spoof**", saved["description"])
        self.assertNotIn("[click](https", saved["description"])
        self.assertNotIn("\x00", saved["description"])
        self.assertNotIn("\u200b", saved["description"])
        self.assertEqual(saved["description"].count("\n"), 3)
        assert_embed_limits(self, saved)

    def test_long_labels_and_oversize_pages_stay_inside_discord_limits(self):
        label = "@everyone [**" + "A" * 10000
        weapons = {"items": [{"name": label, "class": label, "prefix": label, "snapshot_date": label}] * 100,
                   "page": 10**20, "pages": 10**20, "total": 10**20, "query": label}
        records = [{"title": label, "code": label}] * 100
        attachments = {"items": [{"name": label, "slot_label": label}] * 100, "page": 1, "pages": 1, "total": 100}
        for embed in (hub_cards.weapons_embed(weapons, label), hub_cards.saved_embed(records, total=100),
                      hub_cards.attachments_embed({"name": label}, attachments, label), hub_cards.reference_home_embed()):
            assert_embed_limits(self, embed)
            self.assertNotIn("@everyone", str(embed))


if __name__ == "__main__":
    unittest.main()
