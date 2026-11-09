"""Stateless, owner-bound catalog navigation and fixed-ID Discord forms."""
import base64
import binascii
import re

from yourbot_sdk import ActionRow, Button, SelectMenu, SelectOption, TextInput

from . import cards, catalog, hub_cards
from .store import BuildStore, owner_id

NO_MENTIONS = {"parse": []}
IMPORT_MODAL = "chh:import:v1"
SEARCH_MODAL = "chh:search:v1"
REFERENCE_MODAL = "chh:reference:v1"


def _actor(event):
    return owner_id(event.get("user_id"))


def _id(action, owner, *parts):
    value = ":".join(("chh", action, owner, *(str(p) for p in parts)))
    if len(value) > 100 or any(":" in str(part) for part in parts):
        raise ValueError("Please use a shorter search and open the browser again.")
    return value


def _query(value):
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("Search with a weapon name or prefix of up to 40 characters.")
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _pack(query):
    return base64.urlsafe_b64encode(_query(query).encode("ascii")).decode("ascii").rstrip("=") or "_"


def _unpack(token):
    if token == "_":
        return ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,54}", token):
        raise ValueError("That search control is invalid. Open COD Hub again.")
    try:
        value = base64.b64decode(token + "=" * (-len(token) % 4), altchars=b"-_", validate=True).decode("ascii")
    except (ValueError, UnicodeError, binascii.Error) as error:
        raise ValueError("That search control is invalid. Open COD Hub again.") from error
    if _pack(value) != token:
        raise ValueError("That search control is invalid. Open COD Hub again.")
    return value


def _page(value):
    if not re.fullmatch(r"[1-9][0-9]{0,2}", str(value)):
        raise ValueError("That catalog page is invalid.")
    return int(value)


def _selected(event):
    values = event.get("values")
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], str) or len(values[0]) > 100:
        raise ValueError("Choose one item from the menu.")
    return values[0]


def _reply(ctx, embed, components, *, update=False):
    ctx.interaction.respond(content="", embeds=[embed], components=components,
                            ephemeral=True, update_message=update, allowed_mentions=NO_MENTIONS)


def _error(ctx, error):
    if isinstance(error, ValueError):
        message = str(error)[:1800]
    else:
        ctx.log("COD Hub navigation failed", level="error", error_type=type(error).__name__)
        message = "COD Hub couldn't open that card. Try /codhub again."
    ctx.interaction.respond(content=message, ephemeral=True, allowed_mentions=NO_MENTIONS)


def home_controls():
    return [ActionRow(
        Button("Import build", custom_id="chh:import", style="primary"),
        Button("Explore weapons", custom_id="chh:explore", style="secondary"),
        Button("Compare", custom_id="chc:open", style="secondary"),
        Button("My builds", custom_id="chh:library", style="secondary")),
        ActionRow(SelectMenu("chh:more", [
            SelectOption("Multiplayer meta builds", "mode-multiplayer", description="Filter MW4 recommendations by weapon type"),
            SelectOption("DMZ meta builds", "mode-dmz", description="Dedicated DMZ source and availability"),
            SelectOption("Warzone meta builds", "mode-warzone", description="Filter Battle Royale recommendations by weapon type"),
            SelectOption("BO7 meta loadouts", "meta-bo7"),
            SelectOption("Search references", "references", description="Maps, operators, camos, challenges and more"),
        ], placeholder="More to explore"))]


def handle_home(ctx, event):
    # A public, reusable launcher. Personal results are always separate replies.
    ctx.interaction.defer()
    ctx.interaction.followup(embeds=[hub_cards.home_embed()], components=home_controls(),
                             allowed_mentions=NO_MENTIONS)


def weapons_view(owner, class_key="all", page=1, query=""):
    query = _query(query)
    payload = catalog.browse_weapons(class_key, query=query, page=page)
    class_key = payload["class_key"] or "all"
    token = _pack(query)
    classes = catalog.list_weapon_classes()
    options = [SelectOption("All classes", "all", default=class_key == "all")]
    options += [SelectOption(c["label"], c["key"], description=f"{c['count']} weapons",
                             default=c["key"] == class_key) for c in classes]
    rows = [ActionRow(SelectMenu(_id("c", owner, token), options, placeholder="Filter by class"))]
    if payload["items"]:
        rows.append(ActionRow(SelectMenu(_id("p", owner, class_key, page, token), [
            SelectOption(w["name"], w["id"], description=w.get("class") or "Weapon details")
            for w in payload["items"]], placeholder="Choose a weapon")))
    buttons = []
    if page > 1:
        buttons.append(Button("Previous", custom_id=_id("w", owner, class_key, page-1, token), style="secondary"))
    if page < payload["pages"]:
        buttons.append(Button("Next", custom_id=_id("w", owner, class_key, page+1, token), style="secondary"))
    buttons += [Button("Search", custom_id="chh:search", style="primary"),
                Button("Home", custom_id=_id("h", owner), style="secondary")]
    rows.append(ActionRow(*buttons))
    label = next((c["label"] for c in classes if c["key"] == class_key), None)
    return hub_cards.weapons_embed(payload, label), rows


def build_navigation(code=None):
    buttons = []
    prefix = str(code or "").split("-", 1)[0]
    if re.fullmatch(r"[ALRBPSCUM][0-9]{2}", prefix):
        buttons.append(Button("Explore weapon", custom_id="chh:openweapon:" + prefix, style="secondary"))
        if re.fullmatch(r"[A-Z0-9-]{7,25}", str(code)):
            buttons.append(Button("Compare build", custom_id="chc:open:c" + str(code), style="secondary"))
    buttons += [Button("My builds", custom_id="chh:library", style="secondary"),
                Button("Hub", custom_id="chh:private", style="secondary")]
    return ActionRow(*buttons)


def weapon_controls(weapon, owner, back=None):
    identifier = weapon.get("id") or weapon.get("prefix") or weapon.get("asset_id")
    if not identifier:
        return [ActionRow(Button("COD Hub", custom_id="chh:private", style="secondary"))]
    buttons = []
    if weapon.get("native_supported", bool(weapon.get("prefix"))):
        buttons += [Button("Explore attachments", custom_id=_id("a", owner, identifier, "_", 1), style="primary"),
                    Button("Preview base build", custom_id=_id("b", owner, identifier), style="secondary")]
    buttons.append(Button("Compare", custom_id="chc:open:w" + identifier, style="secondary"))
    class_key, page, token = back or (weapon.get("class_key") or "all", 1, "_")
    buttons += [Button("Back", custom_id=_id("w", owner, class_key, page, token), style="secondary"),
                Button("Home", custom_id=_id("h", owner), style="secondary")]
    return [ActionRow(*buttons)]


def _weapon_view(identifier, owner, back=None):
    weapon = catalog.get_weapon(identifier)
    return cards.weapon_embed(weapon), weapon_controls(weapon, owner, back)


def _attachments_view(owner, weapon_id, slot="_", page=1):
    payload = catalog.browse_attachments(weapon_id, slot=None if slot == "_" else slot, page=page)
    weapon = payload["weapon"]
    rows = []
    if payload["slots"]:
        options = [SelectOption("All slots", "_", default=slot == "_")]
        options += [SelectOption(s["label"], s["key"], description=f"{s['count']} catalog entries",
                                 default=slot == s["key"]) for s in payload["slots"]]
        rows.append(ActionRow(SelectMenu(_id("s", owner, weapon_id), options, placeholder="Filter by attachment slot")))
    if payload["items"]:
        rows.append(ActionRow(SelectMenu(_id("t", owner, weapon_id, slot, page), [
            SelectOption(a["name"], a["binding_id"], description=a["slot_label"])
            for a in payload["items"]], placeholder="Choose an attachment")))
    buttons = []
    if page > 1:
        buttons.append(Button("Previous", custom_id=_id("a", owner, weapon_id, slot, page-1), style="secondary"))
    if page < payload["pages"]:
        buttons.append(Button("Next", custom_id=_id("a", owner, weapon_id, slot, page+1), style="secondary"))
    buttons += [Button("Back to weapon", custom_id=_id("v", owner, weapon_id), style="secondary"),
                Button("Home", custom_id=_id("h", owner), style="secondary")]
    rows.append(ActionRow(*buttons))
    return hub_cards.attachments_embed(weapon, payload, None if slot == "_" else slot), rows


def _form(ctx, custom_id, title, fields):
    ctx.interaction.send_modal(title=title, custom_id=custom_id, fields=fields)


def _import_form(ctx):
    _form(ctx, IMPORT_MODAL, "Import an MW4 build", [
        TextInput("Build code", "code", placeholder="A01-42J19-BU11", max_length=256),
        TextInput("Build name (optional)", "title", required=False, max_length=80)])


def _search_form(ctx):
    _form(ctx, SEARCH_MODAL, "Find a weapon", [
        TextInput("Weapon name or prefix", "query", placeholder="Kastov, Hyeon Burst or A01", max_length=40)])


def _reference_form(ctx):
    _form(ctx, REFERENCE_MODAL, "Search COD references", [
        TextInput("What would you like to find?", "query", placeholder="A map, operator, camo, challenge or prestige", max_length=120)])


def _preview(ctx, event, code, title=None):
    from . import app
    owner = _actor(event)
    build = catalog.resolve_build(code)
    if build.get("label_status") == "fallback":
        raise ValueError("This build contains items without verified English names. Try another build; its code has not been changed.")
    record = BuildStore(ctx.kv, ctx.server_id).preview(owner, build, title)
    app._show(ctx, record, "p", ephemeral=True)


def handle_component(ctx, event):
    """Local private pages update in place; slow/stateful work acknowledges first."""
    try:
        owner = _actor(event)
        raw = event.get("custom_id")
        if not isinstance(raw, str) or len(raw) > 100:
            raise ValueError("That COD Hub control is invalid.")
        if raw in {"chh:import", "chh:search", "chh:reference"}:
            return {"chh:import": _import_form, "chh:search": _search_form,
                    "chh:reference": _reference_form}[raw](ctx)
        if raw == "chh:private":
            return _reply(ctx, hub_cards.home_embed(), home_controls())
        if raw == "chh:library":
            from .library_ui import handle_open
            return handle_open(ctx, event)
        if raw == "chh:explore":
            return _reply(ctx, *weapons_view(owner))
        if raw.startswith("chh:openweapon:"):
            identifier = raw[len("chh:openweapon:"):]
            return _reply(ctx, *_weapon_view(identifier, owner))
        if raw == "chh:more":
            selected = _selected(event)
            if selected == "references":
                return _reference_form(ctx)
            if selected in {"mode-multiplayer", "mode-dmz", "mode-warzone"}:
                from .meta_browser import handle_open
                return handle_open(ctx, event, mode=selected.removeprefix("mode-"))
            if selected not in {"meta-mw4", "meta-bo7", "meta-warzone"}:
                raise ValueError("Choose a source from the More menu.")
            ctx.interaction.defer(ephemeral=True)
            try:
                from .meta import get_meta
                payload = get_meta(ctx, selected.removeprefix("meta-"))
                ctx.interaction.followup(embeds=[cards.meta_embed(payload)],
                    components=[ActionRow(Button("Home", custom_id="chh:private", style="secondary"))],
                    ephemeral=True, allowed_mentions=NO_MENTIONS)
            except Exception as error:
                from .app import _failure
                _failure(ctx, error)
            return
        parts = raw.split(":")
        if len(parts) < 3 or parts[0] != "chh" or parts[2] != owner:
            raise ValueError("This view belongs to another person. Open /codhub for your own view.")
        action, args = parts[1], parts[3:]
        if action == "h" and not args:
            return _reply(ctx, hub_cards.home_embed(), home_controls(), update=True)
        if action == "w" and len(args) == 3:
            return _reply(ctx, *weapons_view(owner, args[0], _page(args[1]), _unpack(args[2])), update=True)
        if action == "c" and len(args) == 1:
            return _reply(ctx, *weapons_view(owner, _selected(event), 1, _unpack(args[0])), update=True)
        if action == "p" and len(args) == 3:
            page = catalog.browse_weapons(args[0], query=_unpack(args[2]), page=_page(args[1]))
            selected = _selected(event)
            if selected not in {w["id"] for w in page["items"]}:
                raise ValueError("Choose a weapon from the current page.")
            return _reply(ctx, *_weapon_view(selected, owner, (args[0], args[1], args[2])), update=True)
        if action == "v" and len(args) == 1:
            return _reply(ctx, *_weapon_view(args[0], owner), update=True)
        if action == "a" and len(args) == 3:
            return _reply(ctx, *_attachments_view(owner, args[0], args[1], _page(args[2])), update=True)
        if action == "s" and len(args) == 1:
            selected = _selected(event)
            slots = catalog.browse_attachments(args[0])["slots"]
            if selected != "_" and selected not in {s["key"] for s in slots}:
                raise ValueError("Choose an attachment slot from this weapon.")
            return _reply(ctx, *_attachments_view(owner, args[0], selected), update=True)
        if action == "t" and len(args) == 3:
            page = catalog.browse_attachments(args[0], slot=None if args[1] == "_" else args[1], page=_page(args[2]))
            selected = _selected(event)
            if selected not in {a["binding_id"] for a in page["items"]}:
                raise ValueError("Choose an attachment from the current page.")
            item = catalog.get_attachment(args[0], selected)
            rows = [ActionRow(Button("Back to attachments", custom_id=_id("a", owner, *args), style="secondary"),
                              Button("Home", custom_id=_id("h", owner), style="secondary"))]
            return _reply(ctx, cards.attachment_embed(item), rows, update=True)
        if action == "b" and len(args) == 1:
            ctx.interaction.defer(ephemeral=True)
            try:
                weapon = catalog.get_weapon(args[0])
                if not weapon.get("native_supported"):
                    raise ValueError("This reference weapon has no supported native build code.")
                native = catalog.get_catalog()
                code = native.codec.encode(weapon["prefix"], [0] * len(native.schema.slots))
                _preview(ctx, event, code)
            except Exception as error:
                from .app import _failure
                _failure(ctx, error)
            return
        raise ValueError("That COD Hub control is invalid. Open /codhub again.")
    except Exception as error:
        _error(ctx, error)


def handle_import(ctx, event):
    from .app import _failure
    ctx.interaction.defer(ephemeral=True)
    try:
        values = event.get("modal_values")
        if not isinstance(values, dict) or not isinstance(values.get("code"), str) or len(values["code"]) > 256:
            raise ValueError("Paste a valid MW4 build code.")
        title = values.get("title", "")
        if not isinstance(title, str) or len(title) > 80:
            raise ValueError("Use a build name of up to 80 characters.")
        _preview(ctx, event, values["code"], title)
    except Exception as error:
        _failure(ctx, error)


def handle_search(ctx, event):
    try:
        owner = _actor(event)
        values = event.get("modal_values")
        query = _query(values.get("query") if isinstance(values, dict) else None)
        if not query:
            raise ValueError("Enter a weapon name or prefix.")
        _reply(ctx, *weapons_view(owner, query=query))
    except Exception as error:
        _error(ctx, error)


def handle_reference(ctx, event):
    from .app import _failure
    ctx.interaction.defer(ephemeral=True)
    try:
        _actor(event)
        values = event.get("modal_values")
        if not isinstance(values, dict):
            raise ValueError("Enter a reference search.")
        from .reference import get_reference
        payload = get_reference(ctx, values.get("query"), category="all", game="all")
        ctx.interaction.followup(embeds=[cards.reference_embed(payload)],
            components=[ActionRow(Button("Search again", custom_id="chh:reference", style="primary"),
                                  Button("Home", custom_id="chh:private", style="secondary"))],
            ephemeral=True, allowed_mentions=NO_MENTIONS)
    except Exception as error:
        _failure(ctx, error)
