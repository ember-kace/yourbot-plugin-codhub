"""Native catalog staging rejects loose names, broken parents and wrong counts."""
from copy import deepcopy
import json
import unittest

from tools import item_catalog_release as release


def candidate():
    items = {}
    for index in range(1, 102):
        items[str(index)] = {"id": index, "kind": "attachment", "name": "Synthetic reference " + str(index),
            "name_hash": f"{index:016x}", "asset_id": f"{index + 1000:016x}", "internal_ref": "synthetic_" + str(index),
            "description": None, "unlock": None, "image_asset_id": None, "quality": "native_localization",
            "status": "resolved", "source_ids": [release.SOURCE_ID], "classification": "player_catalog_record"}
    return {"format_version": 1, "game": "mw4", "snapshot_date": release.SNAPSHOT, "source_id": release.SOURCE_ID,
            "items": items, "coverage": {"native_records": 101,
                "by_kind": {"attachment": {"total": 101, "resolved": 101, "held": 0, "source_proven_internal": 0}}}}


class CatalogReleaseTests(unittest.TestCase):
    def test_context_labels_preserve_native_names_and_reject_an_invented_canonical_name(self):
        source = candidate()
        row = source['items']['1']
        row.update(name=None, name_hash=None, name_source='native_context_labels', display_labels=[
            {'name': 'Synthetic supply box', 'name_hash': '1' * 16, 'context_ids': ['1' * 64]},
            {'name': 'Synthetic ammunition box', 'name_hash': '2' * 16, 'context_ids': ['2' * 64]}])
        release.build_resources(source)
        row['name'] = 'Invented canonical box'
        with self.assertRaises(ValueError):
            release.build_resources(source)
        row['name'] = None
        row['display_labels'][1]['name'] = '#PH:UNASSIGNED'
        with self.assertRaises(ValueError):
            release.build_resources(source)

    def test_staging_is_deterministic_bounded_and_retains_every_source_record(self):
        source = candidate()
        before = deepcopy(source)
        resources = release.build_resources(source)
        self.assertEqual(source, before)
        self.assertEqual(resources, release.build_resources(source))
        document = json.loads(resources["item-catalog.json"])
        self.assertEqual([row["count"] for row in document["categories"]["attachment"]["shards"]], [100, 1])
        self.assertEqual(release.summarize(resources)["native_records"], 101)

    def test_placeholders_or_loose_identity_provenance_cannot_be_named_cards(self):
        for override in ({"name": "#PH:UNASSIGNED_NATIVE_KEY"}, {"name": "COS_REX_061"},
                         {"name": " "}, {"name_hash": None}, {"quality": "guessed"},
                         {"source_ids": ["synthetic-unreviewed"]}, {"source_path": "private"}):
            data = candidate()
            data["items"]["1"].update(override)
            with self.subTest(override=override), self.assertRaises(ValueError):
                release.build_resources(data)

    def test_native_parent_name_requires_the_same_exact_named_identity(self):
        data = candidate()
        child, parent = data["items"]["2"], data["items"]["1"]
        child.update(name=parent["name"], name_hash=parent["name_hash"], base_item_id=1,
                     name_source="native_baseref", classification="blueprint_variant")
        release.build_resources(data)
        for override in ({"base_item_id": 999}, {"name": "Different name"}, {"name_hash": "f" * 16}):
            changed = deepcopy(data)
            changed["items"]["2"].update(override)
            with self.subTest(override=override), self.assertRaises(ValueError):
                release.build_resources(changed)

    def test_internal_parent_can_supply_its_real_native_name_but_not_a_technical_caption(self):
        data = candidate()
        parent, child = data['items']['1'], data['items']['2']
        parent['status'] = 'source_internal'
        data['coverage']['by_kind']['attachment'].update(resolved=100, source_proven_internal=1)
        child.update(name=parent['name'], name_hash=parent['name_hash'], base_item_id=1,
                     name_source='native_baseref', classification='blueprint_variant')
        release.build_resources(data)
        parent['quality'] = 'reviewed_technical_description'
        with self.assertRaises(ValueError):
            release.build_resources(data)

    def test_literal_numeric_title_is_limited_to_the_exact_reviewed_native_identity(self):
        item = candidate()['items']['1']
        item.update(id=134368, name='141', name_hash='77f779fafebe9526', kind='weapon')
        release.reviewed_item(item, '134368')
        item['id'] = 134369
        with self.assertRaises(ValueError):
            release.reviewed_item(item, '134369')

    def test_optional_native_placeholder_text_is_omitted_without_inventing_descriptions(self):
        data = candidate()
        data["items"]["1"]["description"] = "#PH:UNASSIGNED_NATIVE_DESCRIPTION"
        data["items"]["1"]["unlock"] = "Synthetic readable unlock reference."
        resources = release.build_resources(data)
        shard = next(raw for name, raw in resources.items() if name.startswith("items/attachment-000"))
        item = json.loads(shard)[0]
        self.assertIsNone(item["description"])
        self.assertEqual(item["unlock"], "Synthetic readable unlock reference.")


if __name__ == "__main__":
    unittest.main()
