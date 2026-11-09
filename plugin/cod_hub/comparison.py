"""Gun/build identity comparison and explicitly sourced measurement curves.

The shipped catalog has dated base references, not ballistic telemetry. This
module never derives damage, recoil or attachment effects from UI ratings. The
optional profile contract validates structure/scope; its provenance still needs
independent source review before production use.
"""
from copy import deepcopy
from datetime import date
import math
import re
from urllib.parse import urlsplit

from . import catalog


MODES = {"multiplayer": "Multiplayer", "dmz": "DMZ", "warzone": "Warzone"}
_MODES = {"multiplayer": "multiplayer", "mp": "multiplayer", "dmz": "dmz", "warzone": "warzone", "wz": "warzone"}
_ASSET = re.compile(r"[0-9a-f]{16}\Z")
_CODE_START = re.compile(r"[A-Z][0-9]{2}.+", re.I)
HIT_LOCATIONS = ("base_profile", "body", "head", "neck", "upper_torso", "lower_torso", "upper_arm", "lower_arm", "upper_leg", "lower_leg")
HIT_LOCATION_LABELS = {key: key.replace("_", " ").title() for key in HIT_LOCATIONS}
HIT_LOCATION_LABELS["base_profile"] = "Published base profile (region unspecified)"
BASE_FIELDS = (
    ("rpm", "Fire rate", "rounds/min"), ("magazine", "Base magazine", "rounds"),
    ("reserve", "Base reserve", "rounds"), ("weaponLevels", "Weapon levels", "levels"),
    ("unlockLevel", "Player unlock level", "player level"), ("caliber", "Caliber", "as stated"),
)


def normalize_mode(value):
    mode = _MODES.get(str(value).strip().lower())
    if mode is None:
        raise ValueError("Choose Multiplayer, DMZ or Warzone.")
    return mode


def resolve_subject(value):
    """Resolve an exact named player weapon or a fully named native build."""
    if (not isinstance(value, str) or not value.strip() or len(value) > 256
            or any(ord(c) < 32 for c in value)):
        raise ValueError("Choose an exact weapon name, prefix or MW4 build code.")
    value = value.strip()
    try:
        weapon = catalog.get_weapon(value)
    except ValueError:
        if not _CODE_START.fullmatch(value):
            raise ValueError("Choose an exact weapon name or prefix, such as Kastov 762 or A01.") from None
        build = catalog.resolve_build(value)
        if build.get("identity_status") != "resolved" or build.get("label_status") == "fallback":
            raise ValueError("This build contains unsupported or untranslated items. Choose another build code.")
        weapon = catalog.get_weapon(build["weapon"]["asset_id"])
        return {"kind": "build", "key": build["code"], "label": weapon["name"] + " build",
                "weapon": weapon, "code": build["code"], "attachments": deepcopy(build["attachments"]),
                "native_slots": dict(build["native_slots"]), "notes": list(build.get("notes", []))}
    return {"kind": "weapon", "key": weapon["asset_id"], "label": weapon["name"],
            "weapon": weapon, "code": None, "attachments": [], "native_slots": {}, "notes": []}


def _number(value, *, minimum=0, maximum=100_000, name="Value"):
    if (type(value) not in (int, float) or not math.isfinite(value)
            or not minimum <= value <= maximum):
        raise ValueError(name + " must be a finite number in the supported range.")
    return value


def _text(value, name, maximum=160):
    if (not isinstance(value, str) or not value.strip() or len(value) > maximum
            or any(ord(c) < 32 for c in value)):
        raise ValueError(name + " must be nonempty bounded text.")
    return value.strip()


def _provenance(value):
    if not isinstance(value, dict):
        raise ValueError("Measurement provenance is required.")
    source = _text(value.get("source_url"), "Source URL", 2048)
    try:
        url = urlsplit(source)
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.port not in (None, 443):
            raise ValueError("Source URL must be a public HTTPS citation.")
        source_date = _text(value.get("source_date"), "Source date", 10)
        if date.fromisoformat(source_date).isoformat() != source_date:
            raise ValueError("Source date must be an ISO calendar date.")
    except (ValueError, TypeError) as error:
        raise ValueError("Measurement source URL/date is invalid.") from error
    result = {"source_url": source, "source_date": source_date,
              "patch": _text(value.get("patch"), "Balance patch", 100),
              "method": _text(value.get("method"), "Measurement method", 300)}
    if "components" in value:
        components = value["components"]
        if not isinstance(components, list) or not 1 <= len(components) <= 16:
            raise ValueError("Composite measurements require bounded source components.")
        result["components"] = []
        for component in components:
            if not isinstance(component, dict):
                raise ValueError("A source component must identify its metric, URL and date.")
            row = {"metric": _text(component.get("metric"), "Source component metric", 80),
                   "source_url": _text(component.get("source_url"), "Component URL", 2048),
                   "source_date": _text(component.get("source_date"), "Component date", 10)}
            try:
                url = urlsplit(row["source_url"])
                if (url.scheme != "https" or not url.hostname or url.username or url.password
                        or url.port not in (None, 443) or date.fromisoformat(row["source_date"]).isoformat() != row["source_date"]):
                    raise ValueError("Invalid source component URL/date.")
            except (ValueError, TypeError) as error:
                raise ValueError("Invalid source component URL/date.") from error
            for optional in ("patch", "note"):
                if optional in component:
                    row[optional] = _text(component[optional], "Component " + optional, 300)
            result["components"].append(row)
    if "caveats" in value:
        if not isinstance(value["caveats"], list) or not 1 <= len(value["caveats"]) <= 8:
            raise ValueError("Measurement caveats must be a bounded text list.")
        result["caveats"] = [_text(item, "Measurement caveat", 300) for item in value["caveats"]]
    return result


def _dps_section(value):
    if not isinstance(value, dict) or value.get("fire_mode") != "automatic":
        raise ValueError("DPS requires verified automatic-fire cadence; burst/charge models are not supported.")
    rpm = _number(value.get("rpm"), minimum=0.001, maximum=100_000, name="Measured fire rate")
    projectiles = value.get("projectiles_per_shot")
    if type(projectiles) is not int or not 1 <= projectiles <= 64:
        raise ValueError("Projectiles per shot must be an integer from 1 to 64.")
    ranges = value.get("damage_ranges")
    if not isinstance(ranges, list) or not 1 <= len(ranges) <= 64:
        raise ValueError("DPS requires bounded damage-by-distance ranges.")
    out, previous, locations = [], 0, None
    for index, item in enumerate(ranges):
        if not isinstance(item, dict):
            raise ValueError("Damage ranges must be objects.")
        minimum = _number(item.get("min_m"), maximum=10_000, name="Range start")
        if not math.isclose(minimum, previous, rel_tol=0, abs_tol=1e-9):
            raise ValueError("Damage ranges must start at zero and be contiguous without overlap.")
        maximum = item.get("max_m")
        if maximum is None:
            if index != len(ranges)-1:
                raise ValueError("Only the final damage range may be open-ended.")
        else:
            maximum = _number(maximum, maximum=10_000, name="Range end")
            if maximum <= minimum:
                raise ValueError("A damage range must have positive width.")
        damage = item.get("damage")
        if (not isinstance(damage, dict) or not damage or not set(damage) <= set(HIT_LOCATIONS)
                or locations is not None and set(damage) != locations):
            raise ValueError("Every damage range needs the same explicit supported hit locations.")
        locations = set(damage)
        damage = {key: _number(number, name="Projectile damage") for key, number in damage.items()}
        out.append({"min_m": minimum, "max_m": maximum, "damage": damage})
        previous = maximum
    return {"fire_mode": "automatic", "rpm": rpm, "projectiles_per_shot": projectiles, "damage_ranges": out}


def _trajectory(value, kind):
    if not isinstance(value, dict) or value.get("unit") not in {"degrees", "milliradians"}:
        raise ValueError("Trajectory points need an explicit degrees or milliradians unit.")
    points = value.get("points")
    if not isinstance(points, list) or not 2 <= len(points) <= 2048:
        raise ValueError("A measured trajectory needs between 2 and 2048 points.")
    out, previous = [], -1
    for index, point in enumerate(points):
        if not isinstance(point, dict):
            raise ValueError("Trajectory points must be objects.")
        if kind == "recoil":
            at = point.get("shot")
            if type(at) is not int or at != index+1:
                raise ValueError("Recoil points must contain consecutive shot indexes starting at one.")
            row = {"shot": at}
        else:
            at = _number(point.get("time_s"), maximum=3600, name="Sway time")
            if at <= previous:
                raise ValueError("Sway sample times must increase strictly.")
            row = {"time_s": at}
        row.update(x=_number(point.get("x"), minimum=-10_000, maximum=10_000, name="Horizontal angle"),
                   y=_number(point.get("y"), minimum=-10_000, maximum=10_000, name="Vertical angle"))
        out.append(row)
        previous = at
    result = {"unit": value["unit"], "points": out}
    if kind == "recoil":
        if value.get("statistic") not in {"single_trial", "mean"}:
            raise ValueError("Recoil must identify a single trial or a mean path.")
        count = value.get("sample_count")
        if (type(count) is not int or not 1 <= count <= 100_000
                or value["statistic"] == "single_trial" and count != 1
                or value["statistic"] == "mean" and count < 2):
            raise ValueError("Recoil sample count does not match its declared statistic.")
        result.update(statistic=value["statistic"], sample_count=count)
    else:
        result["stance"] = _text(value.get("stance"), "Sway stance", 80)
    if "condition" in value:
        result["condition"] = _text(value["condition"], "Measurement condition", 160)
    return result


def validate_profile(profile, *, subject=None, mode=None):
    """Validate a declared measurement; this does not authenticate its source."""
    if not isinstance(profile, dict) or type(profile.get("schema_version")) is not int or profile["schema_version"] != 1:
        raise ValueError("Unsupported measurement profile schema.")
    if profile.get("game") != "mw4" or not isinstance(profile.get("asset_id"), str) or not _ASSET.fullmatch(profile["asset_id"]):
        raise ValueError("Measurements require the exact MW4 weapon asset identity.")
    scope = normalize_mode(profile.get("mode"))
    if mode is not None and scope != normalize_mode(mode):
        raise ValueError("Measurement mode does not match the selected mode.")
    variant = profile.get("variant")
    if not isinstance(variant, dict) or variant.get("kind") not in {"base", "build"}:
        raise ValueError("Measurements must identify a base weapon or exact build variant.")
    if variant["kind"] == "base" and "code" in variant:
        raise ValueError("A base measurement must not contain a build code.")
    variant = {"kind": variant["kind"], **({"code": variant.get("code")} if variant["kind"] == "build" else {})}
    if variant["kind"] == "build":
        code = variant["code"]
        if not isinstance(code, str) or len(code) > 25 or catalog.get_catalog().codec.decode(code).canonical_code != code:
            raise ValueError("A build measurement needs its canonical native code.")
    if subject is not None:
        if profile["asset_id"] != subject["weapon"]["asset_id"]:
            raise ValueError("Measurement weapon identity does not match this selection.")
        if variant["kind"] == "base" and subject.get("attachments"):
            raise ValueError("Attachment-adjusted telemetry is required for this exact build.")
        if variant["kind"] == "build" and variant["code"] != subject.get("code"):
            raise ValueError("Measurement build code does not match this selection.")
    result = {"schema_version": 1, "game": "mw4", "mode": scope, "asset_id": profile["asset_id"],
              "variant": variant, "provenance": _provenance(profile.get("provenance"))}
    for key in ("dps", "recoil", "sway"):
        if key in profile:
            result[key] = _dps_section(profile[key]) if key == "dps" else _trajectory(profile[key], key)
    if not any(key in result for key in ("dps", "recoil", "sway")):
        raise ValueError("A measurement profile contains no supported metric.")
    return result


def damage_at_distance(profile, distance_m, hit_location="upper_torso"):
    """Select a half-open damage interval; an exact boundary uses the next range."""
    profile = validate_profile(profile)
    if "dps" not in profile or hit_location not in HIT_LOCATIONS:
        raise ValueError("Choose a measured damage profile and supported hit location.")
    distance = _number(distance_m, maximum=10_000, name="Distance")
    for row in profile["dps"]["damage_ranges"]:
        if row["min_m"] <= distance and (row["max_m"] is None or distance < row["max_m"]):
            if hit_location not in row["damage"]:
                raise ValueError("That hit location was not measured.")
            return row["damage"][hit_location]
    raise ValueError("Distance is outside the measured damage coverage.")


def dps_curve(profile, hit_location="upper_torso", max_distance_m=100):
    """Theoretical automatic-fire DPS, excluding reloads, misses and target armor."""
    profile = validate_profile(profile)
    if "dps" not in profile or hit_location not in HIT_LOCATIONS:
        raise ValueError("A measured automatic-fire profile is required for DPS.")
    end = _number(max_distance_m, minimum=0.001, maximum=10_000, name="Plot distance")
    section = profile["dps"]
    factor = section["rpm"] / 60 * section["projectiles_per_shot"]
    points, segments = [], []
    for row in section["damage_ranges"]:
        if row["min_m"] >= end:
            break
        if hit_location not in row["damage"]:
            raise ValueError("That hit location was not measured.")
        stop = min(end, row["max_m"]) if row["max_m"] is not None else end
        dps = row["damage"][hit_location] * factor
        segments.append({"min_m": row["min_m"], "max_m": stop, "dps": dps,
                         "includes_end": stop == end and (row["max_m"] is None or stop < row["max_m"])})
        points.extend([{"distance_m": row["min_m"], "dps": dps}, {"distance_m": stop, "dps": dps}])
    return {"points": points, "segments": segments, "hit_location": hit_location,
            "hit_location_label": HIT_LOCATION_LABELS[hit_location],
            "unit": "damage/second", "max_distance_m": segments[-1]["max_m"] if segments else 0,
            "model": "Theoretical automatic-fire DPS; all projectiles hit; reloads, misses and target armor are excluded.",
            "region_note": ("The published table does not identify this base profile's body region; no hit-location multiplier is assumed."
                            if hit_location == "base_profile" else "Uses the explicitly supplied hit-location damage values.")}


def _base_comparison(left, right):
    sides = [subject["weapon"].get("base_stats") or {} for subject in (left, right)]
    rows = []
    for key, label, unit in BASE_FIELDS:
        values = [side.get("values", {}).get(key) for side in sides]
        if all(value is None for value in values):
            continue
        delta = None
        if all(type(value) in (int, float) and math.isfinite(value) for value in values):
            delta = values[0] - values[1]
        rows.append({"key": key, "label": label, "unit": unit, "left": values[0], "right": values[1],
                     "delta": delta, "left_date": sides[0].get("data_date"), "right_date": sides[1].get("data_date")})
    return {"rows": rows, "attachment_adjusted": False, "mode_specific": False,
            "left_sources": list(sides[0].get("source_ids", [])), "right_sources": list(sides[1].get("source_ids", [])),
            "note": "Dated launch base references. Mode-specific balance and attachment effects are unverified."}


def _attachment_diff(left, right, same_weapon):
    if not same_weapon:
        return {"comparable": False, "common": [], "changed": [],
                "left_only": deepcopy(left["attachments"]), "right_only": deepcopy(right["attachments"]),
                "note": "Attachment indexes are weapon-specific; selections are listed without equating indexes across weapons."}
    a, b = ({row["slot"]: row for row in side["attachments"]} for side in (left, right))
    common, changed, only_a, only_b = [], [], [], []
    for slot in catalog.get_catalog().schema.slots:
        x, y = a.get(slot.key), b.get(slot.key)
        if x and y:
            if (x["asset_id"], x["index"]) == (y["asset_id"], y["index"]):
                common.append(deepcopy(x))
            else:
                changed.append({"slot": slot.key, "slot_label": x["slot_label"], "left": deepcopy(x), "right": deepcopy(y)})
        elif x:
            only_a.append(deepcopy(x))
        elif y:
            only_b.append(deepcopy(y))
    return {"comparable": True, "common": common, "changed": changed, "left_only": only_a, "right_only": only_b,
            "note": "Exact selected catalog items; their performance effects are not inferred."}


def _profile_for(subject, profiles, mode):
    raw = profiles.get(subject["key"])
    if raw is None and not subject["attachments"]:
        raw = profiles.get(subject["weapon"]["asset_id"])
    if raw is None:
        return None, ("No attachment-adjusted measurements are available for this exact build."
                      if subject["attachments"] else "No reviewed mode-specific measurements are available for this weapon.")
    try:
        return validate_profile(raw, subject=subject, mode=mode), None
    except (ValueError, TypeError, OverflowError) as error:
        return None, str(error)


def _metrics(left, right, profiles, mode, hit_location):
    scoped = [_profile_for(side, profiles, mode) for side in (left, right)]
    result = {}
    for metric in ("dps", "recoil", "sway"):
        available = [profile is not None and metric in profile for profile, _ in scoped]
        item = {"available": False, "left_available": available[0], "right_available": available[1],
                "series": [], "reason": None}
        result[metric] = item
        if not all(available):
            details = []
            for label, (profile, error), present in zip(("Left", "Right"), scoped, available):
                if not present:
                    details.append(label + ": " + (error or "The reviewed profile has no " + metric + " measurements."))
            item["reason"] = " ".join(details)
            continue
        p, q = scoped[0][0], scoped[1][0]
        if p["provenance"]["patch"] != q["provenance"]["patch"]:
            item["reason"] = "Measurements use different balance patches; choose matching measurements."
            continue
        if metric != "dps":
            fields = ("unit", "condition", "statistic") if metric == "recoil" else ("unit", "condition", "stance")
            if any(p[metric].get(key) != q[metric].get(key) for key in fields):
                item["reason"] = "Measurements use different units, conditions or sampling definitions."
                continue
        try:
            values = [dps_curve(profile, hit_location) if metric == "dps" else deepcopy(profile[metric]) for profile in (p, q)]
        except ValueError as error:
            item["reason"] = str(error)
            continue
        item.update(available=True, series=[dict(value, side=side, label=subject["label"],
                                                provenance=deepcopy(profile["provenance"]))
                                             for side, subject, profile, value in zip(("left", "right"), (left, right), (p, q), values)])
    return result


def compare(left, right, mode="multiplayer", *, profiles=None, hit_location="upper_torso"):
    """Compare identities/base references; enable curves only from scoped data."""
    mode = normalize_mode(mode)
    if profiles is not None and not isinstance(profiles, dict):
        raise ValueError("Reviewed measurement profiles must be an exact-selection map.")
    if hit_location not in HIT_LOCATIONS:
        raise ValueError("Choose a supported hit location.")
    a, b = resolve_subject(left), resolve_subject(right)
    same = a["weapon"]["asset_id"] == b["weapon"]["asset_id"]
    metrics = _metrics(a, b, profiles or {}, mode, hit_location)
    notes = ["Build codes identify selected items; they do not contain measured damage or recoil data."]
    if not all(value["available"] for value in metrics.values()):
        notes.append("Unavailable chart metrics need matching reviewed measurements; missing values are not estimated.")
    if any(value["available"] for value in metrics.values()):
        notes.append("Chart measurements retain their declared mode, balance patch, source date and sampling scope.")
        dates = {component["source_date"] for metric in metrics.values() for series in metric["series"]
                 for component in series["provenance"].get("components", [])}
        if len(dates) > 1:
            notes.append("Chart inputs have separately dated sources; consult the damage and fire-rate provenance.")
    return {"game": "mw4", "mode": mode, "mode_label": MODES[mode], "left": a, "right": b,
            "same_weapon": same, "base_stats": _base_comparison(a, b),
            "attachment_diff": _attachment_diff(a, b, same),
            "metrics": metrics, "notes": notes}
