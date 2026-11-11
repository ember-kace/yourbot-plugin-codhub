"""Render the public weapon gallery from reviewed plugin artwork metadata."""
from collections import Counter
import html
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "plugin")]
from cod_hub import native_artwork
from tools.native_artwork_release import evaluate_release


def card(record, *, code=None):
    art = native_artwork.get_art(record, build_code=code)
    if art is None:
        raise ValueError("A gallery entry has no reviewed bundled image.")
    title = html.escape(record["name"])
    label = html.escape(code or record.get("prefix") or "Reference weapon")
    caption, scope = html.escape(art["caption"]), html.escape(art["scope_text"])
    return (f'<article><div class="preview"><img src="v1/{record["filename"]}" width="{record["width"]}" '
            f'height="{record["height"]}" loading="lazy" alt="{title}"></div><h3>{title}</h3>'
            f'<p><code>{label}</code> · {caption}</p><p class="muted">{scope}</p></article>')


def main():
    review = evaluate_release()
    if not review["ready"]:
        raise ValueError(review["issues"])
    document = json.loads((ROOT / "plugin/cod_hub/data/native-artwork.json").read_bytes())
    bases, builds = document["base_images"], document["build_images"]
    kinds = Counter(record.get("preview_kind", "primary_components") for record in bases.values())
    page = '''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>COD Hub · Weapon references</title><meta name="description" content="Native weapon references used by COD Hub's Discord cards.">
<link rel="icon" href="data:,">
<style>
:root{color-scheme:dark;font-family:system-ui,sans-serif;background:#0b111a;color:#e9eff5}body{max-width:1120px;margin:auto;padding:32px 20px 56px}a{color:#9df0b4}header{max-width:850px}h1{font-size:clamp(2rem,6vw,3rem);margin:12px 0}h2{margin-top:40px}h3{margin:12px 16px 4px}p{line-height:1.6}.muted{color:#a4b5c8}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:18px}article{border:1px solid #293849;border-radius:16px;overflow:hidden;background:#141f2b}article p{margin:4px 16px 12px}.preview{height:240px;background:radial-gradient(ellipse,#293849 0,#111b29 75%);display:flex;align-items:center;justify-content:center;overflow:hidden}.preview img{width:100%;height:100%;min-width:0;min-height:0;object-fit:contain}code{overflow-wrap:anywhere}footer{margin-top:44px;border-top:1px solid #293849;padding-top:20px;font-size:.9rem}
</style></head><body><header><p><a href="https://github.com/ember-kace/yourbot-plugin-codhub">COD Hub repository</a> · <a href="items/">Browse the item catalog</a></p><h1>Your loadout, in view.</h1>'''
    page += (f'<p>{len(bases)} weapon references: {len(bases) - kinds["native_item_icon"]} reviewed model views and '
             f'{kinds["native_item_icon"]} native catalog icons, plus {len(builds)} verified build layouts. '
             'The same transparent lossless WebPs are bundled for PNG exports.</p>')
    page += ('<p class="muted">Each card states its scope. Static models do not reproduce full in-game shaders, '
             'camos, charms or arbitrary selected attachments. Five weapons use native icons while their model '
             'assembly or pose remains unverified. CSG35 shows its source-defined folded reference.</p></header>')
    page += '<section><h2>Verified build layouts</h2><div class="grid">'
    page += '\n'.join(card(record, code=code) for code, record in sorted(builds.items()))
    page += '</div></section><section><h2>Weapon references</h2><div class="grid">'
    page += '\n'.join(card(record) for record in sorted(bases.values(), key=lambda row: row["name"].casefold()))
    page += ('</div></section><footer class="muted">Unofficial community previews. Call of Duty artwork, models, '
             'textures and marks belong to Activision and their respective owners. No license to those resources '
             'is granted. <a href="https://github.com/ember-kace/yourbot-plugin-codhub/blob/main/THIRD_PARTY_NOTICES.md">'
             'Third-party notices</a>.</footer></body></html>\n')
    (ROOT / "docs/artwork/index.html").write_text(page, encoding="utf8")
    print(json.dumps({"weapon_references": len(bases), "build_layouts": len(builds), "scopes": dict(kinds)}))


if __name__ == "__main__":
    main()
