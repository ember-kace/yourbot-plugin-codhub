"""Small, bounded Discord embeds for COD Hub's interactive workspace.

These functions only present data. Navigation, ownership and posting are handled
by the interaction router; browsing pages do not create or share build records.
"""
import re
import unicodedata

from .cards import COLOR, _safe


PAGE_SIZE = 10
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")


def _line(value, maximum=140):
    """Keep user labels to one line and neutralize Markdown and mentions."""
    raw = "".join(" " if unicodedata.category(c).startswith("C") else c
                  for c in str(value or ""))
    return _safe(" ".join(raw.split()), maximum)


def _number(value, default=1):
    if type(value) is int and value >= 0:
        return min(value, 99999)
    return default


def _paging(page_data):
    pages = max(1, _number(page_data.get("pages"), 1))
    page = max(1, min(_number(page_data.get("page"), 1), pages))
    total = _number(page_data.get("total"), 0)
    return page, pages, total


def _snapshot(page_data, items):
    date = page_data.get("snapshot_date")
    if not date:
        date = next((item.get("snapshot_date") for item in items if item.get("snapshot_date")), None)
    return " · Snapshot " + date if isinstance(date, str) and _DATE.fullmatch(date) else ""


def home_embed():
    return {
        "title": "COD Hub",
        "description": "**Your next loadout starts here.**\n\nImport an MW4 code, compare weapons, or find a build to try.",
        "color": COLOR,
        "footer": {"text": "Personal cards open privately. You choose what to share."},
    }


def meta_home_embed():
    return {
        "title": "Meta builds",
        "description": "Choose a mode or game below, then filter recommendations by weapon type.\n\nMultiplayer and Warzone open in-card recommendations. DMZ opens its dedicated external-source card. BO7 loadouts are also available.",
        "color": COLOR,
        "footer": {"text": "Provider recommendations · Check each build's source and date"},
    }


def weapons_embed(page_data, class_label=None):
    """Present one already paginated weapon page; the router adds its selector."""
    items = [item for item in page_data.get("items", [])[:PAGE_SIZE] if isinstance(item, dict)]
    page, pages, total = _paging(page_data)
    title = "Explore weapons" + (" · " + _line(class_label, 70) if class_label else "")
    rows = []
    for item in items:
        name = _line(item.get("name"), 140) or "Weapon"
        prefix = _line(item.get("prefix"), 12)
        detail = "`" + prefix + "`" if prefix else "Reference weapon"
        if not class_label and item.get("class"):
            detail += " · " + _line(item["class"], 45)
        rows.append("**" + name + "**\n" + detail)
    description = "Choose a weapon below to open its card.\n\n" + "\n\n".join(rows) if rows else "No weapons match this view. Try another class or search."
    if page_data.get("query"):
        description = "Search: **" + _line(page_data["query"], 100) + "**\n\n" + description
    return {
        "title": title, "description": description[:4096], "color": COLOR,
        "footer": {"text": f"MW4 · {total} weapon{'s' if total != 1 else ''} · Page {page}/{pages}" + _snapshot(page_data, items)},
    }


def saved_embed(records, page=1, pages=1, total=None):
    """`records` contains only the selected page, never the entire library."""
    records = [record for record in records[:PAGE_SIZE] if isinstance(record, dict)]
    page_data = {"page": page, "pages": pages, "total": len(records) if total is None else total}
    page, pages, total = _paging(page_data)
    if not records:
        description = "Your next build starts here.\n\nImport a code, preview the card, and choose **Save**."
    else:
        rows = []
        for record in records:
            title = _line(record.get("title"), 140) or "MW4 build"
            code = _line(record.get("code"), 100)
            rows.append("**" + title + "**" + ("\n`" + code + "`" if code else ""))
        description = "Choose a saved build below to open its card.\n\n" + "\n\n".join(rows)
    return {
        "title": "My builds", "description": description[:4096], "color": COLOR,
        "footer": {"text": f"Private library · {total}/50 builds · Page {page}/{pages}"},
    }


def attachments_embed(weapon, page_data, slot=None):
    """Present an attachment page for one selected weapon and optional slot."""
    items = [item for item in page_data.get("items", [])[:PAGE_SIZE] if isinstance(item, dict)]
    page, pages, total = _paging(page_data)
    name = _line(weapon.get("name"), 130) or "Weapon"
    title = name + " · Attachments"
    slot_label = next((entry.get("label") for entry in page_data.get("slots", [])
                       if isinstance(entry, dict) and entry.get("key") == slot), slot)
    scope = _line(slot_label, 70) if slot else "All attachment categories"
    rows = []
    for item in items:
        label = _line(item.get("name"), 140) or "Attachment"
        category = _line(item.get("slot_label") or item.get("slot"), 65)
        rows.append("**" + label + "**" + ("\n" + category if category else ""))
    if rows:
        description = "**" + scope + "**\nChoose an attachment below for details.\n\n" + "\n\n".join(rows)
    else:
        description = "No named attachments are available in this view."
        if page_data.get("note"):
            description += "\n\n" + _line(page_data["note"], 300)
    return {
        "title": title, "description": description[:4096], "color": COLOR,
        "footer": {"text": f"MW4 · {total} attachment{'s' if total != 1 else ''} · Page {page}/{pages}" + _snapshot(page_data, items or [weapon])},
    }


def reference_home_embed():
    return {
        "title": "Explore Call of Duty",
        "description": "Look up maps, operators, camos, challenges, prestige and equipment.\n\nChoose **Search reference** and enter a name or topic.",
        "color": COLOR,
        "footer": {"text": "Dated wiki references · Check each article's game and source date"},
    }
