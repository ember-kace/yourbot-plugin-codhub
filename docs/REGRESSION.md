# COD Hub 0.2.0 regression

Checked November 11, 2026, using YourBot SDK 0.10.1.

| Check | Result |
|---|---|
| Python suite | 375 tests, two platform-dependent skips; no failures |
| Real SDK transport with a local simulated host | 67 events across dedicated and pooled runs; no failures |
| Native code tables | 2,401 active bindings, 31 prefixes, 35 browser weapons; all three user golden codes retained |
| Item census and independent English witnesses | 8,029 records retained; all 6,720 named references checked against 6,872 current source contexts |
| Native guide | 683 source references; 587 named and 96 held |
| Weapon images | All 38 bundled files and matching hosted copies verified, including all 35 browser weapons |
| Item artwork | All 2,962 hosted files verified by content hash, decoded RGBA pixels and alpha; 2,980 native identities |
| Gallery browser review | Desktop and 390-pixel mobile layouts, filters, empty search, image loading, scope labels and title separation passed |
| Public-tree and artifact checks | No rejected host paths, secret patterns, source containers, native code or disallowed Python imports |
| SDK artifact validation | No errors or warnings |

The current source hashes were rechecked after extraction using read-only handles. Windows-generated public text was normalized to the repository’s LF policy before the final proof hashes were calculated. Historical name evidence remains available without allowing rejected aliases to select another attachment.

The item census is complete for its installed source table. It is **not a completely named global collectible catalog**: 1,238 records remain held, and 71 remain internal. None of the held identities belongs to the current code dictionary. See [coverage](../metadata/item-catalog-coverage.json) and [data limits](DATA.md).

Images distinguish 30 model references, five catalog-icon fallbacks and three exact build layouts. Four model references simplify lens shaders; CSG35 shows its folded reference. Arbitrary builds, applied camos/charms and full in-game appearance are not reproduced.

The SDK host is simulated. The previously observed live Discord popup HTTP 400 remains unresolved; `/codbuild` is the direct import alternative. These checks do not claim a live Discord deployment or predict YourBot’s platform security score.

Reproduce the local checks with:

```sh
python tools/dev.py test
python tools/dev.py validate
python tools/stage_plugin_transport.py --report dist/transport.json
python tools/dev.py package
```
