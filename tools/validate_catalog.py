"""Verify the curated public catalog and exact public provenance joins."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'plugin')]
from tools.english_release_gate import evaluate_release, ids_digest, native_identity_digest


def main():
    data = ROOT / 'plugin/cod_hub/data'
    catalog = json.loads((data / 'catalog.json').read_text(encoding='utf8'))
    sources = json.loads((data / 'facts-sources.json').read_text(encoding='utf8'))['sources']
    inventory = json.loads((ROOT / 'metadata/name-inventory.json').read_text(encoding='utf8'))
    indexed = {row['asset_id']: row for row in inventory['assets']}
    assert set(indexed) == set(catalog['assets']), 'Public name inventory lost an identity'
    inputs = {}
    for key, source in sources.items():
        if source.get('kind') != 'native_localization':
            continue
        path = (ROOT / source['data_reference']).resolve()
        assert path.is_relative_to((ROOT / 'metadata/names').resolve())
        raw = path.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == source['input_sha256'], key
        document = json.loads(raw)
        assert document['language'] == 'en' and document['source_id'] == key
        inputs[key] = document['names']
    claims = 0
    for asset_id, asset in catalog['assets'].items():
        row = indexed[asset_id]
        assert (row.get('internal_ref'), row.get('loot_id')) == (asset.get('internal_ref'), asset.get('loot_id'))
        for claim in asset.get('name_claims', []):
            if claim.get('quality') != 'native_localization':
                continue
            key = claim['name_hash']
            assert key in row['localize_hashes'], asset_id
            assert inputs[claim['source_id']][key] == claim.get('raw_name', claim['name']), asset_id
            claims += 1
    for reference in catalog['reference_weapons']:
        actual = catalog['assets'][reference['asset_id']]
        for key in ('name', 'quality', 'aliases', 'source_ids', 'name_claims'):
            assert reference.get(key) == actual.get(key), (reference['asset_id'], key)
    report = evaluate_release(ROOT / 'plugin')
    assert report['ready'], report['issues']
    print(json.dumps({'ready': True, 'required': report['required'], 'real_names': report['total_translated'],
                      'descriptions': report['total_described'], 'native_name_claims': claims,
                      'asset_identity_sha256': ids_digest(catalog['assets']),
                      'native_identity_sha256': native_identity_digest(catalog['weapons'])}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
