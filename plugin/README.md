# COD Hub

COD Hub is an unofficial Call of Duty companion for YourBot SDK 0.10.1. Import MW4 build codes, explore weapons and attachments, save loadouts, compare supported weapons, and share cards from Discord chat.

## Start

Install the validated plugin ZIP through YourBot's developer publishing and Marketplace workflow, grant the requested permissions, then run **`/codhub`**. The ZIP places `manifest.json` and `__main__.py` at its root. Full installation and development instructions are in the [public repository](https://github.com/ember-kace/yourbot-plugin-codhub).

The home card offers **Import build**, **Explore weapons**, **Compare** and **My builds**. Browsing and imported previews are private. **Share card**, **Post PNG** and **Post graphs** explicitly publish to the current channel. Shared builds let others save their own copy; saved-build edits remain owner-bound. **Get code** displays copyable code text.

| Command | Use |
|---|---|
| `/codhub` | Open the shared home card and private tools. |
| `/codbuild code:A01-42J19-BU11` | Decode an MW4 build into a private card. |
| `/codweapon query:Kastov` | Find a named weapon. |
| `/codattachment query:grip weapon:A01` | Find an attachment for a weapon. |
| `/codsaved` | List, open, rename or delete your saved builds. |
| `/codcompare left:A01 right:A05` | Compare weapons or builds; view available charts and full measurement sources. |
| `/codmeta` | Browse attributed recommendations by mode and weapon type. |
| `/codreference query:Shipment` | Search dated, attributed wiki references. |

## Behavior and data

Build decoding, saved builds, charts and PNG exports use bundled data. Live meta and wiki requests use YourBot's HTTP proxy, limited to `metaradar.gg` and `callofduty.fandom.com`. The plugin requests interaction responses, per-server KV storage, message sending and the proxy. It does not listen to ordinary messages or fetch player statistics.

Saved builds are scoped to their owner and server, with an advisory 50-build limit. Preview controls expire after seven days; saved records persist independently. Concurrent cross-worker saves may exceed the advisory quota because the platform KV API has no compare-and-swap operation.

The MW4 snapshot is dated 2026-11-09. Verified real names and separately reviewed internal descriptions cover every retained identity. Internal descriptions are metadata, not player-item names. Exact native decoding does not establish live game eligibility or unlock ownership.

Transparent linked images illustrate 27 base weapons; missing artwork uses text-only cards. Selected attachments/camos are not rendered into those images. PNG exports use text layouts. Five reviewed automatic base weapons have theoretical Multiplayer DPS charts with separately dated source inputs. Modified-build DPS, other modes' damage, recoil and aiming sway remain unavailable until matching measurements are reviewed. Meta feeds and wiki articles are attributed references rather than a complete structured game database.

No project license is granted. Included font and identifier notices retain their respective third-party licenses. See the public repository's [usage guide](https://github.com/ember-kace/yourbot-plugin-codhub/blob/main/docs/USAGE.md), [data notes](https://github.com/ember-kace/yourbot-plugin-codhub/blob/main/docs/DATA.md), and [third-party notices](https://github.com/ember-kace/yourbot-plugin-codhub/blob/main/THIRD_PARTY_NOTICES.md).
