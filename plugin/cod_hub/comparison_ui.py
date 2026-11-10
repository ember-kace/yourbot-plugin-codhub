"""Private weapon/build comparisons and explicitly published chart attachments."""
import base64
import re

from yourbot_sdk import ActionRow, Button, SelectMenu, SelectOption, TextInput

from . import catalog, comparison, telemetry
from .cards import COLOR, WARNING, _safe, _link
from .store import owner_id

NO_MENTIONS = {"parse": []}
MODAL = "chc:compare:v1"
VIEWS = {"overview": "Overview", "dps": "DPS by distance", "recoil": "Recoil / gun kick", "sway": "Aiming sway",
         "details": "Measurements / sources"}
MODE_KEYS = {"m": "multiplayer", "d": "dmz", "w": "warzone"}
VIEW_KEYS = {"o": "overview", "d": "dps", "r": "recoil", "s": "sway", "i": "details"}
LOCATION_KEYS = {"b": "base_profile", "h": "head", "n": "neck", "u": "upper_torso", "l": "lower_torso",
                 "a": "upper_arm", "f": "lower_arm", "t": "upper_leg", "k": "lower_leg", "x": "body"}


def _actor(event):
    return owner_id(event.get("user_id"))


def _reverse(table, value):
    try:
        return next(key for key, candidate in table.items() if candidate == value)
    except StopIteration:
        raise ValueError("That comparison option is invalid.") from None


def _token(subject):
    return "c" + subject["code"] if subject["code"] else "w" + str(subject["weapon"].get("prefix") or subject["weapon"]["asset_id"])


def _input(token):
    if re.fullmatch(r"w(?:[A-Z][0-9]{2}|[0-9a-f]{16})", token):
        return token[1:]
    if re.fullmatch(r"c[A-Z][0-9]{2}-[A-Z0-9-]{3,21}", token):
        return token[1:]
    raise ValueError("That comparison control is invalid. Start a new comparison.")


def _state(result, view, location):
    return [_reverse(MODE_KEYS, result["mode"]), _token(result["left"]), _token(result["right"]),
            _reverse(VIEW_KEYS, view), _reverse(LOCATION_KEYS, location)]


def _id(action, owner, state, *extra):
    value = ":".join(["chc", action, owner, *state, *extra])
    if len(value) > 100:
        raise ValueError("This comparison cannot fit in a card control. Try shorter canonical inputs.")
    return value


def _selection(event, allowed):
    values = event.get("values")
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], str) or values[0] not in allowed:
        raise ValueError("Choose one comparison option from the menu.")
    return values[0]


def _resolve(left, right, mode, location):
    profiles, fingerprint = telemetry.snapshot(mode)
    result = comparison.compare(left, right, mode=mode, profiles=profiles, hit_location=location)
    result["telemetry_fingerprint"] = fingerprint
    common = None
    for side in (result["left"], result["right"]):
        profile = profiles.get(side["key"])
        if profile is None and not side["attachments"]:
            profile = profiles.get(side["weapon"]["asset_id"])
        values = set(profile.get("dps", {}).get("damage_ranges", [{}])[0].get("damage", {})) if profile else set()
        common = values if common is None else common & values
    result["hit_location_options"] = [key for key in LOCATION_KEYS.values() if key in (common or set())]
    return result


def _source_dates(metric):
    rows = []
    seen = set()
    for series in metric.get("series", []):
        provenance = series["provenance"]
        components = provenance.get("components") or [{"metric": "Measurements", **provenance}]
        for item in components:
            key = (item["metric"], item["source_url"], item["source_date"])
            if key not in seen:
                seen.add(key)
                rows.append(str(item["metric"]).title() + " · " + item["source_date"])
    return "\n".join(dict.fromkeys(rows))


def _value(value):
    if value is None:
        return "Not verified"
    return f"{value:g}" if type(value) in (int, float) else _safe(value, 100)


def _append_rows(fields, name, lines):
    if not lines:
        return
    chunks, current = [], ""
    for line in lines[:15]:
        if current and len(current) + len(line) + 1 > 900:
            chunks.append(current)
            current = ""
        current += ("\n" if current else "") + line
    if current:
        chunks.append(current)
    for index, text in enumerate(chunks[:3]):
        fields.append({"name": name + (" (continued)" if index else ""), "value": text[:1000], "inline": False})


def _identity(result):
    return ("**A:** " + _safe(result["left"]["label"], 150) + "\n**B:** " + _safe(result["right"]["label"], 150)
            + "\n**Modern Warfare 4 · " + result["mode_label"] + "**")


def _detail_pages(result):
    """Pack complete paragraphs and links into bounded, navigable detail pages."""
    blocks = []
    def add(title, text, url=None):
        prefix, current = "**" + title + "**\n", ""
        for line in text.split("\n"):
            if current and len(prefix) + len(current) + len(line) + 1 > 1900:
                blocks.append({"body": prefix + current, "url": url}); current = ""
                prefix = "**" + title + " (continued)**\n"
            current += ("\n" if current else "") + line
        blocks.append({"body": prefix + current, "url": url})

    add("Reading this comparison", "\n".join(_safe(note, 600) for note in result["notes"]))
    base = result["base_stats"]
    if base["rows"]:
        lines = []
        for row in base["rows"]:
            lines.append(_safe(row["label"]) + " (" + row["unit"] + "): A " + _value(row["left"]) + " · B " + _value(row["right"]) +
                         "\nA date: " + str(row["left_date"] or "Not verified") + " · B date: " + str(row["right_date"] or "Not verified"))
        add("Launch catalog references", "\n".join(lines) + "\n" + base["note"] + "\n" +
            _link("Dated launch catalog source", "https://codloadout.gitlab.io/data/mw4.json"))
    for side, subject in (("A", result["left"]), ("B", result["right"])):
        if subject["code"]:
            add(side + " build selections", "`" + subject["code"] + "`\n" + ("\n".join(
                _safe(part["slot_label"]) + ": " + _safe(part["name"]) for part in subject["attachments"])
                or "Base weapon; no attachments selected."))
    add("Attachment comparison", result["attachment_diff"]["note"])
    context, blocks = blocks, []
    seen_sources, seen_limits = set(), set()
    for metric_key, metric in result["metrics"].items():
        if not metric["available"]:
            add(VIEWS[metric_key], "Not available. " + _safe(metric["reason"], 1200))
            continue
        for series in metric["series"]:
            label = ("A · " if series["side"] == "left" else "B · ") + _safe(series["label"], 150)
            provenance = series["provenance"]
            definitions = ["Patch: " + _safe(provenance["patch"], 300), "Method: " + _safe(provenance["method"], 600)]
            if metric_key == "dps":
                definitions += [series["hit_location_label"], series["region_note"], series["model"]]
            else:
                for key in ("unit", "condition", "stance", "statistic", "sample_count"):
                    if series.get(key) is not None:
                        definitions.append(key.replace("_", " ").title() + ": " + _safe(series[key], 600))
            add(VIEWS[metric_key] + " · " + label, "\n".join(definitions))
            components = provenance.get("components") or [{"metric": "Measurements", **provenance}]
            if not any(source["source_url"] == provenance["source_url"] and source["source_date"] == provenance["source_date"] for source in components):
                components = [*components, {"metric": "Measurement provenance", **provenance}]
            for source in components:
                key = (source["metric"], source["source_url"], source["source_date"], source.get("patch"), source.get("note"))
                if key in seen_sources:
                    continue
                seen_sources.add(key)
                source_label = str(source["metric"]).title() + " · " + source["source_date"]
                text = _link(source_label, source["source_url"])
                source_url = None
                if len(text) > 2700:
                    # Expanded Markdown escaping can exceed the prose limit;
                    # an intact title URL still preserves its exact destination.
                    source_url = source["source_url"]
                    text = _safe(source_label, 300) + "\nOpen this card's title for the complete source."
                if source.get("patch"):
                    text += "\nPatch: " + _safe(source["patch"], 600)
                if source.get("note"):
                    text += "\n" + _safe(source["note"], 600)
                add("Measurement source", text, source_url)
            for caveat in provenance.get("caveats", []):
                if caveat not in seen_limits:
                    add("Measurement limit", _safe(caveat, 600))
                    seen_limits.add(caveat)
    blocks.extend(context)
    pages, current = [], ""
    for block in blocks:
        # Source links can be up to 2,048 characters; never cut a destination.
        text = block["body"]
        if len(text) > 3450:
            raise ValueError("A measurement note is too long for a complete details page.")
        if current and (block["url"] or len(current) + len(text) + 2 > 1900):
            pages.append({"body": current}); current = ""
        if block["url"]:
            pages.append(block)
            continue
        current += ("\n\n" if current else "") + text
    if current:
        pages.append({"body": current})
    return pages or [{"body": "No measurement sources are available for these selections."}]


def _detail_embed(result, page):
    pages = _detail_pages(result)
    if type(page) is not int or not 0 <= page < len(pages):
        raise ValueError("That measurement page does not exist. Open Measurements / sources again.")
    result_embed = {"title": "Measurements / sources", "description": _identity(result) + "\n\n" + pages[page]["body"], "color": COLOR,
            "footer": {"text": f"COD Hub · Details {page + 1}/{len(pages)} · Dated measurements; no current-balance claim"}}
    if pages[page].get("url"):
        result_embed["url"] = pages[page]["url"]
    return result_embed


def _summary_rows(fields, name, lines):
    if not lines:
        return
    kept = []
    for line in lines[:3]:
        if len("\n".join(kept + [line])) > 760:
            break
        kept.append(line)
    if len(kept) < len(lines):
        kept.append(f"… {len(lines) - len(kept)} more in Measurements / sources")
    fields.append({"name": name, "value": "\n".join(kept), "inline": False})


def _available_views(result):
    return {key: label for key, label in VIEWS.items()
            if key in {"overview", "details"} or result["metrics"][key]["available"]}


def _graph_metric(result, view):
    if view in {"overview", "details"}:
        return next((key for key, metric in result["metrics"].items() if metric["available"]), None)
    return view if result["metrics"][view]["available"] else None


def _coverage(result):
    available = [VIEWS[key] for key, metric in result["metrics"].items() if metric["available"]]
    missing = [VIEWS[key] for key, metric in result["metrics"].items() if not metric["available"]]
    lines = ["Available: " + ", ".join(available) + "." if available else
             "No reviewed graphs match these selections in this mode."]
    if missing:
        lines.append("Needs matching reviewed measurements: " + ", ".join(missing) + ".")
    lines.append("Measurements / sources explains coverage, dates and limits.")
    return "\n".join(lines)


def comparison_embed(result, view="overview", detail_page=0, *, presentation="private"):
    if view not in VIEWS:
        raise ValueError("Choose a comparison view from the menu.")
    if presentation not in {"private", "shared", "graph"}:
        raise ValueError("Choose a valid comparison presentation.")
    if view == "details":
        return _detail_embed(result, detail_page)
    description = _identity(result)
    fields = []
    for label, subject in (("A", result["left"]), ("B", result["right"])):
        if subject["code"]:
            fields.append({"name": label + " build code", "value": "`" + subject["code"] + "`", "inline": True})
    if view == "overview":
        description += "\nDated launch references; mode changes and attachment effects are not applied."
        lines = []
        for row in result["base_stats"]["rows"]:
            value = _safe(row["label"]) + ": A **" + _value(row["left"]) + "** · B **" + _value(row["right"]) + "** " + row["unit"]
            if row["delta"] is not None:
                value += f" (A − B {row['delta']:+g})"
            lines.append(value)
        if lines:
            dates = sorted({row[key] for row in result["base_stats"]["rows"] for key in ("left_date", "right_date") if row[key]})
            _summary_rows(fields, "Base references · " + ", ".join(dates), lines)
        diff = result["attachment_diff"]
        if diff["common"]:
            fields.append({"name": "Shared selections", "value": str(len(diff["common"])) + " identical attachments · full selections in Measurements / sources", "inline": False})
        _summary_rows(fields, "Changed selections", [_safe(a["slot_label"]) + ": A " + _safe(a["left"]["name"]) + " → B " + _safe(a["right"]["name"]) for a in diff["changed"]])
        for label, key in (("Only A", "left_only"), ("Only B", "right_only")):
            _summary_rows(fields, label, [_safe(a["slot_label"]) + ": " + _safe(a["name"]) for a in diff[key]])
        if not diff["comparable"] and (diff["left_only"] or diff["right_only"]):
            description += "\nAttachments are weapon-specific; their performance is not equated."
        fields.append({"name": "Chart coverage", "value": _coverage(result), "inline": False})
    else:
        metric = result["metrics"][view]
        if not metric["available"]:
            description += "\n\n**" + VIEWS[view] + " is not available for this comparison.**"
            fields.append({"name": "Missing measurements", "value": _safe(metric["reason"], 950), "inline": False})
            description += "\nUse Overview for selections. Missing measurements are not estimated."
        else:
            instruction = {"private": "Choose **Post graphs to channel** to display the chart here.",
                           "shared": "Open comparison to explore privately or post its graph.",
                           "graph": "Chart posted below. Open comparison to explore privately."}[presentation]
            description += "\n\n**" + VIEWS[view] + "** · " + instruction
            if view == "dps":
                for series in metric["series"]:
                    lines = [f"{band['min_m']:g}–{band['max_m']:g} m: **{band['dps']:.2f} DPS**" for band in series["segments"]]
                    fields.append({"name": ("A · " if series["side"] == "left" else "B · ") + _safe(series["label"], 100), "value": "\n".join(lines)[:950], "inline": True})
                series = metric["series"][0]
                fields.append({"name": series["hit_location_label"], "value": series["region_note"] + "\nTheoretical automatic fire; all projectiles hit. Excludes reloads, misses and armor; not real TTK.", "inline": False})
            else:
                for series in metric["series"]:
                    fields.append({"name": ("A · " if series["side"] == "left" else "B · ") + _safe(series["label"], 100),
                                   "value": f"{len(series['points'])} reviewed points · {series['unit']}\n" + _safe(series.get("condition") or series.get("stance") or "Declared source conditions", 200), "inline": True})
            fields.append({"name": "Source dates", "value": _source_dates(metric) + "\nFull links, conditions and limits: Measurements / sources.", "inline": False})
            description += "\nDated measurements; later hotfix completeness is unverified."
    footer = {"private": "Post to channel and Post graphs to channel publish here",
              "shared": "Open comparison to explore privately",
              "graph": "Complete source notes attached"}[presentation]
    embed = {"title": "Weapon / build comparison", "description": description[:1800],
             "fields": fields[:24], "color": COLOR if view == "overview" or result["metrics"][view]["available"] else WARNING,
             "footer": {"text": "COD Hub · Dated source values · " + footer}}
    # Bound the combined Discord embed text while keeping the identity/context.
    length = len(embed["title"]) + len(embed["description"]) + len(embed["footer"]["text"])
    kept = []
    for field in embed["fields"]:
        amount = len(field["name"]) + len(field["value"])
        if length + amount > 5900:
            break
        kept.append(field); length += amount
    embed["fields"] = kept
    return embed


def _locations(result):
    return list(result.get("hit_location_options", []))


def controls(result, owner, view, location, detail_page=0):
    state = _state(result, view, location)
    rows = [ActionRow(SelectMenu(_id("m", owner, state), [SelectOption(label, key, default=key == result["mode"]) for key, label in comparison.MODES.items()], placeholder="Comparison mode")),
            ActionRow(SelectMenu(_id("v", owner, state), [SelectOption(label, key, default=key == view) for key, label in _available_views(result).items()], placeholder="Comparison view"))]
    locations = _locations(result)
    if view == "dps" and len(locations) > 1:
        rows.append(ActionRow(SelectMenu(_id("l", owner, state), [SelectOption(comparison.HIT_LOCATION_LABELS[key], key, default=key == location) for key in locations], placeholder="Damage profile / hit location")))
    if view == "details":
        count = len(_detail_pages(result))
        rows.append(ActionRow(
            Button("Previous details", custom_id=_id("n", owner, state, str(max(0, detail_page - 1))), style="secondary", disabled=detail_page == 0),
            Button("Next details", custom_id=_id("n", owner, state, str(min(count - 1, detail_page + 1))), style="secondary", disabled=detail_page == count - 1)))
    graph_available = _graph_metric(result, view) is not None
    rows.append(ActionRow(Button("New comparison", custom_id="chc:open", style="secondary"),
        Button("Swap A / B", custom_id=_id("s", owner, state), style="secondary"),
        Button("Home", custom_id="chh:private", style="secondary")))
    rows.append(ActionRow(
        Button("Post to channel", custom_id=_id("p", owner, state, *([str(detail_page)] if view == "details" else [])), style="secondary" if graph_available else "primary"),
        Button("Post graphs to channel", custom_id=_id("g", owner, state), style="primary" if graph_available else "secondary", disabled=not graph_available)))
    return rows


def _setup_id(action, owner, target, left="_", right="_", class_key="all", page=1):
    value = ":".join(("chc", action, owner, target, left, right, class_key, str(page)))
    if len(value) > 100:
        raise ValueError("This setup cannot fit in a card control. Start a new comparison.")
    return value


def _setup_subject(token):
    return None if token == "_" else comparison.resolve_subject(_input(token))


def setup_view(owner, target="a", left="_", right="_", class_key="all", page=1):
    """Choose two exact catalog weapons without requiring a modal dialog."""
    if target not in {"a", "b"}:
        raise ValueError("Choose selection A or B.")
    subjects = [_setup_subject(left), _setup_subject(right)]
    weapons = catalog.browse_weapons(class_key, page=page)
    class_key = weapons["class_key"] or "all"
    fields = []
    for side, subject in zip(("A", "B"), subjects):
        value = "Not selected"
        if subject:
            value = _safe(subject["label"], 180)
            if subject["code"]:
                value += "\n`" + subject["code"] + "`"
        fields.append({"name": "Selection " + side, "value": value, "inline": True})
    ready = all(subjects)
    embed = {"title": "Set up a comparison", "color": COLOR,
        "description": ("**1. Choose A · 2. Choose B · 3. Compare**\n"
            "Choose a weapon below for **" + target.upper() + "**. Use the class filter or page buttons to find it.\n"
            "Have build codes or exact names? Choose **Paste names / codes**.\n\n"
            + ("Both selections are ready. Choose **Compare A / B**." if ready else
               "Select both weapons to enable **Compare A / B**.")
            + "\nStarts in Multiplayer; change mode or view on the result card."),
        "fields": fields, "footer": {"text": "Multiplayer · Private setup · Posting is a separate action on the result card"}}
    def control(action, **changes):
        values = {"target": target, "left": left, "right": right, "class_key": class_key, "page": page}
        values.update(changes)
        return _setup_id(action, owner, **values)
    rows = [ActionRow(
        Button("Choose A", custom_id=control("x", target="a"), style="primary" if target == "a" and not ready else "secondary"),
        Button("Choose B", custom_id=control("x", target="b"), style="primary" if target == "b" and not ready else "secondary"))]
    classes = catalog.list_weapon_classes()
    rows.append(ActionRow(SelectMenu(control("k"), [SelectOption("All classes", "all", default=class_key == "all")]
        + [SelectOption(item["label"], item["key"], default=class_key == item["key"]) for item in classes],
        placeholder="Filter comparison weapons")))
    if weapons["items"]:
        rows.append(ActionRow(SelectMenu(control("w"), [SelectOption(item["name"], item["id"],
            description=item.get("class") or "Base weapon") for item in weapons["items"]],
            placeholder="Choose weapon for " + target.upper())))
    if weapons["pages"] > 1:
        rows.append(ActionRow(
            Button("Previous weapons", custom_id=control("x", page=max(1, page - 1)), style="secondary", disabled=page == 1),
            Button("Next weapons", custom_id=control("x", page=min(weapons["pages"], page + 1)), style="secondary", disabled=page == weapons["pages"])))
    rows.append(ActionRow(
        Button("Paste names / codes", custom_id=control("f"), style="secondary"),
        Button("Compare A / B", custom_id=control("r"), style="primary" if ready else "secondary", disabled=not ready),
        Button("Home", custom_id="chh:private", style="secondary")))
    return embed, rows


def _show_setup(ctx, owner, target="a", left="_", right="_", class_key="all", page=1, *, update=False, content="", followup=False):
    embed, rows = setup_view(owner, target, left, right, class_key, page)
    if followup:
        ctx.interaction.followup(content=content, embeds=[embed], components=rows, ephemeral=True,
                                 allowed_mentions=NO_MENTIONS)
    else:
        ctx.interaction.respond(content=content, embeds=[embed], components=rows, ephemeral=True,
                                update_message=update, allowed_mentions=NO_MENTIONS)


def _form(ctx, left="", right=""):
    ctx.interaction.send_modal(title="Compare: paste names or build codes", custom_id=MODAL, fields=[
        TextInput("A: weapon name or MW4 build code", "left", value=left, placeholder="Kastov 762, A01 or A01-42J19-BU11", max_length=256),
        TextInput("B: weapon name or MW4 build code", "right", value=right, placeholder="M4, A05 or another MW4 build code", max_length=256)])


def _show(ctx, result, owner, view="overview", location="base_profile", update=False, initial=False, detail_page=0):
    send = ctx.interaction.respond if initial or update else ctx.interaction.followup
    kwargs = {"embeds": [comparison_embed(result, view, detail_page)], "components": controls(result, owner, view, location, detail_page),
              "ephemeral": True, "allowed_mentions": NO_MENTIONS}
    if update:
        kwargs["update_message"] = True
    send(**kwargs)


def handle_command(ctx, event):
    from .app import _failure, _options
    ctx.interaction.defer(ephemeral=True)
    try:
        options = _options(event)
        mode = comparison.normalize_mode(options.get("mode") or "multiplayer")
        view = options.get("view") or "overview"
        location = options.get("hit_location") or "base_profile"
        result = _resolve(options.get("left"), options.get("right"), mode, location)
        _show(ctx, result, _actor(event), view, location)
    except Exception as error:
        _failure(ctx, error)


def handle_modal(ctx, event):
    from .app import _failure
    ctx.interaction.defer(ephemeral=True)
    try:
        values = event.get("modal_values")
        if not isinstance(values, dict):
            raise ValueError("Enter two weapon names, prefixes or MW4 build codes.")
        owner = _actor(event)
        subjects, errors = [], []
        for label, key in (("A", "left"), ("B", "right")):
            try:
                subjects.append(comparison.resolve_subject(values.get(key)))
            except ValueError as error:
                subjects.append(None)
                errors.append("**" + label + " needs another selection.** " + _safe(str(error), 300))
        tokens = [_token(subject) if subject else "_" for subject in subjects]
        if errors:
            target = "a" if subjects[0] is None else "b"
            kept = [label for label, subject in zip(("A", "B"), subjects) if subject]
            if kept:
                errors.append("Selection **" + kept[0] + "** is kept. Choose a weapon for **" + target.upper() + "** below, or reopen **Paste names / codes**.")
            else:
                errors.append("Choose A and B below, or reopen **Paste names / codes**.")
            return _show_setup(ctx, owner, target, *tokens, content="\n\n".join(errors), followup=True)
        result = _resolve(_input(tokens[0]), _input(tokens[1]), "multiplayer", "base_profile")
        _show(ctx, result, _actor(event))
    except Exception as error:
        _failure(ctx, error, components=[ActionRow(
            Button("Choose weapons", custom_id="chc:open", style="primary"),
            Button("Home", custom_id="chh:private", style="secondary"))])


def _public_controls(result, owner, view, location, *, graph_bundle=False):
    state = _state(result, view, location)
    available = [key for key, value in result["metrics"].items() if value["available"]]
    rows = []
    if graph_bundle and len(available) > 1:
        fingerprint = result.get("telemetry_fingerprint")
        if not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9a-f]{8}", fingerprint):
            raise ValueError("The measurement snapshot is unavailable. Open a fresh comparison.")
        rows.append(ActionRow(SelectMenu(_id("t", owner, state, fingerprint),
            [SelectOption(VIEWS[key], key, default=key == view) for key in available], placeholder="Graph view")))
    copy_id = ":".join(["chc", "copy", *state])
    details_id = ":".join(["chc", "copy", *_state(result, "details", location)])
    rows.append(ActionRow(Button("Open comparison", custom_id=copy_id, style="primary"),
        Button("Measurements / sources", custom_id=details_id, style="secondary"), Button("Hub", custom_id="chh:private", style="secondary")))
    return rows


def handle_component(ctx, event):
    from .app import _failure
    deferred = False
    modal_recovery = None
    try:
        owner = _actor(event)
        raw = event.get("custom_id")
        if not isinstance(raw, str) or len(raw) > 100:
            raise ValueError("That comparison control is invalid.")
        if raw == "chc:open":
            return _show_setup(ctx, owner)
        if raw.startswith("chc:open:"):
            subject = comparison.resolve_subject(_input(raw[len("chc:open:"):]))
            return _show_setup(ctx, owner, "b", _token(subject))
        parts = raw.split(":")
        if len(parts) >= 2 and parts[1] in {"x", "k", "w", "f", "r"}:
            if len(parts) != 8 or parts[0] != "chc" or parts[2] != owner:
                raise ValueError("This setup belongs to another person. Open your own comparison.")
            action, target, left, right, class_key, page_value = parts[1], *parts[3:]
            if target not in {"a", "b"} or not re.fullmatch(r"[1-9][0-9]{0,2}", page_value):
                raise ValueError("That comparison setup is invalid. Start a new comparison.")
            page = int(page_value)
            subjects = [_setup_subject(left), _setup_subject(right)]
            choices = catalog.browse_weapons(class_key, page=page)
            if action == "k":
                class_key = _selection(event, {"all", *(item["key"] for item in catalog.list_weapon_classes())})
                page = 1
            elif action == "w":
                selected = _selection(event, {item["id"] for item in choices["items"]})
                token = _token(comparison.resolve_subject(selected))
                if target == "a":
                    left = token
                    target = "b" if right == "_" else "a"
                else:
                    right = token
            elif action == "f":
                modal_recovery = (target, left, right, class_key, page)
                values = [subject["code"] or subject["weapon"]["name"] if subject else "" for subject in subjects]
                return _form(ctx, *values)
            elif action == "r":
                if not all(subjects):
                    raise ValueError("Choose both A and B before comparing.")
                result = _resolve(_input(left), _input(right), "multiplayer", "base_profile")
                return _show(ctx, result, owner, initial=True, update=True)
            return _show_setup(ctx, owner, target, left, right, class_key, page, update=True)
        clone = len(parts) == 7 and parts[:2] == ["chc", "copy"]
        if clone:
            action, args = "copy", parts[2:]
        else:
            if len(parts) not in (8, 9) or parts[0] != "chc" or parts[2] != owner:
                raise ValueError("This comparison belongs to another person. Open your own comparison.")
            action, args = parts[1], parts[3:]
        if args[0] not in MODE_KEYS or args[3] not in VIEW_KEYS or args[4] not in LOCATION_KEYS:
            raise ValueError("Choose a valid comparison view.")
        mode, view, location = MODE_KEYS[args[0]], VIEW_KEYS[args[3]], LOCATION_KEYS[args[4]]
        detail_page = 0
        left, right = _input(args[1]), _input(args[2])
        if action == "m":
            mode = _selection(event, comparison.MODES)
            location = "base_profile"
        elif action == "v":
            view = _selection(event, VIEWS)
        elif action == "s":
            left, right = right, left
        elif action == "t":
            if len(args) != 6 or not re.fullmatch(r"[0-9a-f]{8}", args[5]):
                raise ValueError("Measurement data changed. Post a fresh comparison graph.")
            view = _selection(event, ("dps", "recoil", "sway"))
        elif action == "n":
            if view != "details" or len(args) != 6 or not re.fullmatch(r"[0-9]{1,3}", args[5]):
                raise ValueError("Choose a valid measurement details page.")
            detail_page = int(args[5])
        elif action == "p" and view == "details" and len(args) == 6:
            if not re.fullmatch(r"[0-9]{1,3}", args[5]):
                raise ValueError("Choose a valid measurement details page.")
            detail_page = int(args[5])
        if action in {"p", "g"}:
            ctx.interaction.defer(ephemeral=True); deferred = True
        result = _resolve(left, right, mode, location)
        if action == "t" and args[5] != result["telemetry_fingerprint"]:
            raise ValueError("Measurement data changed. Post a fresh comparison graph.")
        if action == "l":
            location = _selection(event, _locations(result))
            result = _resolve(left, right, mode, location)
        if action in {"m", "v", "s", "l", "copy", "n"}:
            return _show(ctx, result, owner, view, location, update=not clone, initial=clone, detail_page=detail_page)
        if action == "t":
            if not result["metrics"][view]["available"]:
                raise ValueError("That graph has no matching reviewed measurements.")
            embed = comparison_embed(result, view, presentation="graph")
            embed["image"] = {"url": "attachment://comparison-" + view + ".png"}
            ctx.interaction.respond(embeds=[embed], components=_public_controls(result, owner, view, location, graph_bundle=True),
                                    update_message=True, allowed_mentions=NO_MENTIONS)
            return
        if action not in {"p", "g"}:
            raise ValueError("That comparison control is invalid.")
        channel = str(event.get("channel_id") or "")
        if not channel.isdigit():
            raise ValueError("Open this comparison in a Discord channel before posting.")
        embed = comparison_embed(result, view, detail_page, presentation="shared")
        files = None
        if action == "g":
            from .comparison_charts import render_chart, measurement_notes
            metric = _graph_metric(result, view)
            if metric is None:
                raise ValueError("This graph needs matching reviewed measurements. No values will be estimated.")
            files = []
            for key, entry in result["metrics"].items():
                if entry["available"]:
                    png = render_chart(result, key)
                    if not isinstance(png, bytes) or not png.startswith(b"\x89PNG\r\n\x1a\n"):
                        raise ValueError("The graph couldn't be rendered.")
                    files.append({"filename": "comparison-" + key + ".png", "data_b64": base64.b64encode(png).decode("ascii")})
            notes = "\n\n".join(measurement_notes(result, key) for key, entry in result["metrics"].items() if entry["available"])
            files.append({"filename": "comparison-measurements.txt", "data_b64": base64.b64encode(notes.encode("utf8")).decode("ascii")})
            if sum(len(base64.b64decode(f["data_b64"])) for f in files) > 8 * 1024 * 1024:
                raise ValueError("The graphs and measurement notes exceed Discord's file limit.")
            embed = comparison_embed(result, metric, presentation="graph")
            embed["image"] = {"url": "attachment://comparison-" + metric + ".png"}
            view = metric
        ctx.discord.send_message(channel_id=channel, embeds=[embed], files=files,
            components=_public_controls(result, owner, view, location, graph_bundle=bool(files)), allowed_mentions=NO_MENTIONS)
        ctx.interaction.followup(content="Posted the comparison " + ("graphs" if files else "card") + " in this channel.",
                                 ephemeral=True, allowed_mentions=NO_MENTIONS)
    except Exception as error:
        if deferred:
            _failure(ctx, error)
        else:
            if not isinstance(error, ValueError):
                code = getattr(error, "code", None)
                ctx.log("COD Hub comparison control failed", level="error",
                        error_type=type(error).__name__[:60],
                        rpc_code=code if type(code) is int else None,
                        action="paste_form" if modal_recovery else "comparison_control")
            if modal_recovery:
                return _show_setup(ctx, owner, *modal_recovery,
                    content="The paste form couldn't open. You can still choose weapons below, "
                            "or choose **Paste names / codes** to try the form again.")
            message = str(error)[:1800] if isinstance(error, ValueError) else "COD Hub couldn't open that comparison. Try again."
            ctx.interaction.respond(content=message, ephemeral=True, allowed_mentions=NO_MENTIONS)
