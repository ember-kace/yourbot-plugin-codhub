"""Private offline game-guide cards with explicit owner-only channel posting."""
import re

from yourbot_sdk import ActionRow, Button, SelectMenu, SelectOption

from . import native_guide as guide
from .cards import COLOR, _safe
from .hub import _pack, _unpack
from .hub_cards import _line
from .store import owner_id


NO_MENTIONS = {"parse": []}
CONTEXT_REQUIREMENTS = "Open the in-game challenge for contextual requirements."


def _id(action, owner, *parts):
    result = ":".join(("chg", action, owner, *(str(part) for part in parts)))
    if len(result) > 100 or any(":" in str(part) for part in parts):
        raise ValueError("Open /codguide for fresh game guide controls.")
    return result


def _page(value):
    if not re.fullmatch(r"[1-9][0-9]{0,3}", str(value)) or int(value) > 1000:
        raise ValueError("Choose a valid game guide page.")
    return int(value)


def _selected(event):
    values = event.get("values")
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], str) or len(values[0]) > 100:
        raise ValueError("Choose a reference from the guide menu.")
    return values[0]


def _reply(ctx, embed, controls, *, update=True, deferred=False):
    options = {"embeds": [embed], "components": controls, "ephemeral": True, "allowed_mentions": NO_MENTIONS}
    if not deferred:
        options.update(content="", update_message=update)
    method = ctx.interaction.followup if deferred else ctx.interaction.respond
    method(**options)


def _error(ctx, error, *, deferred=False):
    message = str(error)[:1800] if isinstance(error, ValueError) else "The game guide couldn't open. Try /codguide again."
    if not isinstance(error, ValueError):
        ctx.log("COD Hub native guide failed", level="error", error_type=type(error).__name__)
    method = ctx.interaction.followup if deferred else ctx.interaction.respond
    method(content=message, ephemeral=True, allowed_mentions=NO_MENTIONS)


def _category_options(selected="all"):
    return [SelectOption("All references", "all", default=selected == "all")] + [
        SelectOption(row["label"], row["key"], description=f"{row['resolved']} named references", default=selected == row["key"])
        for row in guide.categories() if row["resolved"]]


def home_view(owner):
    categories = guide.categories()
    description = "Explore map references and challenges from the packaged MW4 snapshot.\n\n"
    description += "\n".join("**" + _safe(row["label"], 100) + "** · " + str(row["resolved"]) for row in categories if row["resolved"])
    embed = {"title": "MW4 game guide", "description": description, "color": COLOR,
             "footer": {"text": "Reference snapshot " + guide.SNAPSHOT + " · Browse privately. Choose what to share."}}
    controls = [ActionRow(SelectMenu(_id("c", owner, "_"), _category_options(), placeholder="Choose a guide category")),
                ActionRow(Button("Browse all", custom_id=_id("p", owner, "all", 1, "_"), style="primary"),
                          Button("Search help", custom_id=_id("q", owner), style="secondary"),
                          Button("Wiki search", custom_id="chh:reference", style="secondary"),
                          Button("COD Hub", custom_id=_id("hub", owner), style="secondary"))]
    return embed, controls


def results_view(owner, payload):
    category, page, query = payload["category"], payload["page"], payload["query"]
    token = _pack(query)
    title = guide.CATEGORIES[category][0] if category != "all" else "All game guide references"
    description = "Search: **" + _safe(query, 100) + "**\n\n" if query else "Choose a reference to open its card.\n\n"
    description += "\n\n".join("**" + _safe(row["name"], 160) + "**\n"
                                 + _safe(guide.CATEGORIES[guide.category_for(row["kind"])][0], 100)
                                 for row in payload["items"])
    if not payload["items"]:
        description += "No verified names match. Try another category or a shorter search."
    embed = {"title": title, "description": description[:4096], "color": COLOR,
             "footer": {"text": f"{payload['total']} references · Page {page}/{payload['pages']} · Snapshot {payload['snapshot_date']}"}}
    controls = [ActionRow(SelectMenu(_id("c", owner, token), _category_options(category), placeholder="Choose a guide category"))]
    if payload["items"]:
        controls.append(ActionRow(SelectMenu(_id("i", owner, category, page, token), [
            SelectOption(_line(row["name"], 100), row["id"],
                         description=_line(row["internal_ref"] if row["kind"] == "map" else guide.CATEGORIES[guide.category_for(row["kind"])][0], 100))
            for row in payload["items"]], placeholder="Choose a guide reference")))
    buttons = []
    if page > 1:
        buttons.append(Button("Previous", custom_id=_id("p", owner, category, page - 1, token), style="secondary"))
    if page < payload["pages"]:
        buttons.append(Button("Next", custom_id=_id("p", owner, category, page + 1, token), style="secondary"))
    buttons += [Button("Guide home", custom_id=_id("h", owner), style="secondary"),
                Button("Search help", custom_id=_id("q", owner), style="secondary"),
                Button("COD Hub", custom_id=_id("hub", owner), style="secondary")]
    controls.append(ActionRow(*buttons))
    return embed, controls


def reference_view(owner, item, back=None):
    category = guide.category_for(item["kind"])
    text = item.get("description_display") if item.get("description_status") == "source_static_text" else None
    if not text:
        text = "Native MW4 map reference." if item["kind"] == "map" else CONTEXT_REQUIREMENTS
    fields = [{"name": "Category", "value": guide.CATEGORIES[category][0], "inline": True},
              {"name": "Reference ID", "value": "`" + item["id"] + "`", "inline": False}]
    if item["kind"] == "map":
        fields.append({"name": "Native map reference", "value": _safe(item["internal_ref"], 500), "inline": False})
    embed = {"title": _safe(item["name"], 240), "description": _safe(text, 1800), "color": COLOR, "fields": fields,
             "footer": {"text": "COD Hub · Native English reference · Snapshot " + item["snapshot_date"] + " · Check current availability in-game."}}
    back_category, page, query = back or (category, 1, "")
    controls = [ActionRow(Button("Post card to channel", custom_id=_id("s", owner, item["id"]), style="secondary")),
                ActionRow(Button("Back to references", custom_id=_id("p", owner, back_category, page, _pack(query)), style="secondary"),
                          Button("Guide home", custom_id=_id("h", owner), style="secondary"),
                          Button("COD Hub", custom_id=_id("hub", owner), style="secondary"))]
    return embed, controls


def handle_command(ctx, event):
    ctx.interaction.defer(ephemeral=True)
    try:
        raw = event.get("options", {})
        options = raw if isinstance(raw, dict) else {r["name"]: r.get("value") for r in raw if isinstance(r, dict) and "name" in r}
        owner = owner_id(event.get("user_id"))
        category, query, page = options.get("category", "all"), options.get("query", ""), options.get("page", 1)
        if category == "all" and query == "" and type(page) is int and page == 1:
            view = home_view(owner)
        else:
            view = results_view(owner, guide.browse(category, query, page))
        _reply(ctx, *view, deferred=True)
    except Exception as error:
        _error(ctx, error, deferred=True)


def _post(ctx, event, owner, identifier):
    ctx.interaction.defer(ephemeral=True)
    try:
        item = guide.get_reference(identifier)
        embed, _ = reference_view(owner, item)
        ctx.discord.send_message(channel_id=owner_id(event.get("channel_id")), embeds=[embed],
            components=[ActionRow(Button("Explore game guide", custom_id="chg:open", style="secondary"))], allowed_mentions=NO_MENTIONS)
        ctx.interaction.followup(content="Posted the reference card in this channel.", ephemeral=True, allowed_mentions=NO_MENTIONS)
    except Exception as error:
        _error(ctx, error, deferred=True)


def handle_component(ctx, event):
    if event.get("custom_id") == "chg:open":
        return handle_command(ctx, {"user_id": event.get("user_id")})
    try:
        owner = owner_id(event.get("user_id"))
        parts = str(event.get("custom_id") or "").split(":")
        if len(parts) < 3 or parts[0] != "chg" or parts[2] != owner:
            raise ValueError("Open /codguide to browse your own private guide.")
        action, args = parts[1], parts[3:]
        if action == "h" and not args:
            return _reply(ctx, *home_view(owner))
        if action == "hub" and not args:
            from . import hub, hub_cards
            return _reply(ctx, hub_cards.home_embed(), hub.home_controls())
        if action == "q" and not args:
            return ctx.interaction.respond(content="Search offline references with `/codguide query:<name>`. Add a category or page to narrow the results.",
                                           ephemeral=True, allowed_mentions=NO_MENTIONS)
        if action == "c" and len(args) == 1:
            category = _selected(event)
            return _reply(ctx, *results_view(owner, guide.browse(category, _unpack(args[0]))))
        if action in {"p", "i"} and len(args) == 3:
            category, page, query = args[0], _page(args[1]), guide.normalize_query(_unpack(args[2]))
            payload = guide.browse(category, query, page)
            if action == "p":
                return _reply(ctx, *results_view(owner, payload))
            identifier = _selected(event)
            if identifier not in {row["id"] for row in payload["items"]}:
                raise ValueError("Choose a reference from this page of the guide.")
            return _reply(ctx, *reference_view(owner, guide.get_reference(identifier), (category, page, query)))
        if action == "s" and len(args) == 1:
            return _post(ctx, event, owner, args[0])
        raise ValueError("Open /codguide for fresh game guide controls.")
    except Exception as error:
        _error(ctx, error)
