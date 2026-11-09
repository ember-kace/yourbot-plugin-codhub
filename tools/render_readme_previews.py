"""Render public documentation examples from the real plugin, entirely offline.

The hub is a local illustration of an SDK MockContext response, not a Discord
screenshot. Build and comparison images use the plugin's actual PNG renderers.
Only synthetic interaction identifiers are used. No third-party art is fetched.
"""
from __future__ import annotations

import argparse
from io import BytesIO
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugin"
sys.path.insert(0, str(PLUGIN))


def _write_png(destination, body):
    """Keep pixels only: no EXIF, comments, timestamps or source-path metadata."""
    from PIL import Image

    with Image.open(BytesIO(body)) as source:
        source.load()
        pixels = source.convert("RGBA")
        clean = Image.new("RGB", source.size, "#0b111a")
        clean.paste(pixels, mask=pixels.getchannel("A"))
        clean.save(destination, format="PNG", optimize=False)
        clean.close()
        pixels.close()


def _hub_png(payload):
    """Lay out actual embed text and SDK controls in a labelled local preview."""
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (1200, 970), "#0b111a")
    draw = ImageDraw.Draw(image)
    font_path = PLUGIN / "cod_hub/fonts/font.ttf"
    fonts = {size: ImageFont.truetype(str(font_path), size=size)
             for size in (18, 20, 22, 24, 30, 42)}
    ink, muted, accent = "#edf3fa", "#a4b5c8", "#a9f1c4"

    def text(x, y, value, size=22, fill=ink):
        draw.text((x, y), value, font=fonts[size], fill=fill)

    def wrapped(x, y, value, width, size=22, fill=ink, gap=8):
        line_height = size + gap
        for paragraph in value.split("\n"):
            if not paragraph:
                y += line_height // 2
                continue
            current = ""
            for word in paragraph.split():
                candidate = (current + " " + word).strip()
                if current and draw.textlength(candidate, font=fonts[size]) > width:
                    text(x, y, current, size, fill)
                    y += line_height
                    current = word
                else:
                    current = candidate
            if current:
                text(x, y, current, size, fill)
                y += line_height
        return y

    embed = payload["embeds"][0]
    draw.rounded_rectangle((56, 42, 1144, 97), radius=14, fill="#142230")
    text(78, 57, "COD HUB / CHAT TOOLS", 20, accent)
    text(812, 57, "LOCAL SDK PREVIEW", 20, muted)
    draw.rounded_rectangle((56, 126, 1144, 760), radius=18,
                           fill="#131f2c", outline="#293c50", width=2)
    draw.rounded_rectangle((56, 126, 64, 760), radius=4, fill=accent)
    text(92, 155, embed["title"], 42)
    y = wrapped(92, 218, embed["description"], 980, 24, muted)
    y += 19
    for field in embed.get("fields", []):
        text(92, y, field["name"], 24, ink)
        y = wrapped(92, y + 34, field["value"], 980, 22, muted) + 19
    text(92, 713, embed.get("footer", {}).get("text", ""), 20, accent)

    controls = [row.to_dict() if hasattr(row, "to_dict") else row
                for row in payload.get("components", [])]
    y = 789
    for row in controls:
        x = 56
        for control in row["components"]:
            if control["type"] == 2:
                label = control["label"]
                width = max(170, int(draw.textlength(label, font=fonts[22])) + 48)
                primary = control.get("style") == 1
                draw.rounded_rectangle((x, y, x + width, y + 57), radius=10,
                                       fill="#9bdcb9" if primary else "#24384b")
                text(x + 24, y + 15, label, 22, "#12241d" if primary else ink)
                x += width + 14
            elif control["type"] == 3:
                draw.rounded_rectangle((56, y, 1144, y + 55), radius=10,
                                       fill="#172735", outline="#344b62", width=1)
                text(80, y + 14, control.get("placeholder", "Choose an option"), 22, muted)
                draw.line((1101, y + 24, 1109, y + 32, 1117, y + 24), fill=muted, width=2)
        y += 71
    text(56, 937, "Actual /codhub response. Local layout; controls are illustrated, not interactive.", 18, muted)
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=False)
    image.close()
    return buffer.getvalue()


def render(output):
    from yourbot_sdk.testing import MockClock, MockContext, make_event
    from cod_hub import cards, catalog, comparison, comparison_charts, hub, telemetry

    manifest = json.loads((PLUGIN / "manifest.json").read_text(encoding="utf-8"))
    context = MockContext(server_id="1000", plugin_id=manifest["id"],
                          capabilities=manifest["capabilities_required"],
                          clock=MockClock(start=1_700_000_000))
    event = make_event("interaction_create", interaction_type=2,
                       user_id="1001", channel_id="1002")
    hub.handle_home(context, event)
    home = context.interaction.followups[-1]
    if home["embeds"][0]["title"] != "COD Hub" or context.messages_sent:
        raise ValueError("The local hub response was not the expected home card.")

    build = dict(catalog.resolve_build("A01-42J19-BU11"))
    build["title"] = "Range setup"
    result = comparison.compare("A01", "A05", mode="multiplayer",
                                profiles=telemetry.profiles_for("multiplayer"),
                                hit_location="base_profile")
    bodies = {"hub.png": _hub_png(home),
              "build.png": cards.render_build_png(build),
              "compare.png": comparison_charts.render_chart(result, "dps")}
    output.mkdir(parents=True, exist_ok=True)
    for name, body in bodies.items():
        _write_png(output / name, body)
    return sorted(bodies)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/images",
                        help="Directory for hub.png, build.png and compare.png")
    args = parser.parse_args(argv)
    names = render(args.output)
    print("Rendered offline documentation previews: " + ", ".join(names))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
