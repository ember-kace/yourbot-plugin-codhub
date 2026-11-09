"""Bounded, offline Pygal SVG charts rasterized with resvg and a bundled OFL font."""
from datetime import date as CalendarDate
import json
import math
from pathlib import Path
import re
import struct
import threading
import xml.etree.ElementTree as ET


WIDTH, HEIGHT = 760, 700
FONT_PATH = Path(__file__).parent / "fonts/font.ttf"
FONT_FAMILY = "Atkinson Hyperlegible"
BACKGROUND = "#0b111a"
_SVG = "http://www.w3.org/2000/svg"
_MAX_SVG = 1_000_000
_MAX_PNG = 8 * 1024 * 1024
_RENDER_LOCK = threading.Lock()
_TITLES = {"dps": "Theoretical DPS by distance", "recoil": "Measured recoil trajectory", "sway": "Measured aiming sway"}
# Rounded-up glyph advances from the unchanged bundled font at 100 px. These
# avoid importing a second image/font engine just to wrap provenance captions.
_WIDTHS = (0.28,0.28,0.3,0.66,0.59,0.93,0.71,0.16,0.3,0.3,0.43,0.6,0.21,0.37,0.21,0.38,0.65,0.4,0.55,0.57,0.61,0.58,0.6,0.51,0.62,0.6,0.21,0.21,0.55,0.6,0.55,0.52,0.78,0.63,0.62,0.66,0.67,0.57,0.55,0.71,0.69,0.41,0.51,0.63,0.54,0.82,0.69,0.73,0.6,0.75,0.62,0.6,0.56,0.69,0.59,0.84,0.62,0.6,0.61,0.32,0.38,0.32,0.55,0.4,0.27,0.53,0.57,0.5,0.56,0.54,0.31,0.56,0.55,0.28,0.25,0.49,0.24,0.84,0.55,0.55,0.57,0.58,0.34,0.47,0.32,0.54,0.44,0.65,0.46,0.43,0.46,0.32,0.23,0.32,0.56)


def _text(value, maximum=300):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise ValueError("Chart labels must be bounded, single-line text.")
    return value.strip()


def _number(value, minimum=-10_000, maximum=10_000):
    if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError("Chart points must be finite values in the supported range.")
    return value


def _width(value, size):
    return sum(_WIDTHS[ord(c)-32] if 32 <= ord(c) <= 126 else 1 for c in value) * size


def _wrap(value, size=12.5, width=WIDTH-52):
    words, lines, current = value.split(), [], ""
    for word in words:
        while _width(word, size) > width:
            if current:
                lines.append(current)
                current = ""
            at = 1
            while at < len(word) and _width(word[:at+1], size) <= width:
                at += 1
            lines.append(word[:at])
            word = word[at:]
        candidate = (current + " " + word).strip()
        if current and _width(candidate, size) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _payload(result, metric):
    if metric not in _TITLES or not isinstance(result, dict):
        raise ValueError("Choose DPS, recoil or aiming sway.")
    metrics = result.get("metrics")
    data = metrics.get(metric) if isinstance(metrics, dict) else None
    if not isinstance(data, dict) or data.get("available") is not True:
        raise ValueError("This chart is unavailable: " + str(data.get("reason") if isinstance(data, dict) else "No reviewed measurements.")[:1000])
    series = data.get("series")
    if (not isinstance(series, list) or len(series) != 2
            or {s.get("side") for s in series if isinstance(s, dict)} != {"left", "right"}):
        raise ValueError("A comparison chart needs exactly one measured series per side.")
    ordered = [next(s for s in series if s["side"] == side) for side in ("left", "right")]
    output = []
    for source in ordered:
        label = _text(source.get("label"), 80)
        if not label:
            raise ValueError("A measured series needs a label.")
        points = source.get("points")
        if not isinstance(points, list) or not 2 <= len(points) <= 2048:
            raise ValueError("A chart needs between 2 and 2048 measured points per side.")
        rows, previous = [], -1
        for index, point in enumerate(points):
            if not isinstance(point, dict):
                raise ValueError("Chart points must be coordinate objects.")
            if metric == "dps":
                x, y = _number(point.get("distance_m"), 0), _number(point.get("dps"), 0, 1_000_000_000)
                if x < previous:
                    raise ValueError("DPS distances must increase or repeat at damage boundaries.")
                previous = x
                rows.append((x, y))
            elif metric == "recoil":
                if point.get("shot") != index+1 or type(point.get("shot")) is not int:
                    raise ValueError("Recoil charts require consecutive shot indexes.")
                rows.append((_number(point.get("x")), _number(point.get("y"))))
            else:
                at = _number(point.get("time_s"), 0, 3600)
                if at <= previous:
                    raise ValueError("Sway sampling times must increase strictly.")
                previous = at
                rows.append((at, _number(point.get("x")), _number(point.get("y"))))
        if metric != "dps" and source.get("unit") not in {"degrees", "milliradians"}:
            raise ValueError("Angular charts require explicit degrees or milliradians units.")
        output.append((source, label, rows))
    if metric != "dps" and output[0][0]["unit"] != output[1][0]["unit"]:
        raise ValueError("Angular chart units must match.")
    conditions = ("condition", "statistic") if metric == "recoil" else ("condition", "stance")
    if metric != "dps" and any(output[0][0].get(key) != output[1][0].get(key) for key in conditions):
        raise ValueError("Angular chart sampling definitions and conditions must match.")
    if metric == "dps" and output[0][0].get("hit_location") != output[1][0].get("hit_location"):
        raise ValueError("DPS chart hit-location definitions must match.")
    return output


def _notes(series, metric):
    sources, patches, caveats, details, component_notes = [], [], [], [], []
    for source, label, _ in series:
        provenance = source.get("provenance")
        if not isinstance(provenance, dict):
            raise ValueError("Every chart series must retain source provenance.")
        patch = _text(provenance.get("patch"), 100)
        if patch:
            patches.append(patch)
        components = provenance.get("components", [{"metric": "measurement", "source_url": provenance.get("source_url"),
                                                    "source_date": provenance.get("source_date")}])
        if not isinstance(components, list) or not 1 <= len(components) <= 16:
            raise ValueError("Chart source components are invalid.")
        if not any(isinstance(component, dict) and component.get("source_url") == provenance.get("source_url")
                   and component.get("source_date") == provenance.get("source_date") for component in components):
            components = [*components, {"metric": "measurement provenance", "source_url": provenance.get("source_url"),
                                       "source_date": provenance.get("source_date")}]
        details.append(label + " / method: " + _text(provenance.get("method"), 300))
        for component in components:
            if not isinstance(component, dict):
                raise ValueError("Chart source components are invalid.")
            name = _text(component.get("metric"), 80)
            date = _text(component.get("source_date"), 10)
            url = _text(component.get("source_url"), 2048)
            try:
                valid_date = re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) and CalendarDate.fromisoformat(date).isoformat() == date
            except ValueError:
                valid_date = False
            if not valid_date or not url.startswith("https://"):
                raise ValueError("Chart source dates and HTTPS citations are required.")
            sources.append((name, date, url))
            if component.get("note"):
                component_notes.append((label, name, _text(component["note"], 300)))
            if component.get("patch"):
                component_notes.append((label, name, "Patch: " + _text(component["patch"], 300)))
        entries = provenance.get("caveats", [])
        if not isinstance(entries, list) or len(entries) > 8:
            raise ValueError("Chart caveats are invalid.")
        caveats += [_text(item, 300) for item in entries]
        if metric == "recoil":
            statistic = _text(source.get("statistic"), 20)
            count = source.get("sample_count")
            if (statistic not in {"mean", "single_trial"} or type(count) is not int or not 1 <= count <= 100_000
                    or statistic == "single_trial" and count != 1 or statistic == "mean" and count < 2):
                raise ValueError("Recoil charts must identify their sample definition.")
            details.append(f"{label}: {statistic.replace('_', ' ')}, {count} sample{'s' if count != 1 else ''}.")
        if metric != "dps":
            details.append(label + " / unit: " + _text(source["unit"], 20))
            for key in ("condition", "stance"):
                if source.get(key):
                    details.append(label + " / " + key + ": " + _text(source[key], 160))
    unique_sources = list(dict.fromkeys(sources))
    paragraphs = []
    if metric == "dps":
        paragraphs.append("Theoretical cyclic DPS; continuous automatic fire, all projectiles hit. No current-balance or real-TTK claim.")
    else:
        paragraphs.append("Measured angular samples; no stability percentage, accuracy score or synthetic recoil pattern is inferred.")
    if patches:
        paragraphs.append("Patch: " + " / ".join(dict.fromkeys(patches)))
    # Keep component dates visibly distinct even when both sources share a host.
    for name, date, url in unique_sources:
        paragraphs.append(name.upper() + " " + date + ": " + url)
    grouped_notes = {}
    for label, name, note in component_notes:
        grouped_notes.setdefault((name, note), []).append(label)
    for (name, note), labels in grouped_notes.items():
        scope = "Both" if len(set(labels)) == 2 else labels[0]
        paragraphs.append(scope + " / " + name + ": " + note)
    paragraphs += list(dict.fromkeys(details))
    paragraphs += list(dict.fromkeys(caveats))
    if metric == "dps" and not caveats:
        paragraphs.append("Reloads, misses, target armor, travel time and unmeasured attachment effects are excluded.")
        region = series[0][0].get("region_note")
        if region:
            paragraphs.append(_text(region, 300))
    return paragraphs, unique_sources


def measurement_notes(result, metric="dps"):
    """Complete UTF-8 companion text, including source URLs and every caveat."""
    series = _payload(result, metric)
    paragraphs, _ = _notes(series, metric)
    identity = [_TITLES[metric], "Game: Modern Warfare 4", "Mode: " + str(result.get("mode_label") or result.get("mode"))]
    for side, label, _ in series:
        subject = result.get(side["side"], {})
        identity.append(("A: " if side["side"] == "left" else "B: ") + label +
                        (" · Build code: " + subject["code"] if subject.get("code") else " · Base weapon"))
        if metric == "dps":
            identity += [side["hit_location_label"], side["region_note"], side["model"]]
    return "\n".join(dict.fromkeys(identity)) + "\n\n" + "\n\n".join(paragraphs)


def _compact_captions(series, metric, sources):
    labels = list(dict.fromkeys(name.title() + " " + date for name, date, _ in sources))
    dates = " · ".join(labels)
    if len(dates) > 100:
        bounds = sorted({date for _, date, _ in sources})
        dates = f"{len(sources)} dated source inputs: {bounds[0]} to {bounds[-1]}; breakdown in notes."
    if metric == "dps":
        paragraphs = ["Theoretical automatic-fire DPS; all projectiles hit.",
                      "No reloads, misses, armor, travel time or unmeasured attachment effects; not real TTK.",
                      dates, "Later hotfix completeness and engine threshold rounding are unverified."]
    else:
        paragraphs = ["Measured angular samples; no inferred accuracy or stability score.", dates]
        if metric == "recoil":
            for source, label, _ in series:
                paragraphs.append(label + ": " + source["statistic"].replace("_", " ") + f", {source['sample_count']} sample(s).")
        else:
            paragraphs.append("Conditions and stance are declared in the complete measurement notes.")
    paragraphs.append("Full sources and limits: comparison-measurements.txt / Measurements / sources.")
    return [line for paragraph in paragraphs for line in _wrap(paragraph, size=16, width=WIDTH-52)]


def _audit_svg(root):
    for element in root.iter():
        if element.tag.split("}")[-1].lower() in {"script", "image", "foreignobject"}:
            raise ValueError("Chart SVG must not contain executable or image resources.")
        for name, value in element.attrib.items():
            if name.split("}")[-1].lower() == "href" and not value.startswith("#"):
                raise ValueError("Chart SVG must not load external resources.")
        if element.tag.split("}")[-1] == "style":
            if "@import" in (element.text or "").lower():
                raise ValueError("Chart SVG must not import styles.")
            for value in re.findall(r"url\((.*?)\)", element.text or "", re.I):
                if not value.strip(" \"'").startswith("#"):
                    raise ValueError("Chart SVG must not load external styles.")


def render_svg(result, metric="dps"):
    """Return a mobile-friendly chart; complete notes accompany every public post."""
    series = _payload(result, metric)
    paragraphs, sources = _notes(series, metric)
    captions = _compact_captions(series, metric, sources)
    footer_height = 24 + 20 * len(captions)
    plot_height = HEIGHT - 86 - footer_height
    if plot_height < 255:
        raise ValueError("The complete source notes are too long for one readable chart.")
    try:
        import pygal
        from pygal.style import Style
    except ImportError as error:
        raise ValueError("Chart rendering dependencies are unavailable.") from error
    colors = ("#9df0b4", "#69b8ff") if metric != "sway" else ("#9df0b4", "#d2f8dd", "#69b8ff", "#b9ddff")
    style = Style(font_family=FONT_FAMILY, background=BACKGROUND, plot_background="#101c27",
                  foreground="#cedbe7", foreground_strong="#f0f5f9", foreground_subtle="#405362",
                  colors=colors, opacity="1", stroke_opacity="1", stroke_width="2.6", transition="0ms",
                  title_font_size=20, label_font_size=18, major_label_font_size=18, legend_font_size=21,
                  guide_stroke_color="#354857", major_guide_stroke_color="#405362")
    chart = pygal.XY(width=WIDTH, height=plot_height, style=style, js=[], show_dots=False,
                     show_legend=True, legend_at_bottom=True, legend_at_bottom_columns=2,
                     explicit_size=True, disable_xml_declaration=True, tooltip_fancy_mode=False,
                     margin=14, spacing=10, show_x_guides=True, truncate_legend=45,
                     x_labels_major_count=6, show_minor_x_labels=False,
                     interpolate=None, include_x_axis=metric == "dps", human_readable=False)
    if metric == "dps":
        chart.x_title, chart.y_title = "Distance (m)", "Damage per second"
        context = series[0][0].get("hit_location_label") or series[0][0].get("hit_location") or "Explicit measured hit location"
        chart.range = (0, max(y for _, _, rows in series for _, y in rows) * 1.08 or 1)
    elif metric == "recoil":
        unit = series[0][0]["unit"]
        chart.x_title, chart.y_title = "Horizontal angle ("+unit+")", "Vertical angle ("+unit+")"
        context = "Per-shot angular path ("+unit+")"
    else:
        unit = series[0][0]["unit"]
        chart.x_title, chart.y_title = "Time (s)", "Aiming angle ("+unit+")"
        context = "Horizontal / vertical measured traces ("+unit+")"
    for source, label, rows in series:
        if metric == "sway":
            chart.add(label + " · horizontal", [(at, x) for at, x, y in rows])
            chart.add(label + " · vertical", [(at, y) for at, x, y in rows])
        else:
            chart.add(label, rows)
    generated = ET.fromstring(chart.render(is_unicode=True))
    # Pygal emits an inline configuration script even with js=[]; remove it.
    for parent in generated.iter():
        for child in list(parent):
            if child.tag.split("}")[-1].lower() == "script":
                parent.remove(child)
    root = ET.Element("{"+_SVG+"}svg", {"width": str(WIDTH), "height": str(HEIGHT),
                                      "viewBox": f"0 0 {WIDTH} {HEIGHT}"})
    ET.SubElement(root, "{"+_SVG+"}rect", {"width": str(WIDTH), "height": str(HEIGHT), "fill": BACKGROUND})
    def text(x, y, content, size, fill="#c2d1dd"):
        node = ET.SubElement(root, "{"+_SVG+"}text", {"x": str(x), "y": str(y), "fill": fill,
                                                   "font-family": FONT_FAMILY, "font-size": str(size)})
        node.text = content
    text(26, 32, _TITLES[metric], 26, "#f1f6fa")
    subtitle = _text(result.get("mode_label") or result.get("mode") or "Explicit measured mode", 80) + " · " + _text(context, 120)
    if _width(subtitle, 16) > WIDTH-52:
        raise ValueError("The chart's measurement label is too long.")
    text(26, 59, subtitle, 16, "#9df0b4")
    generated.set("y", "86")
    root.append(generated)
    top = 86 + plot_height + 16
    for index, line in enumerate(captions):
        text(26, top + index*20, line, 16)
    metadata = ET.SubElement(root, "{"+_SVG+"}metadata")
    metadata.text = json.dumps({"metric": metric, "mode": result.get("mode"), "sources": sources,
                                "complete_notes": paragraphs}, ensure_ascii=True)
    _audit_svg(root)
    svg = ET.tostring(root, encoding="unicode")
    if len(svg.encode("utf8")) > _MAX_SVG:
        raise ValueError("The chart exceeds its bounded SVG size.")
    return svg


def _rasterize(result, metric):
    svg = render_svg(result, metric)
    if not FONT_PATH.is_file() or FONT_PATH.stat().st_size > 100_000:
        raise ValueError("The bundled chart font is unavailable.")
    try:
        import resvg_py
        png = resvg_py.svg_to_bytes(svg_string=svg, width=WIDTH, height=HEIGHT, background=BACKGROUND,
                                   skip_system_fonts=True, font_files=[str(FONT_PATH)],
                                   font_family=FONT_FAMILY, sans_serif_family=FONT_FAMILY)
    except (ImportError, OSError, RuntimeError, ValueError) as error:
        raise ValueError("The chart image could not be rendered.") from error
    if (not isinstance(png, bytes) or len(png) < 24 or not png.startswith(b"\x89PNG\r\n\x1a\n") or len(png) > _MAX_PNG
            or struct.unpack_from(">II", png, 16) != (WIDTH, HEIGHT)):
        raise ValueError("The chart renderer returned an invalid or oversized image.")
    return png


def render_chart(result, metric="dps"):
    """Rasterize offline, with one bounded native raster job per worker."""
    if not _RENDER_LOCK.acquire(timeout=10):
        raise ValueError("The chart renderer is busy. Please try again.")
    try:
        return _rasterize(result, metric)
    finally:
        _RENDER_LOCK.release()
