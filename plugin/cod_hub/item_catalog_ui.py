"""Private category and item cards for the structured native MW4 catalog."""
import re

from yourbot_sdk import ActionRow, Button, SelectMenu, SelectOption

from . import artwork, item_artwork, item_catalog, native_artwork
from .cards import COLOR, _safe
from .hub_cards import _line
from .store import owner_id


NO_MENTIONS = {"parse": []}
_NUMBER = re.compile(r"[0-9]{1,10}\Z")
_KIND = re.compile(r"[a-z][a-z0-9_]{0,39}\Z")
CATEGORIES_PER_PAGE = 24


def _actor(event):
    return owner_id(event.get("user_id"))


def _id(action, owner, *parts):
    value = ":".join(("chx", action, owner, *(str(part) for part in parts)))
    if len(value) > 100 or any(":" in str(part) for part in parts):
        raise ValueError("Open the catalog again for fresh controls.")
    return value


def _number(value, maximum=10000):
    if not _NUMBER.fullmatch(str(value)) or not 0 <= int(value) <= maximum:
        raise ValueError("Open an item from the catalog.")
    return int(value)


def _reply(ctx, embed, controls, *, update=False, content=""):
    ctx.interaction.respond(content=content, embeds=[embed], components=controls,
                            ephemeral=True, update_message=update, allowed_mentions=NO_MENTIONS)


def _error(ctx, error, *, deferred=False):
    message = str(error)[:1800] if isinstance(error, ValueError) else "The catalog couldn't open. Try /codcatalog again."
    if not isinstance(error, ValueError):
        ctx.log("COD Hub item catalog failed", level="error", error_type=type(error).__name__)
    method = ctx.interaction.followup if deferred else ctx.interaction.respond
    method(content=message, ephemeral=True, allowed_mentions=NO_MENTIONS)


def home_view(owner, page=1):
    all_rows = item_catalog.categories()
    rows = [row for row in all_rows if row["resolved"]]
    pages = max(1, (len(rows) + CATEGORIES_PER_PAGE - 1) // CATEGORIES_PER_PAGE)
    if not 1 <= page <= pages:
        raise ValueError("Choose a catalog category page.")
    chosen = rows[(page - 1) * CATEGORIES_PER_PAGE:page * CATEGORIES_PER_PAGE]
    total = sum(row["total"] for row in all_rows)
    resolved = sum(row["resolved"] for row in all_rows)
    details = "Choose a category to explore its items.\n\n"
    details += "\n".join("**" + _safe(row["label"], 80) + "** · " + str(row["resolved"]) + " named items"
                          for row in chosen)
    if total != resolved:
        details += f"\n\n{resolved:,} named items from {total:,} native records. Internal and unresolved records are counted separately."
    embed = {"title": "MW4 catalog", "description": details[:4096], "color": COLOR,
             "footer": {"text": f"Categories {page}/{pages} · Source snapshot {item_catalog.manifest()['snapshot_date']}"}}
    controls = [ActionRow(SelectMenu(_id("c", owner, page), [
        SelectOption(row["label"], row["key"], description=str(row["resolved"]) + " named items")
        for row in chosen], placeholder="Choose an item category"))]
    buttons = []
    if page > 1:
        buttons.append(Button("Previous categories", custom_id=_id("h", owner, page - 1), style="secondary"))
    if page < pages:
        buttons.append(Button("More categories", custom_id=_id("h", owner, page + 1), style="secondary"))
    buttons += [Button("All items", custom_id=_id("p", owner, "all", 1), style="secondary"),
                Button("Search help", custom_id=_id("q", owner), style="secondary"),
                Button("Hub", custom_id="chh:private", style="secondary")]
    controls.append(ActionRow(*buttons))
    return embed, controls


def _result_view(owner, payload):
    kind = payload["kind"]
    label = "All items" if kind == "all" else item_catalog.LABELS.get(kind, kind.replace("_", " ").title())
    query = payload.get("query")
    description = ("Search: **" + _safe(query, 100) + "**\n\n") if query else "Choose an item below for its details.\n\n"
    description += "\n\n".join("**" + _safe(item["name"], 150) + "**\n"
                                + _safe(item_catalog.LABELS.get(item["kind"], item["kind"].replace("_", " ").title()), 80)
                                for item in payload["items"])
    if not payload["items"]:
        description += "No named items match. Try a shorter name or another category."
    embed = {"title": label, "description": description[:4096], "color": COLOR,
             "footer": {"text": f"{payload['total']:,} results · Page {payload['page']}/{payload['pages']} · Snapshot {payload['snapshot_date']}"}}
    controls = []
    if payload["items"]:
        controls.append(ActionRow(SelectMenu(_id("i", owner), [
            SelectOption(_line(item["name"], 100), f"{item['kind']}:{item['shard']}:{item['id']}",
                         description=item_catalog.LABELS.get(item["kind"], item["kind"]))
            for item in payload["items"]], placeholder="Choose an item")))
    buttons = []
    # Search results are deliberately not encoded in public custom IDs. Refine
    # long result sets through the slash command; category paging stays local.
    if not query:
        if payload["page"] > 1:
            buttons.append(Button("Previous", custom_id=_id("p", owner, kind, payload["page"] - 1), style="secondary"))
        if payload["page"] < payload["pages"]:
            buttons.append(Button("Next", custom_id=_id("p", owner, kind, payload["page"] + 1), style="secondary"))
    buttons += [Button("Categories", custom_id=_id("h", owner, 1), style="secondary"),
                Button("Search help", custom_id=_id("q", owner), style="secondary"),
                Button("Hub", custom_id="chh:private", style="secondary")]
    controls.append(ActionRow(*buttons))
    if query and payload["pages"] > 1:
        embed["description"] += "\n\nUse `/codcatalog` with a more specific query or a page number for further results."
    return embed, controls


def item_view(owner, item):
    kind = item["kind"]
    fields = [{"name": "Category", "value": _safe(item_catalog.LABELS.get(kind, kind.replace("_", " ").title()), 100), "inline": True},
              {"name": "Catalog ID", "value": str(item["id"]), "inline": True}]
    if item.get("season"):
        fields.append({"name": "Season tag", "value": _safe(item["season"], 100), "inline": True})
    description = _safe(item.get("description") or "", 1800)
    if item.get("unlock"):
        fields.append({"name": "Unlock reference", "value": _safe(item["unlock"], 1000), "inline": False})
    embed = {"title": _safe(item_catalog.display_name(item), 180), "description": description or "Native MW4 catalog entry.",
             "color": COLOR, "fields": fields,
             "footer": {"text": "COD Hub · Native English reference · Snapshot " + item["snapshot_date"]}}
    if item.get("classification") == "blueprint_variant":
        embed["fields"].append({"name": "Variant", "value": "Uses the native base attachment name." if item.get("name_source") == "native_baseref" else "Native blueprint variant.", "inline": False})
    if item.get("name_source") == "native_frontend_label":
        embed["footer"]["text"] = "COD Hub · Native English frontend label · Snapshot " + item["snapshot_date"]
    if item.get("name_source") == "native_default_variant":
        embed["footer"]["text"] = "COD Hub · Native English default-variant label · Snapshot " + item["snapshot_date"]
    if item.get("name_source") == "native_context_labels":
        embed["description"] += "\n\nNative labels vary by context."
    item_artwork.decorate_embed(embed, item)
    if kind == "weapon" and native_artwork.get_art(item):
        embed.pop("thumbnail", None)
        embed = artwork.decorate_embed(embed, item)
    controls = [ActionRow(Button("Browse category", custom_id=_id("p", owner, kind, 1), style="secondary"),
                          Button("Categories", custom_id=_id("h", owner, 1), style="secondary"),
                          Button("Hub", custom_id="chh:private", style="secondary"))]
    return embed, controls


def _post_item(ctx, event, owner, kind, shard, identifier):
    ctx.interaction.defer(ephemeral=True)
    try:
        item = item_catalog.get_item(kind, shard, identifier)
        embed, _ = item_view(owner, item)
        ctx.discord.send_message(channel_id=owner_id(event.get("channel_id")), embeds=[embed],
            components=[ActionRow(Button("Explore catalog", custom_id="chx:open", style="secondary"))],
            allowed_mentions=NO_MENTIONS)
        ctx.interaction.followup(content="Posted the item card in this channel.", ephemeral=True, allowed_mentions=NO_MENTIONS)
    except Exception as error:
        _error(ctx, error, deferred=True)


def handle_open(ctx, event):
    ctx.interaction.defer(ephemeral=True)
    try:
        embed, controls = home_view(_actor(event))
        ctx.interaction.followup(embeds=[embed], components=controls, ephemeral=True, allowed_mentions=NO_MENTIONS)
    except Exception as error:
        _error(ctx, error, deferred=True)


def handle_command(ctx, event):
    ctx.interaction.defer(ephemeral=True)
    try:
        raw = event.get("options", {})
        options = raw if isinstance(raw, dict) else {row["name"]: row.get("value") for row in raw if isinstance(row, dict) and "name" in row}
        owner = _actor(event)
        kind, query, page = options.get("category", "all"), options.get("query", ""), options.get("page", 1)
        if not query and kind == "all" and page == 1:
            embed, controls = home_view(owner)
        else:
            embed, controls = _result_view(owner, item_catalog.browse(kind, query, page))
        ctx.interaction.followup(embeds=[embed], components=controls, ephemeral=True, allowed_mentions=NO_MENTIONS)
    except Exception as error:
        _error(ctx, error, deferred=True)


def handle_component(ctx, event):
    if event.get("custom_id") == "chx:open":
        return handle_open(ctx, event)
    try:
        owner = _actor(event)
        parts = str(event.get("custom_id") or "").split(":")
        if len(parts) < 3 or parts[0] != "chx" or parts[2] != owner:
            raise ValueError("Open /codcatalog to browse your own view.")
        action, args = parts[1], parts[3:]
        if action == "h" and len(args) == 1:
            return _reply(ctx, *home_view(owner, _number(args[0])))
        if action == "c" and len(args) == 1:
            page = _number(args[0])
            if page < 1:
                raise ValueError("Choose a catalog category page.")
            rows = [row for row in item_catalog.categories() if row["resolved"]][(page - 1) * CATEGORIES_PER_PAGE:page * CATEGORIES_PER_PAGE]
            values = event.get("values", [])
            if not isinstance(values, list) or len(values) != 1 or values[0] not in {row["key"] for row in rows}:
                raise ValueError("Choose a category from this page.")
            return _reply(ctx, *_result_view(owner, item_catalog.browse(values[0])))
        if action == "p" and len(args) == 2:
            return _reply(ctx, *_result_view(owner, item_catalog.browse(args[0], page=_number(args[1]))), update=True)
        if action == "i" and not args:
            values = event.get("values", [])
            if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], str):
                raise ValueError("Choose an item from the menu.")
            selected = values[0].split(":")
            if len(selected) != 3 or not _KIND.fullmatch(selected[0]):
                raise ValueError("Choose an item from the menu.")
            item = item_catalog.get_item(selected[0], _number(selected[1]), _number(selected[2], 2**31 - 1))
            embed, controls = item_view(owner, item)
            controls.insert(0, ActionRow(Button("Post card to channel", custom_id=_id("s", owner, *selected), style="secondary")))
            return _reply(ctx, embed, controls)
        if action == "s" and len(args) == 3 and _KIND.fullmatch(args[0]):
            return _post_item(ctx, event, owner, args[0], _number(args[1]), _number(args[2], 2**31 - 1))
        if action == "q" and not args:
            return ctx.interaction.respond(content="Search by item name with `/codcatalog query:<name>`. Add a category to narrow the results.",
                                           ephemeral=True, allowed_mentions=NO_MENTIONS)
        raise ValueError("Open /codcatalog for fresh catalog controls.")
    except Exception as error:
        _error(ctx, error)
