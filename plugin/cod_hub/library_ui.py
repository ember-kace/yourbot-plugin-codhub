"""Private, owner-bound saved-library menus and rename forms."""
import re

from yourbot_sdk import ActionRow, Button, SelectMenu, SelectOption, TextInput

from . import hub_cards
from .cards import COLOR, _safe
from .store import BuildStore, build_id, clean_title, owner_id


NO_MENTIONS = {"parse": []}
PAGE_SIZE = 10
RENAME_MODAL = "chl:rename:v1"
_LIST = re.compile(r"chl:list:([0-9]{1,22}):([1-9][0-9]{0,2})\Z")
_OPEN = re.compile(r"chl:open:([0-9]{1,22})\Z")
_ITEM = re.compile(r"chl:(ask|delete):([0-9]{1,22}):([a-f0-9]{16})\Z")
_RENAME = re.compile(r"chl:rename:([0-9]{1,22}):([A-Z0-9-]{7,25})\Z")
_IDENTIFIER = re.compile(r"[a-f0-9]{16}\Z")


def _actor(event):
    return owner_id(event.get("user_id"))


def _check_owner(event, owner):
    actor = _actor(event)
    if actor != owner:
        raise ValueError("This is another person's private library. Open My builds for your own library.")
    return actor


def _failure(ctx, error, *, initial=False):
    if isinstance(error, ValueError):
        message = str(error)[:1800] or "That library action is invalid."
    else:
        ctx.log("COD Hub library action failed", level="error", error_type=type(error).__name__)
        message = "COD Hub couldn't open that library action. Please try again."
    send = ctx.interaction.respond if initial else ctx.interaction.followup
    send(content=message, ephemeral=True, allowed_mentions=NO_MENTIONS)


def _followup(ctx, **kwargs):
    ctx.interaction.followup(ephemeral=True, allowed_mentions=NO_MENTIONS, **kwargs)


def _store(ctx):
    return BuildStore(ctx.kv, ctx.server_id)


def _library(ctx, owner, page=1, *, notice=""):
    if type(page) is not int or not 1 <= page <= 100:
        raise ValueError("Choose a valid saved-library page.")
    records = _store(ctx).list_saved(owner)
    pages = max(1, (len(records) + PAGE_SIZE - 1) // PAGE_SIZE)
    if page > pages:
        raise ValueError("That saved-library page doesn't exist. Open My builds again.")
    selected = records[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]
    rows = []
    if selected:
        options = [SelectOption(clean_title(record.get("title")) or "MW4 build", record["id"],
                                description=record["code"][:100]) for record in selected]
        rows.append(ActionRow(SelectMenu("chl:open:" + owner, options=options,
                                         placeholder="Open a saved build", min_values=1, max_values=1)))
    navigation = []
    if page > 1:
        navigation.append(Button("Previous", custom_id=f"chl:list:{owner}:{page-1}", style="secondary"))
    if page < pages:
        navigation.append(Button("Next", custom_id=f"chl:list:{owner}:{page+1}", style="secondary"))
    navigation.append(Button("Home", custom_id="chh:private", style="secondary"))
    rows.append(ActionRow(*navigation))
    _followup(ctx, content=notice, embeds=[hub_cards.saved_embed(selected, page, pages, len(records))],
              components=rows)


def _show(ctx, record):
    # app imports this module while registering handlers; defer the reverse
    # import until the handler runs to avoid registration-time cycles.
    from .app import _show as show_build
    show_build(ctx, record, "s", ephemeral=True)


def handle_open(ctx, event, page=1):
    """Open the current person's library from either slash or hub entry points."""
    ctx.interaction.defer(ephemeral=True)
    try:
        _library(ctx, _actor(event), page)
    except Exception as error:
        _failure(ctx, error)


def _selected_id(event):
    values = event.get("values")
    if (not isinstance(values, list) or len(values) != 1
            or not isinstance(values[0], str) or not _IDENTIFIER.fullmatch(values[0])):
        raise ValueError("Choose exactly one saved build from the menu.")
    return values[0]


def _rename_form(ctx, event, owner, code):
    """Modal-first, with no KV call or record lookup before acknowledgment."""
    _check_owner(event, owner)
    # Only local codec/catalog work happens before opening this form. A forged
    # own-code button may open the form, but submission still requires a saved
    # record under the trusted submitter's owner key.
    from .catalog import resolve_build
    build = resolve_build(code, game="mw4")
    if build["code"] != code or len(code) > 25:
        raise ValueError("Open Rename from a saved build card.")
    ctx.interaction.send_modal(
        title="Rename saved build", custom_id=RENAME_MODAL,
        fields=[TextInput("Build code", "code", value=code, required=True, min_length=7, max_length=25),
                TextInput("New build name", "title", placeholder="My ranked build", required=True,
                          min_length=1, max_length=80)])


def handle_component(ctx, event):
    custom_id = str(event.get("custom_id") or "")
    rename = _RENAME.fullmatch(custom_id)
    if rename:
        try:
            _rename_form(ctx, event, *rename.groups())
        except Exception as error:
            _failure(ctx, error, initial=True)
        return
    ctx.interaction.defer(ephemeral=True)
    try:
        listed, opened, item = _LIST.fullmatch(custom_id), _OPEN.fullmatch(custom_id), _ITEM.fullmatch(custom_id)
        if listed:
            owner, page = listed.groups()
            _check_owner(event, owner)
            _library(ctx, owner, int(page))
            return
        if opened:
            owner = opened.group(1)
            _check_owner(event, owner)
            identifier = _selected_id(event)
            record = _store(ctx).get("s", owner, identifier)
            if record is None:
                raise ValueError("That saved build wasn't found in your library. Open My builds again.")
            _show(ctx, record)
            return
        if item:
            action, owner, identifier = item.groups()
            _check_owner(event, owner)
            store = _store(ctx)
            record = store.get("s", owner, identifier)
            if record is None:
                raise ValueError("That saved build wasn't found in your library. Open My builds again.")
            if action == "ask":
                title = _safe(clean_title(record.get("title")) or "MW4 build", 120)
                embed = {"title": "Delete saved build?", "description": "Remove **" + title
                         + "** from your private library? Shared cards are unaffected.", "color": COLOR,
                         "fields": [{"name": "Build code", "value": "`" + _safe(record["code"], 100) + "`"}]}
                _followup(ctx, embeds=[embed], components=[ActionRow(
                    Button("Delete build", custom_id=f"chl:delete:{owner}:{identifier}", style="danger"),
                    Button("Keep build", custom_id=f"chl:list:{owner}:1", style="secondary"))])
            else:
                if not store.delete(owner, identifier):
                    raise ValueError("That saved build was already removed. Open My builds again.")
                _library(ctx, owner, notice="Deleted the saved build from your private library.")
            return
        raise ValueError("That library control is invalid. Open My builds again.")
    except Exception as error:
        _failure(ctx, error)


def handle_rename(ctx, event):
    ctx.interaction.defer(ephemeral=True)
    try:
        owner = _actor(event)
        if event.get("custom_id") != RENAME_MODAL:
            raise ValueError("That rename form is invalid. Open Rename again.")
        values = event.get("modal_values")
        if not isinstance(values, dict):
            raise ValueError("Complete the build code and new name fields.")
        code, title = values.get("code"), values.get("title")
        if not isinstance(code, str) or not 0 < len(code) <= 25:
            raise ValueError("Use the saved MW4 build code.")
        if not isinstance(title, str) or not 0 < len(title) <= 80 or not clean_title(title):
            raise ValueError("Use a build name between 1 and 80 characters.")
        from .catalog import resolve_build
        canonical = resolve_build(code, game="mw4")["code"]
        record = _store(ctx).rename(owner, build_id("mw4", canonical), title)
        _show(ctx, record)
    except Exception as error:
        _failure(ctx, error)
