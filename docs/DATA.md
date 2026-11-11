# Catalog and source notes

The bundled MW4 code snapshot is dated **2026-11-11**. It retains 1,267 asset identities, 35 weapon references, 31 native weapon records and 2,401 active attachment bindings. There are 17 reserved attachment positions and 860 reserved weapon positions. Seven earlier assets remain explicitly historical and are excluded from current attachment browsers. Three user-provided golden codes and all source bindings pass round-trip checks.

## Native identities

The catalog stores normalized gameplay facts and short labels. The code decoder uses exact native identity tables independently of English labels. A structurally decoded code does not prove current game-mode eligibility, unlock ownership or in-game import acceptance.

The public repository contains the normalized snapshot and compact regression vectors. It does not distribute original game archives, program code, full localization resources, account captures or tools that operate on an installed game. The authoring inventory in [metadata/name-inventory.json](../metadata/name-inventory.json) provides exact asset/reference/loot/name-hash joins for future reviewed updates.

## Name reviews

There are **1,184 real-named code-dictionary assets and 35 named weapon references**, or 1,219 translated records in that gate. Each native-name claim retains its name hash, raw English value, source, date and mapping method. [Public name facts](../metadata/names/) have content hashes in the [source registry](../plugin/cod_hub/data/facts-sources.json). The current source lineage and historical factual references remain distinct.

Formatting normalization and preferred-label decisions remain explicit. These decisions prevent a rejected historical alias from selecting a different item. Public metadata omits local reviewer identities, host paths and private development records. Source classifications describe the evidence type; they are not account identities.

## Description policies

Eighty-three retained code-dictionary records continue to use two independently pinned English documentation policies:

- [72 internal descriptions](../metadata/policies/internal-descriptions.json), prefixed `Internal · `.
- [11 technical captions](../metadata/policies/technical-descriptions.json), prefixed `Technical record · `.

These objects remain separate from asset names, name qualities, aliases and claims. They cannot qualify an entry for a verified player-item card or search result. Only the exact reviewed identities, wording, evidence and sources satisfy the coverage rule. Reference weapons, player/account names and other identities receive no general exception. Genuine future verified names take precedence without double counting.

The code-dictionary gate checks **1,219 translated records + 83 descriptions = 1,302 required records**. Exact identities and native maps are pinned independently; deleting an entry cannot reduce the requirement. [The provenance migration map](../metadata/policy-migration.json) preserves digest correspondence without publishing private source material.

## Full native item census

The separate sharded item catalog preserves **8,029 records in 31 categories**: 6,720 named references, 1,238 held records and 71 internal records. Named cards include attachments, camos, reticles, weapon variants, charms, operators, skins, equipment and other native categories. Every census record stays in the packaged metadata; unnamed records cannot enter named browsing or sharing.

Some records inherit a source-proven native base label. Four preserve distinct context-dependent English labels without choosing a canonical name or inferring a mode. Two exact blueprint/reticle identities use the literal assigned title `141`; only those ID/hash/text triples are excepted from the numeric-name heuristic. Default-variant and frontend labels retain their specific provenance. None of these routes fabricates names from internal identifiers.

Held records include 913 native sentinel records, 52 weapon-progression trackers and 56 numeric progression steps, as well as unresolved definitions and literal native placeholders. Their roles are preserved rather than treating all of them as released collectibles. An absent own-name assignment is distinct from a decryption failure. Full item metadata and artwork have separate captured-byte gates; the build dictionary’s older caption exceptions do not automatically extend to these records.

## Native game guide

The separately gated guide retains **683 references from eight current tables**: 587 named and 96 held. Its `g<table-hash>r<row>` identifiers identify source rows and are never treated as loot IDs. Categories include maps, Multiplayer/Warzone daily challenges, calling-card challenges, weapon mastery, DMZ missions and events. All source cells were reconciled to the current snapshot.

Only 113 descriptions have safe static display text. The raw source template and typed operands remain separate for 296 template rows; another 19 need native formatting and 225 are empty. The UI directs contextual requirements to the game. It does not infer counters, rewards, schedules, completion or numeric joins to the item census.

## Statistics, artwork and references

- Weapon overview values are dated catalog references. They are not a current-balance guarantee.
- The [measurement snapshot](../plugin/cod_hub/data/telemetry.json) contains five reviewed automatic base-weapon Multiplayer DPS profiles, with primary source URLs and separately dated damage/RPM inputs. Modified-build damage, DMZ/Warzone ballistics, real time-to-kill, recoil and aiming-sway measurements are unavailable until matching measurements are reviewed. UI accuracy bars are not converted into performance figures.
- [Native artwork metadata](../plugin/cod_hub/data/native-artwork.json) selects all 35 main-browser weapon references and three exact Kastov primary attachment layouts. These 38 transparent lossless WebPs total 3,694,872 bytes and are bundled for PNG export and mirrored on GitHub Pages. Thirty references use models: 15 revalidated primary-component views, ten static assemblies, four explicitly simplified lens-shader views and one folded CSG35 reference. Five held model assemblies use exact native catalog icons instead. No arbitrary build/camo/charm or full shader parity is claimed.
- [Item artwork metadata](../plugin/cod_hub/data/item-artwork.json) retains 2,980 exact native image identities in 2,962 unique WebPs. There are 2,873 ordinary 2D images and 107 labeled static native image-part previews; frame, slice order and animation timing are not inferred. Native image/full-image field associations select the artwork. Cards use the hosted library without an interaction-time HTTP request.
- [Provider artwork metadata](../plugin/cod_hub/data/artwork.json) remains as an attributed fallback for unavailable native resources. It is separate from current native-artwork proof.
- Live meta recommendations use attributed MetaRadar responses. DMZ provides an external source link. Wiki references retain article/revision/contributor/license attribution and are not a complete structured database.
- The source registry includes the original public source URLs and dates. Provider outages and freshness are handled separately from offline build decoding.

## Updating data

Keep source URLs, evidence dates and exact identity joins for each change. Update compact public fixtures and relevant pinned policy projections where applicable. Run `python tools/dev.py test` and `python tools/dev.py validate` before packaging. Avoid storing credentials, personal account data, host-specific paths or original game/program files in contributions.
