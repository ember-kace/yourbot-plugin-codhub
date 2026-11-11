# Catalog and source notes

The bundled MW4 snapshot is dated **2026-11-09**. It contains 1,264 native asset identities, 35 weapon references, 31 native weapon records and 2,392 attachment bindings. All identities and reserved code positions remain part of validation.

## Native identities

The catalog stores normalized gameplay facts and short labels. The code decoder uses exact native identity tables independently of English labels. A structurally decoded code does not prove current game-mode eligibility, unlock ownership or in-game import acceptance.

The public repository contains the normalized snapshot and compact regression vectors. It does not distribute original game archives, program code, localization dictionaries, account captures or tools that operate on an installed game. The authoring inventory in [metadata/name-inventory.json](../metadata/name-inventory.json) provides exact asset/reference/loot/name-hash joins for future reviewed updates.

## Name reviews

There are **1,181 verified asset names and 35 named weapon references**, or 1,216 real names. Each native-name claim retains its exact name hash, raw value, source, date and mapping method. [Public name snapshots](../metadata/names/) have content hashes in the [source registry](../plugin/cod_hub/data/facts-sources.json).

Formatting normalization and preferred-label decisions remain explicit. These decisions prevent a rejected historical alias from selecting a different item. Public metadata omits local reviewer identities, host paths and private development records. Source classifications describe the evidence type; they are not account identities.

## Description policies

Eighty-three retained records lack a verified developer-assigned name in this snapshot. Two independently pinned policies provide separate English documentation:

- [72 internal descriptions](../metadata/policies/internal-descriptions.json), prefixed `Internal · `.
- [11 technical captions](../metadata/policies/technical-descriptions.json), prefixed `Technical record · `.

These objects remain separate from asset names, name qualities, aliases and claims. They cannot qualify an entry for a verified player-item card or search result. Only the exact reviewed identities, wording, evidence and sources satisfy the coverage rule. Reference weapons, player/account names and other identities receive no general exception. Genuine future verified names take precedence without double counting.

The coverage gate therefore checks **1,216 real names + 83 descriptions = 1,299 required records**. It also checks exact identity sets and native maps, so deleting an entry cannot reduce the requirement. [The provenance migration map](../metadata/policy-migration.json) records content-digest correspondence while excluding original private material.

## Statistics, artwork and references

- Weapon overview values are dated catalog references. They are not a current-balance guarantee.
- The [measurement snapshot](../plugin/cod_hub/data/telemetry.json) contains five reviewed automatic base-weapon Multiplayer DPS profiles, with primary source URLs and separately dated damage/RPM inputs. Modified-build damage, DMZ/Warzone ballistics, real time-to-kill, recoil and aiming-sway measurements are unavailable until matching measurements are reviewed. UI accuracy bars are not converted into performance figures.
- [Native artwork metadata](../plugin/cod_hub/data/native-artwork.json) selects 17 reviewed base-weapon renders and three verified Kastov primary attachment layouts by exact identity/code. Twenty lossless transparent WebPs are bundled for PNG exports and mirrored on the project's GitHub Pages site for embed URLs. They total 2,001,102 bytes and retain identical decoded pixels to their PNG sources. No camos, charms, full runtime-component or shader parity is claimed. Raw game packages, models, textures and private extraction receipts are excluded.
- [Provider artwork metadata](../plugin/cod_hub/data/artwork.json) retains 27 attributed transparent MetaRadar base-weapon image mappings. Native images take priority; eleven weapons need the provider fallback and seven have no image. Missing or corrupt native resources fail safely to a provider embed or text-only export. Source credits and preview scope stay visible.
- Live meta recommendations use attributed MetaRadar responses. DMZ provides an external source link. Wiki references retain article/revision/contributor/license attribution and are not a complete structured database.
- The source registry includes the original public source URLs and dates. Provider outages and freshness are handled separately from offline build decoding.

## Updating data

Keep source URLs, evidence dates and exact identity joins for each change. Update compact public fixtures and relevant pinned policy projections where applicable. Run `python tools/dev.py test` and `python tools/dev.py validate` before packaging. Avoid storing credentials, personal account data, host-specific paths or original game/program files in contributions.
