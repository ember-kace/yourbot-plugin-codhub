# COD Hub

![Regression](https://github.com/ember-kace/yourbot-plugin-codhub/actions/workflows/ci.yml/badge.svg)
![YourBot SDK 0.10.1](https://img.shields.io/badge/YourBot_SDK-0.10.1-7057ff)
![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776ab)
![MW4 build tools](https://img.shields.io/badge/Build_tools-MW4-cba45c)

COD Hub brings Call of Duty build codes, weapon browsing, comparisons and saved loadouts into Discord through YourBot. Start with `/codhub`, then use the cards and menus or jump directly to a slash command.

![COD Hub home card](docs/images/hub.png)

## What it does

- Import supported native MW4 build codes into private cards with named attachments and copyable codes.
- Explore weapons and their attachments; save, rename and delete your own builds in each server.
- Share a build card or text-based PNG to the current channel when you choose to post it.
- Compare weapons, builds, or one of each. Switch between overview, DPS, recoil, aiming sway and measurement sources.
- Browse attributed Multiplayer and Warzone meta recommendations by weapon type. DMZ currently links to an external dedicated source.
- Search dated COD Wiki references for maps, operators, camos, challenges, prestige, perks and equipment.

Build cards display transparent base-weapon artwork where verified artwork is available. Images illustrate the base weapon; attachments and camo are not rendered onto it. PNG build exports contain text rather than third-party weapon artwork.

| Build card | DPS comparison |
|---|---|
| ![Imported build example](docs/images/build.png) | ![Weapon comparison chart](docs/images/compare.png) |

See [the usage guide](docs/USAGE.md) for all eight commands, sharing controls and data limits. These are locally rendered demonstrations, not screenshots of a live Discord installation.

## Install through YourBot

1. Download `COD-Hub-0.1.0.zip` from [GitHub Releases](https://github.com/ember-kace/yourbot-plugin-codhub/releases/latest), or build it using the commands below. The ZIP contains `manifest.json` and `__main__.py` at its root.
2. To publish your own installation package, sign in to the [YourBot Dev Portal](https://yourbot.gg/dev), use the plugin ID assigned there, upload the validated ZIP and follow the review process. Upload the ZIP contents as built; do not upload this whole repository. [Official publishing guide](https://yourbot.gg/docs/developers/production/publish).
3. Once a version is available to install, use the Marketplace in your custom-bot server's YourBot dashboard, review its permissions and domains, and allow its commands through Command Access. Then run `/codhub` in Discord. [Official installation guidance](https://yourbot.gg/docs/platform/marketplace-plugins).

This repository uses a `plugin/` source directory. The documented artifact workflow is ZIP upload; the public YourBot guidance does not establish GitHub-pull subdirectory support. A public GitHub repository does not itself publish or install a YourBot plugin.

## Develop and package

Use Python 3.10 or newer. Create and activate a virtual environment, then install the pinned development dependencies:

```sh
python -m venv .venv
# Activate .venv using your shell's usual command.
python -m pip install -r requirements-dev.txt
python tools/dev.py test
python tools/dev.py validate
python tools/dev.py package
```

The package command writes `dist/COD-Hub-0.1.0.zip` from an explicit runtime file list and validates it with YourBot SDK 0.10.1. The SDK also supplies `yourbot validate --path plugin` and `yourbot doctor --path plugin`. Review the [current YourBot developer documentation](https://yourbot.gg/docs/developers) before changing platform APIs or dependencies.

Optional: `python tools/dev.py preview` generates local card demonstrations. No game installation, player credentials or Discord bot token is needed for the offline tests and build tools. Live YourBot/Discord installation testing remains pending.

## Data coverage and accuracy

The November 9, 2026 snapshot retains 1,264 catalog assets and 35 weapon-reference records: 1,216 verified names plus 83 separately marked internal or technical descriptions. Descriptions preserve otherwise unnamed identities; they are not canonical game names and are excluded from normal player-item searches. The player-facing weapon browser has 35 named weapons, with approved remote artwork for 27.

Reviewed theoretical DPS currently covers five automatic **base weapons in Multiplayer**: Kastov 762, M4, Patriot XMR, ISO Nightshade and Type 73. Damage is dated November 5, 2026; RPM is from the October 19 launch reference. The source's base hit region is unspecified. Modified-build DPS, DMZ/Warzone damage, recoil and aiming-sway measurements remain unavailable until comparable measurements are reviewed. No performance curve is inferred from UI bars.

Meta recommendations are provider opinions and can change. Wiki results are attributed article references, not a complete structured catalog or a guarantee of current game facts. COD Hub does not retrieve player statistics, match history or account unlocks.

## Permissions and privacy

The plugin requests `interaction:respond`, `storage:kv`, `discord:send_message` and `proxy:http`. HTTP requests are limited to `metaradar.gg` and `callofduty.fandom.com`. It does not subscribe to ordinary channel messages or request moderation permissions.

Saved builds contain your Discord user identifier, build code, title and creation time in YourBot's server-scoped plugin storage. Previews expire after seven days; saved builds persist until deleted. Browsing and import previews are private. **Share card**, **Post PNG** and **Post graphs** deliberately publish to the current channel. Reference search terms are sent to COD Wiki through YourBot's proxy; weapon images are loaded by Discord from the linked provider.

## Sources and rights

COD Hub is an unofficial community project, unaffiliated with Activision, Call of Duty or YourBot. Call of Duty and related names and artwork belong to their respective owners. Cards preserve factual-source links and dates, MetaRadar attribution, and COD Wiki revision/contributor/license information. Third-party artwork remains remotely linked.

No project license granted. Third-party licenses/notices apply to their respective resources. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
