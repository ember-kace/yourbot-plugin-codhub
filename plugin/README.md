# COD Hub

COD Hub is an unofficial Call of Duty companion for YourBot SDK 0.10.1. Import MW4 build codes, explore weapons and attachments, save loadouts, compare supported weapons, and share cards from Discord chat.

## Start

Install the validated plugin ZIP through YourBot's developer publishing and Marketplace workflow, grant the requested permissions, then run **`/codhub`**. The ZIP places `manifest.json` and `__main__.py` at its root. Full installation and development instructions are in the [public repository](https://github.com/ember-kace/yourbot-plugin-codhub).

The compact home card offers **Import code**, **My builds** and **Compare**, followed by **Weapons**, **Meta builds** and **Game guide**. Import code opens a Discord popup: paste your code, optionally name it, and submit to generate a private card. Compare opens an A/B weapon picker; choose both weapons and select **Compare A / B**, or use **Paste names / codes** for builds. Invalid pasted comparison input keeps the valid selection and identifies which side needs another choice. Browsing and imported previews are private. **Post to channel**, **Post PNG to channel** and **Post graphs to channel** explicitly publish to the current channel. Shared builds let others save their own copy; saved-build edits remain owner-bound. **Show code** displays private copyable code text. Only graph views with compatible reviewed measurements appear in the result's view menu.

If YourBot rejects the popup before it opens, import directly with `/codbuild code:A01-42J19-BU11`. A live modal request has returned an unexplained Discord HTTP 400. Version 0.1.4 adds specific recovery and safe diagnostics; the popup rejection itself remains unresolved. See [troubleshooting](https://github.com/ember-kace/yourbot-plugin-codhub/blob/main/docs/USAGE.md#installation-and-troubleshooting).

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
