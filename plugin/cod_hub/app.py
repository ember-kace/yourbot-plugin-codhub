"""COD Hub slash commands and owner-bound durable build controls."""
import base64
import re

from yourbot_sdk import ActionRow, Button

from .store import BuildStore, clean_title, owner_id


NO_MENTIONS = {"parse": []}
POST_NOTICE = "Post to channel and Post PNG to channel publish in the current channel. PNGs include a reviewed weapon preview where available."
_CUSTOM_ID = re.compile(r"ch:(save|code|share|png|delete|list):([psl]):([0-9]{1,22}):([a-z0-9]{1,16})\Z")


def _catalog():
    from . import catalog
    return catalog


def _cards():
    from . import cards
    return cards


def _options(event):
    raw = event.get("options", [])
    if isinstance(raw, dict):
        return raw
    return {option["name"]: option.get("value") for option in raw
            if isinstance(option, dict) and isinstance(option.get("name"), str)}


def _user(event):
    return owner_id(event.get("user_id"))


def _game(value, *, meta=False):
    game = str(value or "mw4").strip().lower()
    allowed = {"mw4", "bo7", "warzone"} if meta else {"mw4"}
    if game not in allowed:
        raise ValueError("Choose MW4, BO7 or Warzone." if meta else "Native build and weapon lookups currently support MW4. Choose MW4.")
    return game


def _followup(ctx, **kwargs):
    ctx.interaction.followup(allowed_mentions=NO_MENTIONS, **kwargs)


def _failure(ctx, error, *, components=None):
    if isinstance(error, ValueError):
        message = str(error)[:1800] or "That request is invalid."
    else:
        ctx.log("COD Hub action failed", level="error", error_type=type(error).__name__)
        message = "COD Hub couldn't complete that action. Please try again."
    options = {"components": components} if components is not None else {}
    _followup(ctx, content=message, ephemeral=True, **options)


def _record_build(record):
    build = _named_build(_catalog().resolve_build(record["code"], game=record["game"]))
    build = dict(build)
    build["title"] = clean_title(record.get("title"))
    return build


def _named_build(build):
    """Keep untranslated identities out of public and saved-card actions."""
    if build.get("label_status") == "fallback":
        raise ValueError("This build contains items without verified English names. Try another build; its code has not been changed.")
    return build


def _controls(record, kind):
    stem = ":" + kind + ":" + record["owner"] + ":" + record["id"]
    utility = []
    if kind == "p":
        utility.append(Button("Save", custom_id="ch:save" + stem, style="success"))
    utility.append(Button("Show code", custom_id="ch:code" + stem, style="secondary"))
    if kind == "s":
        utility.append(Button("Rename", custom_id="chl:rename:" + record["owner"] + ":" + record["code"], style="secondary"))
        utility.append(Button("Delete", custom_id="chl:ask:" + record["owner"] + ":" + record["id"], style="danger"))
    posting = [
        Button("Post to channel", custom_id="ch:share" + stem, style="secondary"),
        Button("Post PNG to channel", custom_id="ch:png" + stem, style="secondary"),
    ]
    from .hub import build_navigation
    return [ActionRow(*utility), ActionRow(*posting), build_navigation(record["code"])]


def _show(ctx, record, kind, *, ephemeral=False, notice=POST_NOTICE):
    build = _record_build(record)
    _followup(ctx, content=notice, embeds=[_cards().build_embed(build)],
              components=_controls(record, kind), ephemeral=ephemeral)


def handle_build(ctx, event):
    ctx.interaction.defer(ephemeral=True)
    try:
        options = _options(event)
        owner = _user(event)
        game = _game(options.get("game"))
        code = options.get("code")
        if not isinstance(code, str) or not code.strip():
            raise ValueError("Provide a native MW4 build code.")
        build = _named_build(_catalog().resolve_build(code, game=game))
        record = BuildStore(ctx.kv, ctx.server_id).preview(owner, build, options.get("title"))
        build = dict(build)
        build["title"] = record["title"]
        _followup(ctx, content=POST_NOTICE, embeds=[_cards().build_embed(build)], components=_controls(record, "p"), ephemeral=True)
    except Exception as error:
        _failure(ctx, error)


def handle_weapon(ctx, event):
    ctx.interaction.defer(ephemeral=True)
    try:
        options = _options(event)
        game = _game(options.get("game"))
        query = str(options.get("query") or "").strip()
        if not query or len(query) > 160:
            raise ValueError("Search with a weapon name, internal reference or code prefix.")
        weapons = _catalog().search_weapons(query, limit=10, game=game)
        if not weapons:
            raise ValueError("No weapon matched in the packaged MW4 catalog. Try a name or prefix such as A01.")
        if len(weapons) == 1:
            embed = _cards().weapon_embed(weapons[0])
            from .hub import weapon_controls
            controls = weapon_controls(weapons[0], _user(event))
        else:
            lines = ["`" + str(w.get("prefix") or "—") + "` · " + clean_title(w.get("name") or w.get("internal_ref") or "Unknown weapon") for w in weapons]
            embed = {"title": "Matching MW4 weapons", "description": "\n".join(lines)
                     + "\n\nRun /codweapon with a full name or prefix to open its details.", "color": 0xCBA45C}
            from .hub import _id, _pack
            token = _pack(query) if len(query) <= 40 else "_"
            controls = [ActionRow(Button("Browse results", custom_id=_id("w", _user(event), "all", 1, token), style="primary"),
                                  Button("Hub", custom_id="chh:private", style="secondary"))]
        _followup(ctx, embeds=[embed], components=controls, ephemeral=True)
    except Exception as error:
        _failure(ctx, error)


def handle_attachment(ctx, event):
    ctx.interaction.defer(ephemeral=True)
    try:
        options = _options(event)
        game = _game(options.get("game"))
        query = str(options.get("query") or "").strip()
        if not query or len(query) > 160:
            raise ValueError("Search with an attachment name or internal reference.")
        weapon = str(options.get("weapon") or "").strip() or None
        matches = _catalog().search_attachments(query, weapon=weapon, limit=10, game=game)
        if not matches:
            raise ValueError("No attachment matched. Try its full name or use weapon:A01 to narrow the search.")
        if len(matches) == 1:
            embed = _cards().attachment_embed(matches[0])
        else:
            names = [clean_title(a.get("name") or a.get("internal_ref") or a.get("asset_id") or "Unknown attachment") for a in matches]
            embed = {"title": "Matching MW4 attachments", "description": "\n".join("• " + name for name in names)
                     + "\n\nUse a full name/internal reference and a weapon prefix to narrow the search.", "color": 0xCBA45C}
        from .hub import build_navigation
        _followup(ctx, embeds=[embed], components=[build_navigation(weapon)], ephemeral=True)
    except Exception as error:
        _failure(ctx, error)


def _saved_list(ctx, store, owner, page=1):
    from .cards import _safe

    records = store.list_saved(owner)
    pages = max(1, (len(records) + 9) // 10)
    if type(page) is not int or page < 1 or page > pages:
        raise ValueError("That saved-build page doesn't exist.")
    if not records:
        _followup(ctx, content="Your saved library is empty. Choose Import code, paste a code, then Save the preview.",
                  components=[ActionRow(Button("Import code", custom_id="chh:import", style="primary"),
                                        Button("Hub", custom_id="chh:private", style="secondary"))],
                  ephemeral=True)
        return
    selected = records[(page - 1) * 10:page * 10]
    description = "\n\n".join("**" + _safe(clean_title(r.get("title")), 180) + "**\nID: `" + r["id"] + "` · MW4" for r in selected)
    embed = {"title": "Your saved builds", "description": description,
             "footer": {"text": f"Page {page}/{pages} · {len(records)}/50 builds · Open with /codsaved action:show id:<ID>"}, "color": 0xCBA45C}
    buttons = []
    if page > 1:
        buttons.append(Button("Previous", custom_id=f"ch:list:l:{owner}:{page-1}", style="secondary"))
    if page < pages:
        buttons.append(Button("Next", custom_id=f"ch:list:l:{owner}:{page+1}", style="secondary"))
    _followup(ctx, embeds=[embed], components=[ActionRow(*buttons)] if buttons else [], ephemeral=True)


def handle_saved(ctx, event):
    ctx.interaction.defer(ephemeral=True)
    try:
        owner = _user(event)
        options = _options(event)
        action = str(options.get("action") or "list").lower()
        store = BuildStore(ctx.kv, ctx.server_id)
        if action == "list":
            _saved_list(ctx, store, owner, options.get("page", 1))
            return
        if action not in {"show", "delete"}:
            raise ValueError("Choose list, show or delete.")
        identifier = str(options.get("id") or "").strip().lower()
        record = store.get("s", owner, identifier)
        if record is None:
            raise ValueError("That saved build wasn't found in your library.")
        if action == "delete":
            store.delete(owner, identifier)
            _followup(ctx, content="Deleted saved build `" + identifier + "`.", ephemeral=True)
        else:
            _show(ctx, record, "s", ephemeral=True)
    except Exception as error:
        _failure(ctx, error)


def handle_meta(ctx, event):
    if not _options(event).get("game"):
        from .meta_browser import handle_command
        return handle_command(ctx, event)
    ctx.interaction.defer()
    try:
        from .meta import get_meta
        payload = get_meta(ctx, _game(_options(event).get("game"), meta=True))
        _followup(ctx, embeds=[_cards().meta_embed(payload)])
    except Exception as error:
        _failure(ctx, error)


def handle_reference(ctx, event):
    ctx.interaction.defer(ephemeral=True)
    try:
        from .reference import get_reference
        options = _options(event)
        payload = get_reference(ctx, options.get("query"),
                                category=options.get("category") or "all",
                                game=options.get("game") or "all")
        _followup(ctx, embeds=[_cards().reference_embed(payload)], ephemeral=True)
    except Exception as error:
        _failure(ctx, error)


def handle_component(ctx, event):
    ctx.interaction.defer(ephemeral=True)
    try:
        user = _user(event)
        match = _CUSTOM_ID.fullmatch(str(event.get("custom_id") or ""))
        if not match:
            raise ValueError("That COD Hub button is invalid. Run the command again.")
        action, kind, owner, identifier = match.groups()
        # Public preview Save makes a copy for the clicker. Other controls use
        # the encoded owner and the actual record owner; neither comes from a form.
        if user != owner and not (action == "save" and kind == "p"):
            raise ValueError("This control belongs to the person who created this card. Use Save for your own copy.")
        store = BuildStore(ctx.kv, ctx.server_id)
        if action == "list":
            if kind != "l" or not identifier.isdigit():
                raise ValueError("That saved-list button is invalid.")
            _saved_list(ctx, store, user, int(identifier))
            return
        if kind not in {"p", "s"} or (action == "delete" and kind != "s"):
            raise ValueError("That build control is invalid.")
        record = store.get(kind, owner, identifier)
        if record is None:
            raise ValueError("This build preview has expired or was deleted. Import the code again or open My builds.")
        if action == "save":
            _record_build(record)
            saved, created = store.save(user, record)
            _show(ctx, saved, "s", ephemeral=True,
                  notice=("Saved" if created else "Already saved") + " in your library. " + POST_NOTICE)
        elif action == "delete":
            store.delete(user, identifier)
            _followup(ctx, content="Deleted saved build `" + identifier + "`.", ephemeral=True)
        elif action == "code":
            _followup(ctx, content="MW4 build code:\n```\n" + record["code"] + "\n```", ephemeral=True)
        elif action in {"share", "png"}:
            channel = str(event.get("channel_id") or "")
            if not channel.isdigit():
                raise ValueError("Open this control in a Discord channel to post the build.")
            build = _record_build(record)
            if action == "share":
                preview = store.preview(user, build, record.get("title"))
                ctx.discord.send_message(channel_id=channel, content=POST_NOTICE,
                    embeds=[_cards().build_embed(build)], components=_controls(preview, "p"), allowed_mentions=NO_MENTIONS)
            else:
                png = _cards().render_build_png(build)
                if not isinstance(png, bytes) or not png.startswith(b"\x89PNG\r\n\x1a\n") or len(png) > 8 * 1024 * 1024:
                    raise ValueError("The image couldn't be prepared within Discord's file limit.")
                ctx.discord.send_message(channel_id=channel,
                    files=[{"filename": "cod-hub-" + identifier + ".png", "data_b64": base64.b64encode(png).decode("ascii")}],
                    allowed_mentions=NO_MENTIONS)
            _followup(ctx, content="Posted the " + ("build card" if action == "share" else "PNG") + " in this channel.", ephemeral=True)
    except Exception as error:
        _failure(ctx, error)


def register(plugin):
    from . import hub, library_ui, comparison_ui, meta_browser

    @plugin.on_slash_command("codcompare")
    def codcompare(ctx, event):
        comparison_ui.handle_command(ctx, event)

    @plugin.on_slash_command("codhub")
    def codhub(ctx, event):
        hub.handle_home(ctx, event)

    @plugin.on_slash_command("codbuild")
    def codbuild(ctx, event):
        handle_build(ctx, event)

    @plugin.on_slash_command("codweapon")
    def codweapon(ctx, event):
        handle_weapon(ctx, event)

    @plugin.on_slash_command("codsaved")
    def codsaved(ctx, event):
        handle_saved(ctx, event)

    @plugin.on_slash_command("codattachment")
    def codattachment(ctx, event):
        handle_attachment(ctx, event)

    @plugin.on_slash_command("codmeta")
    def codmeta(ctx, event):
        handle_meta(ctx, event)

    @plugin.on_slash_command("codreference")
    def codreference(ctx, event):
        handle_reference(ctx, event)

    @plugin.on_component(prefix="ch:")
    def component(ctx, event):
        handle_component(ctx, event)

    @plugin.on_component(prefix="chh:")
    def hub_component(ctx, event):
        hub.handle_component(ctx, event)

    @plugin.on_component(prefix="chl:")
    def library_component(ctx, event):
        library_ui.handle_component(ctx, event)

    @plugin.on_component(prefix="chc:")
    def comparison_component(ctx, event):
        comparison_ui.handle_component(ctx, event)

    @plugin.on_component(prefix="chm:")
    def meta_component(ctx, event):
        meta_browser.handle_component(ctx, event)

    @plugin.on_modal_submit(comparison_ui.MODAL)
    def compare_modal(ctx, event):
        comparison_ui.handle_modal(ctx, event)

    @plugin.on_modal_submit(hub.IMPORT_MODAL)
    def import_modal(ctx, event):
        hub.handle_import(ctx, event)

    @plugin.on_modal_submit(hub.SEARCH_MODAL)
    def search_modal(ctx, event):
        hub.handle_search(ctx, event)

    @plugin.on_modal_submit(hub.REFERENCE_MODAL)
    def reference_modal(ctx, event):
        hub.handle_reference(ctx, event)

    @plugin.on_modal_submit("chl:rename:v1")
    def rename_modal(ctx, event):
        library_ui.handle_rename(ctx, event)
