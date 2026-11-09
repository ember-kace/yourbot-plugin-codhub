"""Discord cards and an original text-first PNG layout."""
from io import BytesIO
from .urls import percent_encode, split_https

from .artwork import decorate_embed


COLOR = 0x9DF0B4
WARNING = 0xE8B66C
GAME_NAMES = {"mw4": "Modern Warfare 4", "bo7": "Black Ops 7", "warzone": "Warzone"}


def _text(value, maximum=1024):
    return str(value or "").replace("\x00", "")[:maximum]


def _safe(value, maximum=180):
    value = _text(value, maximum)
    for char in ("\\", "*", "_", "`", "~", "|", "[", "]", "(", ")"):
        value = value.replace(char, "\\" + char)
    return value.replace("@", "＠")[:maximum]


def _link(label, url):
    if not isinstance(url, str) or any(ord(c) < 32 or ord(c) == 127 for c in url):
        return _safe(label)
    try:
        parts = split_https(url)
        port = parts.port
    except ValueError:
        return _safe(label)
    if (parts.scheme != "https" or not parts.hostname or parts.username is not None or parts.password is not None
            or any(c.isspace() for c in parts.netloc) or port not in (None, 443)):
        return _safe(label)
    # Encode Markdown delimiters without changing the destination or cutting a URL.
    unsafe = "()<>[]\\\"`"
    destination = "".join(percent_encode(c) if c in unsafe or c.isspace() else c for c in url)
    return f"[{_safe(label)}]({destination})"


def _bounded_text(text, maximum):
    """Shorten prose visibly; callers must keep complete links outside this helper."""
    text = str(text or "").replace("\x00", "")
    if len(text) <= maximum:
        return text
    return text[:max(0, maximum - 1)].rstrip("\\ ") + "…" if maximum > 0 else ""


def _source_field(excerpt, source_suffix, maximum=1024):
    """Reserve a complete attribution/revision suffix, or omit the whole field."""
    if len(source_suffix) > maximum:
        return None
    if not excerpt:
        return source_suffix
    room = maximum - len(source_suffix) - 1
    if room <= 0:
        return source_suffix
    return _bounded_text(excerpt, room) + "\n" + source_suffix


def build_embed(build):
    weapon = build["weapon"]
    items = build.get("attachments", [])
    ordinary = sum(a["slot"] != "apex" for a in items)
    apex = any(a["slot"] == "apex" for a in items)
    description = f"**{GAME_NAMES.get(build['game'], build['game'])}** · {ordinary} selected attachments"
    if build.get("title") and build["title"] != weapon["name"]:
        description = f"**{_safe(weapon['name'], 180)}**\n" + description
    if apex:
        description += " + Apex"
    fields = [{"name": "Build code", "value": f"```{_text(build['code'], 160)}```", "inline": False}]
    for attachment in items:
        fields.append({"name": _text(attachment["slot_label"], 80),
                       "value": _safe(attachment["name"], 180), "inline": True})
    if not items:
        fields.append({"name": "Attachments", "value": "Base weapon; no attachments selected.", "inline": False})
    if build.get("unknowns"):
        fields.append({"name": "Unresolved data", "value": _safe("\n".join(build["unknowns"]), 850), "inline": False})
    if build.get("notes"):
        fields.append({"name": "Notes", "value": _safe("\n".join(build["notes"]), 850), "inline": False})
    if build.get("label_status") == "fallback":
        description += "\nSome names are unavailable and are marked with their native IDs."
    footer = f"COD Hub · Catalog {build.get('snapshot_date', 'unknown date')}"
    footer += " · Verified English names" if build.get("label_status") != "fallback" else " · Partial name coverage"
    return decorate_embed({"title": _text(build.get("title") or weapon["name"], 180), "description": description,
            "color": WARNING if build.get("identity_status") == "partial" else COLOR,
            "fields": fields[:24], "footer": {"text": footer}}, weapon)


def weapon_embed(weapon):
    fields = []
    if weapon.get("prefix"):
        fields.append({"name": "Native prefix", "value": _text(weapon["prefix"]), "inline": True})
    if weapon.get("class"):
        fields.append({"name": "Class", "value": _safe(weapon["class"]), "inline": True})
    stats = weapon.get("base_stats") or weapon.get("stats") or {}
    values = stats.get("values", {})
    labels = {"rpm": ("Fire rate", " RPM"), "magazine": ("Base magazine", " rounds"),
              "reserve": ("Base reserve", " rounds"), "weaponLevels": ("Weapon levels", ""),
              "unlockLevel": ("Player unlock level", ""), "caliber": ("Caliber", "")}
    for key, (label, suffix) in labels.items():
        if key in values and values[key] is not None:
            fields.append({"name": label, "value": _safe(str(values[key]) + suffix), "inline": True})
    description = GAME_NAMES.get(weapon.get("game"), weapon.get("game", "MW4"))
    if values:
        description += f"\nBase reference dated **{stats.get('data_date', 'unknown')}**; attachment effects and later balance changes are not included."
    else:
        description += "\nDetailed balance values are not verified in this catalog snapshot."
    if not weapon.get("native_supported", False):
        description += "\nNative sharing is not defined for this weapon in the current catalog."
    if weapon.get("metadata_locked"):
        description += "\nThe source catalog marks this entry as locked."
    return decorate_embed({"title": _text(weapon["name"], 180), "description": description,
            "color": COLOR, "fields": fields,
            "footer": {"text": f"COD Hub · Catalog {weapon.get('snapshot_date', 'unknown')}"}}, weapon)


def attachment_embed(item):
    configured = item.get("configured_for", item.get("compatible_weapons", []))
    rows = []
    for entry in configured[:8]:
        rows.append(f"{_safe(entry.get('name') or entry.get('prefix'))} · `{_text(entry.get('prefix'), 3)}`"
                    + (f" · ID {entry['index']}" if "index" in entry else ""))
    if len(configured) > 8:
        rows.append(f"… and {len(configured) - 8} more catalog entries")
    fields = []
    if item.get("slot_label"):
        fields.append({"name": "Category", "value": _safe(item["slot_label"]), "inline": True})
    if rows:
        fields.append({"name": "Configured weapon entries", "value": _text("\n".join(rows), 1000), "inline": False})
    description = "Attachment reference; current loadout restrictions and unlocks are checked in-game."
    if item.get("quality") in {"internal", "unknown", "unresolved"}:
        description += "\nAn exact English name is not available for this entry."
    return {"title": _text(item["name"], 180), "description": description,
            "color": COLOR, "fields": fields,
            "footer": {"text": f"COD Hub · Catalog {item.get('snapshot_date', 'unknown')} · Source labels"}}


def meta_embed(payload):
    game = GAME_NAMES.get(payload.get("game"), payload.get("game", "Call of Duty"))
    attribution = payload.get("attribution") or {"text": "MetaRadar", "url": "https://metaradar.gg/"}
    credit = _link(attribution.get("text", "MetaRadar"), attribution.get("url"))
    description = f"{credit} · {game}"
    if payload.get("updated_at"):
        description += f"\nSource updated {_safe(payload['updated_at'], 80)}"
    if payload.get("warning"):
        description += "\n" + _safe(payload["warning"], 500)
    source_url = None
    if len(description) > 3800 and credit.startswith("["):
        # An expanded Markdown URL may fit the title URL but not prose. Keep it
        # complete, retain provider credit, and say where the source opens.
        source_url = attribution["url"]
        description = f"{_safe(attribution.get('text', 'MetaRadar'))} · {game}\nOpen this card's title for the complete provider source."
        if payload.get("updated_at"):
            description += "\nSource updated " + _safe(payload["updated_at"], 80)
        if payload.get("warning"):
            description += "\n" + _safe(payload["warning"], 500)
    if not payload.get("available"):
        result = {"title": "Meta feed unavailable", "description": description, "color": WARNING,
                "footer": {"text": "COD Hub · MetaRadar · Saved builds remain available"}}
        if source_url:
            result["url"] = source_url
        return result
    title = "Meta snapshot" if not payload.get("stale") else "Saved meta snapshot"
    footer = "COD Hub · MetaRadar · Cached for at least one hour"
    weapons = payload.get("weapons", [])
    fields, shortened = [], False
    # Reserve space for truthful omission counts before fitting complete row links.
    remaining = 6000 - len(title) - len(description) - len(footer) - 220
    for weapon in weapons[:5]:
        rows = []
        source = _link(weapon.get("name", "Weapon"), weapon.get("url"))
        if weapon.get("tier"):
            rows.append("Tier: " + _bounded_text(_safe(weapon['tier'], 160), 30))
        label = weapon.get("build_label")
        if label:
            rows.append(_bounded_text(_safe(label, 320), 100))
        attachments = weapon.get("attachments", [])
        for attachment in attachments[:8]:
            if isinstance(attachment, dict):
                rows.append(_bounded_text(_safe(attachment.get('slot'), 160), 40) + ": "
                            + _bounded_text(_safe(attachment.get('name'), 400), 100))
        if len(attachments) > 8:
            rows.append(f"… {len(attachments) - 8} more attachments at the source")
        if weapon.get("code"):
            source += f"\n`{_text(weapon['code'], 128)}`"
        name = f"#{weapon.get('rank') or len(fields) + 1}"
        maximum = min(1024, remaining - len(name))
        value = _source_field("", source, maximum)
        if value is None:
            continue
        selected = []
        room = maximum - len(source) - 1
        for row in rows:
            candidate = "\n".join(selected + [row])
            if len(candidate) > room:
                shortened = True
                break
            selected.append(row)
        value = _source_field("\n".join(selected), source, maximum)
        shortened = shortened or any("…" in row for row in rows)
        fields.append({"name": name, "value": value, "inline": False})
        remaining -= len(name) + len(value)
    omitted = len(weapons) - len(fields)
    if omitted:
        description += f"\nShowing {len(fields)} of {len(weapons)} recommendations; {omitted} omitted from this card. Open the provider source for full details."
    if shortened:
        description += "\nSome attachment details were shortened or omitted to fit this card."
    result = {"title": title,
            "description": description, "color": COLOR if not payload.get("stale") else WARNING,
            "fields": fields, "footer": {"text": footer}}
    if source_url:
        result["url"] = source_url
    return result


def reference_embed(payload):
    if not payload.get("available"):
        return {"title": "Reference unavailable", "description": _text(payload.get("warning") or "The reference source could not be reached."),
                "color": WARNING}
    attribution = payload.get("attribution", {})
    credit = _link(attribution.get("text", "Call of Duty Wiki contributors"), attribution.get("url"))
    license_link = _link(attribution.get("license_name", "CC-BY-SA"), attribution.get("license_url"))
    description = f"Text: {credit} · {license_link}"
    if payload.get("adaptation"):
        description += "\n" + _safe(payload["adaptation"], 200)
    if payload.get("coverage"):
        description += "\n" + _safe(payload["coverage"], 300)
    if payload.get("warning"):
        description += "\n" + _safe(payload["warning"], 300)
    fields, shortened = [], False
    title = "Call of Duty reference"
    footer = "COD Hub · Call of Duty Wiki · Text under CC BY-SA; check source dates"
    items = payload.get("items", [])
    remaining = 6000 - len(title) - len(description) - len(footer) - 220
    for item in items[:4]:
        source = _link("Source and revision", item.get("url"))
        if item.get("timestamp"):
            source += " · " + _safe(item["timestamp"][:10], 10)
        name = _bounded_text(_text(item.get("title"), 250), 120)
        excerpt = _safe(item.get("extract"), 1800)
        value = _source_field(excerpt, source, min(1024, remaining - len(name)))
        if value is None:
            continue
        shortened = shortened or value != (excerpt + "\n" if excerpt else "") + source
        fields.append({"name": name, "value": value, "inline": False})
        remaining -= len(name) + len(value)
    omitted = len(items) - len(fields)
    if omitted:
        description += f"\nShowing {len(fields)} of {len(items)} references; {omitted} omitted from this card. Open the wiki source for full results."
    if shortened:
        description += "\nExcerpts were shortened further to keep complete revision links."
    return {"title": title, "description": description, "color": COLOR, "fields": fields,
            "footer": {"text": footer}}


def render_build_png(build):
    # Pillow's embedded default font avoids bundling proprietary fonts or game art.
    from PIL import Image, ImageDraw, ImageFont

    items = build.get("attachments", [])
    columns = 3 if len(items) > 10 else 2
    rows = max(1, (len(items) + columns - 1) // columns)
    width, gap, margin, cell_height = 1100, 16, 48, 112
    height = 300 + rows * (cell_height + gap) + 110
    image = Image.new("RGB", (width, height), "#0b111a")
    draw = ImageDraw.Draw(image)
    fonts = {size: ImageFont.load_default(size=size) for size in (14, 16, 18, 21, 24, 38)}

    def fit(text, size, maximum):
        text = _text(text, 240).replace("\n", " ")
        if draw.textlength(text, font=fonts[size]) <= maximum:
            return text
        ellipsis = "…"
        if draw.textlength(ellipsis, font=fonts[size]) > maximum:
            return ""
        text = text.rstrip(ellipsis)
        while text and draw.textlength(text + ellipsis, font=fonts[size]) > maximum:
            text = text[:-1]
        return text.rstrip() + ellipsis

    def wrap(text, size, maximum, lines=2):
        words, result, current = _text(text, 240).split(), [], ""
        for word in words:
            candidate = (current + " " + word).strip()
            if current and draw.textlength(candidate, font=fonts[size]) > maximum:
                result.append(current)
                current = word
            else:
                current = candidate
        if current:
            result.append(current)
        if len(result) > lines:
            result = result[:lines]
            result[-1] += "…"
        return [fit(line, size, maximum) for line in result] or [""]

    draw.rectangle((0, 0, width, 7), fill="#9df0b4")
    draw.text((margin, 29), "COD HUB", font=fonts[24], fill="#9df0b4")
    game = {"mw4": "MW4", "bo7": "BO7", "warzone": "WARZONE"}.get(build.get("game"), "COD")
    draw.rounded_rectangle((width - 160, 28, width - margin, 65), 12, fill="#21372f")
    draw.text((width - 140, 37), game, font=fonts[18], fill="#c6f8d7")
    title = build.get("title") or build["weapon"]["name"]
    draw.text((margin, 85), fit(title, 38, width - 2 * margin), font=fonts[38], fill="#f1f5f8")
    ordinary = sum(a["slot"] != "apex" for a in items)
    subtitle = f"{ordinary} SELECTED ATTACHMENTS" + (" + APEX" if any(a["slot"] == "apex" for a in items) else "")
    if title != build["weapon"]["name"]:
        subtitle = build["weapon"]["name"] + " · " + subtitle
    draw.text((margin, 137), fit(subtitle, 16, width - 2 * margin), font=fonts[16], fill="#99abbc")
    draw.rounded_rectangle((margin, 178, width - margin, 242), 12, fill="#16242d", outline="#304650", width=1)
    draw.text((margin + 22, 197), _text(build["code"], 120), font=fonts[24], fill="#c6f8d7")
    draw.text((margin, 268), "BUILD DETAILS", font=fonts[16], fill="#8da1b4")
    cell_width = (width - 2 * margin - gap * (columns - 1)) // columns
    for n, item in enumerate(items):
        x = margin + (n % columns) * (cell_width + gap)
        y = 300 + (n // columns) * (cell_height + gap)
        fallback = item.get("quality") in {"internal", "unknown", "unresolved"}
        accent = "#e8b66c" if fallback or item["slot"] == "apex" else "#9df0b4"
        draw.rounded_rectangle((x, y, x + cell_width, y + cell_height), 12, fill="#141f2b", outline="#293849", width=1)
        draw.text((x + 18, y + 15), _text(item["slot_label"], 50).upper(), font=fonts[14], fill=accent)
        size = 18 if columns == 3 else 21
        for line, text in enumerate(wrap(item["name"], size, cell_width - 36)):
            draw.text((x + 18, y + 43 + line * 25), text, font=fonts[size], fill="#e9eff5")
    if not items:
        draw.text((margin, 324), "Base weapon; no attachments selected.", font=fonts[24], fill="#d3dee9")
    footer_y = height - 80
    draw.line((margin, footer_y - 15, width - margin, footer_y - 15), fill="#293849", width=1)
    note = "Some data is unresolved. Original code preserved." if build.get("unknowns") else "Import the code in the selected game; unlocks and mode restrictions still apply."
    draw.text((margin, footer_y), fit(note, 16, width - 2 * margin), font=fonts[16], fill="#c7a974" if build.get("unknowns") else "#9bafc0")
    caption = f"Catalog {build.get('snapshot_date', 'unknown')}  |  Names: verified English catalog"
    if build.get("label_status") == "fallback":
        caption += "; untranslated entries are marked"
    draw.text((margin, footer_y + 30), fit(caption, 14, width - 2 * margin), font=fonts[14], fill="#73899d")
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=False)
    image.close()
    return buffer.getvalue()
