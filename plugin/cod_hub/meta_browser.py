"""Attributed mode/class browsing without substituting Multiplayer for DMZ."""
from copy import deepcopy
import hashlib
import json
import re

from yourbot_sdk import ActionRow, Button, SelectMenu, SelectOption

from . import meta
from .cards import COLOR, WARNING, _safe, _link
from .store import owner_id

NO_MENTIONS = {"parse": []}
PAGE_SIZE = 5
MODE_LABELS = {"multiplayer": "Multiplayer", "dmz": "DMZ", "warzone": "Warzone"}
TYPE_LABELS = {"all": "All weapon types", "ar": "Assault rifles", "br": "Battle rifles",
               "smg": "SMGs", "lmg": "LMGs", "sg": "Shotguns", "sr": "Sniper rifles",
               "mr": "Marksman rifles", "pistols": "Pistols", "launchers": "Launchers", "melee": "Melee"}
MODE_ROUTES = {
    "multiplayer": {"game": "mw4", "scope": "Modern Warfare 4 Multiplayer",
                    "source_url": "https://metaradar.gg/modernwarfare4/meta",
                    "coverage_source": "https://metaradar.gg/modernwarfare4/dmz/loadouts"},
    "warzone": {"game": "warzone", "scope": "Warzone Battle Royale",
                "source_url": "https://metaradar.gg/warzone/meta",
                "coverage_source": "https://metaradar.gg/warzone/meta"},
}
DMZ_SOURCE = "https://dmzradar.com/meta.html"
_CID = re.compile(r"chm:(page|mode|type|pick):([0-9]{1,22}):(multiplayer|dmz|warzone):([a-z]+):([1-9][0-9]{0,2})\Z")
_MODES = {"mp": "multiplayer", "multiplayer": "multiplayer", "dmz": "dmz", "warzone": "warzone", "wz": "warzone"}
_TYPE_ALIASES = {
    "all": "all", "any": "all", "ar": "ar", "assaultrifle": "ar", "assaultrifles": "ar",
    "br": "br", "battlerifle": "br", "battlerifles": "br",
    "smg": "smg", "smgs": "smg", "submachinegun": "smg", "submachineguns": "smg",
    "lmg": "lmg", "lmgs": "lmg", "lightmachinegun": "lmg", "lightmachineguns": "lmg",
    "sg": "sg", "shotgun": "sg", "shotguns": "sg", "sr": "sr", "sniper": "sr",
    "snipers": "sr", "sniperrifle": "sr", "sniperrifles": "sr", "mr": "mr", "dmr": "mr",
    "marksman": "mr", "marksmanrifle": "mr", "marksmanrifles": "mr",
    "pistol": "pistols", "pistols": "pistols", "handgun": "pistols", "handguns": "pistols",
    "launcher": "launchers", "launchers": "launchers", "melee": "melee", "knife": "melee", "knives": "melee",
}


def _key(value):
    if not isinstance(value, str) or len(value) > 80:
        return ""
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def canonical_mode(value):
    mode = _MODES.get(_key(value))
    if mode is None:
        raise ValueError("Choose Multiplayer, DMZ or Warzone.")
    return mode


def canonical_type(value):
    if value is None:
        return "all"
    kind = _TYPE_ALIASES.get(_key(value))
    if kind is None:
        raise ValueError("Choose a weapon type from the menu.")
    return kind


def _check_page(page):
    if type(page) is not int or not 1 <= page <= 999:
        raise ValueError("Choose a valid meta page.")
    return page


def _source_mode_matches(row, mode):
    # Current feeds omit this field; the source page establishes their scope.
    # A future explicit conflicting mode must never be silently relabelled.
    explicit = row.get("mode")
    return explicit in (None, "") or _MODES.get(_key(explicit)) == mode


def get_mode_meta(ctx, mode, weapon_type="all", page=1, now=None):
    """Filter a provider snapshot; preserve its original ranks and source dates."""
    mode, kind, page = canonical_mode(mode), canonical_type(weapon_type), _check_page(page)
    if mode == "dmz":
        if page != 1:
            raise ValueError("That meta page doesn't exist. Return to the first page.")
        return {"available": False, "stale": False, "provider": None, "mode": mode,
                "mode_label": "DMZ", "mode_scope": "Modern Warfare 4 DMZ", "weapon_type": kind,
                "weapon_type_label": TYPE_LABELS[kind], "weapons": [], "total": 0, "page": 1, "pages": 1,
                "updated_at": None, "game": "mw4", "error": "dmz_feed_not_configured",
                "warning": "In-card DMZ recommendations aren't available yet. You can open DMZ Radar's dedicated PvP builds below.",
                "source_url": DMZ_SOURCE, "external_source_date": "2026-10-28",
                "coverage": "External DMZ PvP builds are available on DMZ Radar; its last inspected data date is October 28, 2026."}
    route = MODE_ROUTES[mode]
    snapshot = (meta.get_meta(ctx, route["game"]) if now is None
                else meta.get_meta(ctx, route["game"], now=now))
    value = deepcopy(snapshot)
    candidates = [row for row in value.get("weapons", []) if isinstance(row, dict)
                  and _source_mode_matches(row, mode)]
    if kind != "all":
        candidates = [row for row in candidates if _TYPE_ALIASES.get(_key(row.get("class"))) == kind]
    pages = max(1, (len(candidates) + PAGE_SIZE - 1) // PAGE_SIZE)
    if page > pages:
        raise ValueError("That meta page doesn't exist. Return to the first page.")
    value.update(mode=mode, mode_label=MODE_LABELS[mode], mode_scope=route["scope"],
                 weapon_type=kind, weapon_type_label=TYPE_LABELS[kind], total=len(candidates), page=page, pages=pages,
                 mode_source_url=route["coverage_source"], weapons=candidates[(page-1)*PAGE_SIZE:page*PAGE_SIZE])
    return value


def _identity(event):
    return owner_id(event.get("user_id"))


def _cid(action, owner, view, page=None):
    value = f"chm:{action}:{owner}:{view['mode']}:{view['weapon_type']}:{view['page'] if page is None else page}"
    if len(value) > 100:
        raise ValueError("That meta control is too long. Open Meta again.")
    return value


def _selected(event):
    values = event.get("values")
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], str) or len(values[0]) > 100:
        raise ValueError("Choose one option from the menu.")
    return values[0]


def _build_token(row):
    """Bind a choice to the displayed weapon/build, including its source rank.

    Provider ranks can change while an old menu remains clickable. Hashing the
    normalized row prevents an old choice from selecting a new occupant of that
    rank or silently opening a changed attachment list for the same weapon.
    """
    encoded = json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "b" + hashlib.sha256(encoded.encode("utf8")).hexdigest()[:20]


def _credit(view):
    attribution = view.get("attribution") or {}
    return _link(attribution.get("text") or "Data by MetaRadar", attribution.get("url") or "https://metaradar.gg/")


def _description(view, lines):
    """Keep the complete attribution link and reserve room for omission notices."""
    text = _credit(view) + " · " + view["mode_scope"]
    trimmed = False
    for line in lines:
        remaining = 3890 - len(text) - 1
        if len(line) > remaining:
            if remaining > 1:
                text += "\n" + line[:remaining - 1] + "…"
            trimmed = True
            break
        text += "\n" + line
    return text, trimmed


def _embed_size(embed):
    return (len(embed.get("title", "")) + len(embed.get("description", ""))
            + len(embed.get("footer", {}).get("text", ""))
            + sum(len(field["name"]) + len(field["value"]) for field in embed.get("fields", [])))


def _fit_embed(embed, guidance, *, protected=()):
    """Omit complete low-priority fields rather than cut source links or codes."""
    description, removed = embed["description"], 0
    while _embed_size(embed) > 6000:
        candidates = [at for at, field in enumerate(embed["fields"]) if field["name"] not in protected]
        if not candidates:
            break
        embed["fields"].pop(candidates[-1])
        removed += 1
        embed["description"] = description + f"\n{removed} detail section(s) omitted. " + guidance
    return embed


def browser_embed(view):
    title = MODE_LABELS[view["mode"]] + " meta"
    if view["weapon_type"] != "all":
        title += " · " + TYPE_LABELS[view["weapon_type"]]
    if view["mode"] == "dmz":
        return {"title": title, "description": view["warning"] + "\n\n"
                + _link("Open external DMZ builds", DMZ_SOURCE)
                + "\nExternal page last checked with data dated October 28, 2026.", "color": WARNING,
                "footer": {"text": "COD Hub · MW4 DMZ · External source"}}
    lines = []
    if view.get("updated_at"):
        lines.append("Source updated " + _safe(view["updated_at"], 80))
    if view.get("warning"):
        lines.append(_safe(view["warning"], 500))
    if not view.get("available"):
        lines.append("Recommendations are temporarily unavailable. Offline build tools still work.")
    elif not view["weapons"]:
        lines.append("No provider recommendations match this weapon type. Choose another type.")
    else:
        lines.append("Choose a build below for supplied attachments and its complete source.")
    description, trimmed = _description(view, lines)
    fields = []
    for row in view["weapons"]:
        text = _link(row["name"], row["url"])
        trimmed = trimmed or len(_safe(row["name"], 1000)) > 180
        if len(text) > 1024:
            # The selector still opens a detail card with the complete URL in
            # its linked title. Never create a truncated Markdown destination.
            text = _safe(row["name"], 180)
            trimmed = True
        details = [str(row[k]) for k in ("class", "tier", "build_label") if row.get(k)]
        if details:
            joined = " · ".join(details)
            trimmed = trimmed or len(_safe(joined, 1000)) > 350
            detail = "\n" + _safe(joined, 350)
            if len(text) + len(detail) <= 1024:
                text += detail
            else:
                trimmed = True
        fields.append({"name": "#" + str(row["rank"]), "value": text, "inline": False})
    if trimmed:
        description += "\nSome summaries are shortened; choose a build for its complete source."
    embed = {"title": title[:256], "description": description, "fields": fields,
            "color": WARNING if not view.get("available") or view.get("stale") else COLOR,
            "footer": {"text": f"COD Hub · Page {view['page']}/{view['pages']} · {view['total']} matches · Provider ranking preserved"}}
    return _fit_embed(embed, "Choose a build for its complete source.")


def browser_controls(owner, view):
    rows = [ActionRow(SelectMenu(_cid("mode", owner, view), [
        SelectOption(label, mode, default=mode == view["mode"]) for mode, label in MODE_LABELS.items()], placeholder="Choose mode")),
        ActionRow(SelectMenu(_cid("type", owner, view), [
            SelectOption(label, kind, default=kind == view["weapon_type"]) for kind, label in TYPE_LABELS.items()], placeholder="Filter by weapon type"))]
    if view["weapons"]:
        rows.append(ActionRow(SelectMenu(_cid("pick", owner, view), [
            SelectOption(row["name"], _build_token(row), description=("#" + str(row["rank"]) + " · " + str(row.get("class") or "Weapon"))[:100])
            for row in view["weapons"]], placeholder="Choose a meta build")))
    buttons = []
    if view["page"] > 1:
        buttons.append(Button("Previous", custom_id=_cid("page", owner, view, view["page"]-1), style="secondary"))
    if view["page"] < view["pages"]:
        buttons.append(Button("Next", custom_id=_cid("page", owner, view, view["page"]+1), style="secondary"))
    if view["mode"] == "dmz":
        buttons.append(Button("Open external DMZ builds", style="link", url=DMZ_SOURCE))
    buttons += [Button("Refresh", custom_id=_cid("page", owner, view), style="secondary"),
                Button("Import code", custom_id="chh:import", style="primary"),
                Button("Home", custom_id="chh:private", style="secondary")]
    rows.append(ActionRow(*buttons))
    return rows


def _detail_fields(row):
    chunks, current = [], ""
    for part in row.get("attachments", []):
        line = "**" + _safe(part.get("slot"), 40) + "** · " + _safe(part.get("name"), 120)
        if len(current) + len(line) + 1 > 1000:
            chunks.append(current); current = ""
        current += ("\n" if current else "") + line
    if current:
        chunks.append(current)
    fields = [{"name": "Attachments" if n == 0 else "Attachments (continued)", "value": text, "inline": False}
              for n, text in enumerate(chunks)]
    if not fields:
        fields = [{"name": "Attachments", "value": "The source has not supplied a build for this weapon yet.", "inline": False}]
    code = row.get("code")
    if isinstance(code, str) and re.fullmatch(r"[A-Z0-9-]{3,128}", code):
        text = "```" + code + "```"
    elif code:
        text = "Open the provider page for its source code."
    else:
        text = "Not supplied by this source."
    fields.append({"name": "In-game code (source)", "value": text, "inline": False})
    if row.get("updated_at"):
        fields.append({"name": "Build source updated", "value": _safe(row["updated_at"], 80), "inline": False})
    return fields


def detail_embed(view, row):
    # The linked title retains the exact provider URL without spending the
    # description/field text budget on a second copy of a potentially long URL.
    lines = ["Open the card title for the weapon and build source."]
    if view.get("updated_at"):
        lines.append("Feed updated " + _safe(view["updated_at"], 80))
    if row.get("build_label"):
        lines.append(_safe(row["build_label"], 160))
    if view.get("warning"):
        lines.append(_safe(view["warning"], 500))
    if view["mode"] == "warzone":
        lines.append("A Warzone source code may belong to another game; it is not automatically imported into MW4.")
    description, trimmed = _description(view, lines)
    trimmed = trimmed or len(_safe(row["name"], 1000)) > 180 or any(
        len(_safe(part.get("slot"), 1000)) > 40 or len(_safe(part.get("name"), 1000)) > 120
        for part in row.get("attachments", []))
    if trimmed:
        description += "\nSome notes or attachment labels are shortened; open the provider for full details."
    embed = {"title": _safe(row["name"], 180), "url": row["url"], "description": description,
            "color": WARNING if view.get("stale") else COLOR, "fields": _detail_fields(row),
            "footer": {"text": "COD Hub · MetaRadar · Provider rank #" + str(row["rank"])}}
    return _fit_embed(embed, "Open the provider for the complete build.",
                      protected=("In-game code (source)", "Build source updated"))


def _followup(ctx, view, owner):
    ctx.interaction.followup(embeds=[browser_embed(view)], components=browser_controls(owner, view),
                             ephemeral=True, allowed_mentions=NO_MENTIONS)


def _failure(ctx, error):
    if isinstance(error, ValueError):
        text = str(error)[:1800]
    else:
        ctx.log("COD Hub meta browser failed", level="error", error_type=type(error).__name__)
        text = "The meta browser couldn't complete that request. Please try again."
    ctx.interaction.followup(content=text, ephemeral=True, allowed_mentions=NO_MENTIONS)


def handle_open(ctx, event, mode="multiplayer", weapon_type="all"):
    ctx.interaction.defer(ephemeral=True)
    try:
        owner = _identity(event)
        _followup(ctx, get_mode_meta(ctx, mode, weapon_type), owner)
    except Exception as error:
        _failure(ctx, error)


def handle_command(ctx, event):
    options = event.get("options", [])
    if not isinstance(options, dict):
        options = {item["name"]: item.get("value") for item in options
                   if isinstance(item, dict) and isinstance(item.get("name"), str)} if isinstance(options, list) else {}
    handle_open(ctx, event, mode=options.get("mode", "multiplayer"), weapon_type=options.get("weapon_type", "all"))


def handle_component(ctx, event):
    ctx.interaction.defer(ephemeral=True)
    try:
        owner = _identity(event)
        raw = event.get("custom_id")
        match = _CID.fullmatch(raw) if isinstance(raw, str) and len(raw) <= 100 else None
        if match is None:
            raise ValueError("That meta control is invalid. Open Meta again.")
        action, bound_owner, mode, kind, page = match.groups()
        if bound_owner != owner:
            raise ValueError("This meta view belongs to another person. Open Meta for your own view.")
        kind, page = canonical_type(kind), _check_page(int(page))
        if action == "mode":
            mode, page = canonical_mode(_selected(event)), 1
        elif action == "type":
            kind, page = canonical_type(_selected(event)), 1
        selected = _selected(event) if action == "pick" else None
        if selected is not None and not re.fullmatch(r"b[0-9a-f]{20}", selected):
            raise ValueError("Recommendations changed. Refresh this meta page and choose the build again.")
        view = get_mode_meta(ctx, mode, kind, page)
        if action == "pick":
            row = next((row for row in view["weapons"] if _build_token(row) == selected), None)
            if row is None:
                raise ValueError("Recommendations changed. Refresh this meta page and choose the build again.")
            controls = [ActionRow(Button("Back to meta", custom_id=_cid("page", owner, view), style="secondary"),
                                  Button("Open provider", style="link", url=row["url"]),
                                  Button("Import code", custom_id="chh:import", style="primary"),
                                  Button("Home", custom_id="chh:private", style="secondary"))]
            ctx.interaction.followup(embeds=[detail_embed(view, row)], components=controls,
                                     ephemeral=True, allowed_mentions=NO_MENTIONS)
        else:
            _followup(ctx, view, owner)
    except Exception as error:
        _failure(ctx, error)
