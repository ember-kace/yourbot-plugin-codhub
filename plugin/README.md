# COD Hub

COD Hub is an unofficial Call of Duty companion for YourBot SDK 0.10.1. Import MW4 build codes, explore weapons and attachments, save loadouts, compare supported weapons, and share cards from Discord chat.

## Start

Install the validated plugin ZIP through YourBot's developer publishing and Marketplace workflow, grant the requested permissions, then run **`/codhub`**. The ZIP places `manifest.json` and `__main__.py` at its root. Full installation and development instructions are in the [public repository](https://github.com/ember-kace/yourbot-plugin-codhub).

The home card offers **Import code**, **My builds**, **Compare**, **Weapons**, **Item catalog**, **Meta builds** and **Game guide**. Item catalog opens a private category picker for native items and cosmetics; `/codcatalog` also searches by name or ID. Imported builds, comparisons and catalog browsing stay private. **Post to channel**, **Post PNG to channel**, **Post graphs to channel** and item cards’ **Post card to channel** deliberately publish in the current channel. Shared cards open each person’s own private browsing controls.

If YourBot rejects the popup before it opens, import directly with `/codbuild code:A01-42J19-BU11`. A live modal request has returned an unexplained Discord HTTP 400. Version 0.1.4 adds specific recovery and safe diagnostics; the popup rejection itself remains unresolved. See [troubleshooting](https://github.com/ember-kace/yourbot-plugin-codhub/blob/main/docs/USAGE.md#installation-and-troubleshooting).

| Command | Use |
|---|---|
| `/codhub` | Open the shared home card and private tools. |
| `/codbuild code:A01-42J19-BU11` | Decode an MW4 build into a private card. |
| `/codcatalog query:gold category:camo` | Browse and share native items and cosmetics. |
| `/codweapon query:Kastov` | Find a named weapon. |
| `/codattachment query:grip weapon:A01` | Find an attachment for a weapon. |
| `/codsaved` | List, open, rename or delete your saved builds. |
| `/codcompare left:A01 right:A05` | Compare weapons or builds; view available charts and full measurement sources. |
| `/codmeta` | Browse attributed recommendations by mode and weapon type. |
| `/codguide category:maps` | Browse packaged native map and challenge references. |
| `/codreference query:Shipment` | Search dated, attributed wiki references. |

## Behavior and data

Build decoding, saved builds, charts and PNG exports use bundled data. Live meta and wiki requests use YourBot's HTTP proxy, limited to `metaradar.gg` and `callofduty.fandom.com`. The plugin requests interaction responses, per-server KV storage, message sending and the proxy. It does not listen to ordinary messages or fetch player statistics.

Saved builds are scoped to their owner and server, with an advisory 50-build limit. Preview controls expire after seven days; saved records persist independently. Concurrent cross-worker saves may exceed the advisory quota because the platform KV API has no compare-and-swap operation.

The MW4 snapshot is dated 2026-11-11. The item census retains 8,029 records in 31 categories; 6,720 have verified English references available as cards. Tracking, unassigned and internal records remain counted separately. The code dictionary has 2,401 active attachment bindings and retains the exact approved technical-caption policies. Source presence does not establish live eligibility, store availability or account unlocks. Older saved codes carry a verification reminder because game updates can change attachment mappings.

Native artwork covers all 35 main-browser weapons: 30 reviewed model references and five catalog icons. Four references say **Lens shaders simplified**; CSG35 says **Native folded reference**. Three Kastov codes have their verified primary attachment-layout previews; other codes use labeled weapon references. The 38 bundled weapon/build WebPs total 3.52 MiB and also appear on [GitHub Pages](https://ember-kace.github.io/yourbot-plugin-codhub/artwork/). The larger native item-artwork library is hosted there and referenced through a packaged index. Camo tiles do not apply camos to a gun, and arbitrary attachment combinations are not rendered.

Five reviewed automatic base weapons have theoretical Multiplayer DPS charts with separately dated source inputs. Modified-build DPS, other modes' damage, recoil and aiming sway remain unavailable until matching measurements are reviewed. Meta feeds and wiki articles are attributed references rather than a complete structured game database.

No project license is granted. Included font and identifier notices retain their respective third-party licenses. See the public repository's [usage guide](https://github.com/ember-kace/yourbot-plugin-codhub/blob/main/docs/USAGE.md), [data notes](https://github.com/ember-kace/yourbot-plugin-codhub/blob/main/docs/DATA.md), and [third-party notices](https://github.com/ember-kace/yourbot-plugin-codhub/blob/main/THIRD_PARTY_NOTICES.md).
