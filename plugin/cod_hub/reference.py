"""Bounded, attributed article references from the public COD Wiki API.

This is a dated article search, not a complete current game catalog. Wiki text
retains its CC-BY-SA attribution and revision permalink; artwork is not copied.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import threading
import time
from html.parser import HTMLParser
from .urls import encode_query, split_https

API_URL = "https://callofduty.fandom.com/api.php"
WIKI_URL = "https://callofduty.fandom.com/"
MIN_REFRESH_SECONDS = 43_200
MAX_RESPONSE_BYTES = 200_000
MAX_EXTRACT_CHARS = 900
MAX_RESULTS = 5
_LOCK = threading.Lock()
_VERSION = 1
_CATEGORIES = {"all": "all", "maps": "maps", "map": "maps", "operators": "operators",
               "operator": "operators", "camos": "camos", "camo": "camos", "camouflage": "camos",
               "challenges": "challenges", "challenge": "challenges",
               "prestige": "prestige", "prestiges": "prestige", "perks": "perks",
               "perk": "perks", "equipment": "equipment"}
_CATEGORY_TERMS = {"all": "", "maps": "map", "operators": "operator", "camos": "camouflage",
                   "challenges": "challenge", "prestige": "prestige", "perks": "perk",
                   "equipment": "equipment"}
_GAMES = {"all": "all", "mw4": "mw4", "modernwarfare4": "mw4", "bo7": "bo7",
          "blackops7": "bo7", "warzone": "warzone"}
_GAME_TERMS = {"all": "", "mw4": '"Modern Warfare 4"', "bo7": '"Black Ops 7"',
               "warzone": '"Warzone"'}


class _BadResponse(ValueError):
    pass


class _VisibleText(HTMLParser):
    """Remove references, media blocks and tags without fetching anything."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = []
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"ref", "gallery", "imagemap", "script", "style"}:
            self.hidden.append(tag)
        elif not self.hidden and tag in {"br", "p", "div", "li"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if self.hidden and tag == self.hidden[-1]:
            self.hidden.pop()
        elif not self.hidden and tag in {"p", "div", "li"}:
            self.parts.append(" ")

    def handle_startendtag(self, tag, attrs):
        if not self.hidden:
            self.parts.append(" ")

    def handle_data(self, text):
        if not self.hidden:
            self.parts.append(text)


def _remove_templates(text):
    result, stack, index = [], [], 0
    while index < len(text):
        if text.startswith("{{{", index):
            stack.append("}}}")
            index += 3
        elif text.startswith("{{", index):
            stack.append("}}")
            index += 2
        elif text.startswith("{|", index):
            stack.append("|}")
            index += 2
        elif stack and text.startswith(stack[-1], index):
            index += len(stack.pop())
        else:
            if not stack:
                result.append(text[index])
            index += 1
    return "".join(result)


def _plain_intro(wikitext):
    text = re.sub(r"<!--[\s\S]*?-->", "", wikitext)
    parser = _VisibleText()
    parser.feed(text)
    parser.close()
    text = _remove_templates("".join(parser.parts))

    def link(match):
        fields = match.group(1).split("|")
        target = fields[0].strip().lstrip(":")
        if target.lower().startswith(("file:", "image:", "category:")):
            return ""
        return fields[-1] if len(fields) > 1 else target.replace("_", " ")

    for _ in range(5):
        replaced = re.sub(r"\[\[([^\[\]]+)\]\]", link, text)
        if replaced == text:
            break
        text = replaced
    text = re.sub(r"\[https?://[^\s\]]+(?:\s+([^\]]+))?\]", lambda m: m.group(1) or "", text)
    text = re.sub(r"__\w+__", "", text)
    text = re.sub(r"'{2,5}", "", text)
    text = re.sub(r"(?m)^\s*[*#;:]+\s*", "", text)
    text = " ".join(text.split())
    if len(text) > MAX_EXTRACT_CHARS:
        text = text[:MAX_EXTRACT_CHARS - 1].rsplit(" ", 1)[0].rstrip() + "…"
    return text


def _text(value, limit, *, required=False):
    if value is None and not required:
        return None
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 for c in value):
        raise _BadResponse("invalid text")
    value = value.strip()
    if required and not value:
        raise _BadResponse("missing text")
    return value


def _page_url(value):
    value = _text(value, 1500, required=True)
    try:
        url = split_https(value)
        port = url.port
    except ValueError as error:
        raise _BadResponse("invalid page URL") from error
    if (url.scheme != "https" or url.hostname != "callofduty.fandom.com" or url.username or url.password
            or port not in (None, 443) or not url.path.startswith("/wiki/") or url.query or url.fragment):
        raise _BadResponse("invalid page URL")
    return value


def _license(rights):
    if not isinstance(rights, dict):
        raise _BadResponse("license unavailable")
    name = _text(rights.get("text"), 120, required=True)
    key = re.sub(r"[^a-z0-9]", "", name.lower())
    url = _text(rights.get("url"), 500, required=True)
    if not key.startswith("ccbysa") or url != "https://www.fandom.com/licensing":
        raise _BadResponse("license changed")
    return name, url


def _request(query, category, game):
    search = " ".join(part for part in [query, _CATEGORY_TERMS[category], _GAME_TERMS[game]] if part)
    return {
        "action": "query", "meta": "siteinfo", "siprop": "rightsinfo",
        "generator": "search", "gsrsearch": search, "gsrlimit": MAX_RESULTS, "gsrnamespace": 0,
        "prop": "info|revisions", "inprop": "url", "rvprop": "ids|timestamp|content",
        "rvslots": "main", "rvsection": 0, "format": "json", "formatversion": 2,
    }


def _normalize(data, query, category, game):
    if not isinstance(data, dict) or data.get("error") or data.get("warnings"):
        raise _BadResponse("wiki API error")
    result = data.get("query")
    if not isinstance(result, dict):
        raise _BadResponse("invalid query result")
    license_name, license_url = _license(result.get("rightsinfo"))
    pages = result.get("pages", [])
    if not isinstance(pages, list) or len(pages) > MAX_RESULTS:
        raise _BadResponse("invalid result count")
    items = []
    for page in sorted(pages, key=lambda p: p.get("index", 100) if isinstance(p, dict) else 100):
        if not isinstance(page, dict) or page.get("missing") or page.get("ns") != 0:
            raise _BadResponse("missing public article")
        title = _text(page.get("title"), 250, required=True)
        url = _page_url(page.get("fullurl"))
        revisions = page.get("revisions")
        if not isinstance(revisions, list) or len(revisions) != 1 or not isinstance(revisions[0], dict):
            raise _BadResponse("revision unavailable")
        revision = revisions[0]
        revid = revision.get("revid")
        if type(revid) is not int or revid <= 0:
            raise _BadResponse("revision unavailable")
        timestamp = _text(revision.get("timestamp"), 80, required=True)
        slots = revision.get("slots")
        if not isinstance(slots, dict) or not isinstance(slots.get("main"), dict):
            raise _BadResponse("article text unavailable")
        # This is MediaWiki revision JSON, unrelated to Discord message events.
        content = slots["main"]["content"] if "content" in slots["main"] else None
        if not isinstance(content, str):
            raise _BadResponse("article text unavailable")
        items.append({"title": title, "extract": _plain_intro(content), "page_url": url,
                      "url": url + "?oldid=" + str(revid), "revision": revid, "timestamp": timestamp,
                      "license_name": license_name, "license_url": license_url})
    search_url = "https://callofduty.fandom.com/wiki/Special:Search?" + encode_query({"query": _request(query, category, game)["gsrsearch"]})
    return {"schema_version": _VERSION, "provider": "Call of Duty Wiki", "query": query,
            "category": category, "game": game, "items": items, "source_url": search_url,
            "attribution": {"text": "Call of Duty Wiki contributors", "url": WIKI_URL,
                            "license_name": license_name, "license_url": license_url},
            "adaptation": "Excerpt shortened; wiki formatting removed.",
            "coverage": "Wiki search results; check each article's game and revision date."}


def _time(value):
    return float(value) if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def _view(state, query, category, game, now, error=None):
    snapshot = state.get("snapshot")
    if (not isinstance(snapshot, dict) or snapshot.get("schema_version") != _VERSION
            or not isinstance(snapshot.get("query"), str) or snapshot["query"].casefold() != query.casefold()
            or snapshot.get("category") != category or snapshot.get("game") != game
            or not isinstance(snapshot.get("items"), list) or not isinstance(snapshot.get("attribution"), dict)):
        snapshot = None
    if snapshot is not None:
        try:
            if len(snapshot["items"]) > MAX_RESULTS:
                raise _BadResponse("invalid cached result count")
            credit = snapshot["attribution"]
            _license({"text": credit.get("license_name"), "url": credit.get("license_url")})
            if credit.get("text") != "Call of Duty Wiki contributors" or credit.get("url") != WIKI_URL:
                raise _BadResponse("invalid cached attribution")
            for item in snapshot["items"]:
                _text(item.get("title"), 250, required=True)
                if not isinstance(item.get("extract"), str):
                    raise _BadResponse("invalid cached excerpt")
                _text(item.get("extract"), MAX_EXTRACT_CHARS)
                _text(item.get("timestamp"), 80, required=True)
                _license({"text": item.get("license_name"), "url": item.get("license_url")})
                page_url = _page_url(item.get("page_url"))
                revision = item.get("revision")
                if type(revision) is not int or revision <= 0 or item.get("url") != page_url + "?oldid=" + str(revision):
                    raise _BadResponse("invalid cached revision")
        except (_BadResponse, AttributeError):
            snapshot = None
    fetched, attempted = _time(state.get("fetched_at")), _time(state.get("last_attempt"))
    reason = error or state.get("last_error")
    stale = snapshot is not None and (fetched is None or now - fetched >= MIN_REFRESH_SECONDS or bool(reason))
    result = copy.deepcopy(snapshot) if snapshot is not None else {
        "provider": "Call of Duty Wiki", "query": query, "category": category, "game": game, "items": [],
        "attribution": {"text": "Call of Duty Wiki contributors", "url": WIKI_URL,
                        "license_name": "CC-BY-SA", "license_url": "https://www.fandom.com/licensing"},
        "adaptation": "Excerpt shortened; wiki formatting removed.",
    }
    warning = None
    if snapshot is None:
        warning = "Wiki references are temporarily unavailable. Offline build tools still work."
    elif stale:
        warning = "Showing cached wiki references. Check the linked revision dates."
    elif not result["items"]:
        warning = "No matching wiki articles were found for these search terms."
    result.update({"available": snapshot is not None, "stale": stale, "warning": warning,
                   "error": reason, "fetched_at": fetched,
                   "next_refresh_at": attempted + MIN_REFRESH_SECONDS if attempted is not None else None})
    return result


def _reject_json_number(value):
    raise _BadResponse("invalid JSON number")


def get_reference(ctx, query, category="all", game="all", *, now=None):
    """Find up to five revision-cited article intros, cached for at least 12h."""
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 120 or any(ord(c) < 32 for c in query):
        raise ValueError("Enter an article name or a few search terms, up to 120 characters.")
    query = " ".join(query.split())
    category = _CATEGORIES.get(str(category).strip().lower())
    game = _GAMES.get(str(game).strip().lower())
    if category is None or game is None:
        raise ValueError("Unsupported reference category or game.")
    now = time.time() if now is None else _time(now)
    if now is None:
        raise ValueError("Invalid refresh time.")
    digest = hashlib.sha256(json.dumps([query.casefold(), category, game], separators=(",", ":")).encode()).hexdigest()
    key = "codwiki:v1:" + digest
    with _LOCK:
        try:
            state = ctx.kv.get(key)
        except Exception:
            return _view({}, query, category, game, now, "cache_unavailable")
        if not isinstance(state, dict) or state.get("version") != _VERSION:
            state = {"version": _VERSION}
        attempted = _time(state.get("last_attempt"))
        if attempted is not None and now - attempted < MIN_REFRESH_SECONDS:
            return _view(state, query, category, game, now)
        try:
            if not ctx.ephemeral.dedup("codhub:reference:" + digest, ttl_seconds=MIN_REFRESH_SECONDS):
                return _view(state, query, category, game, now, "refresh_pending")
            pending = copy.deepcopy(state)
            pending.update({"last_attempt": now, "last_error": "refresh_pending"})
            ctx.kv.set(key, pending, ttl_seconds=86_400)
        except Exception:
            return _view(state, query, category, game, now, "cache_unavailable")
        try:
            response = ctx.http.request("GET", API_URL, params=_request(query, category, game),
                                        headers={"Accept": "application/json", "User-Agent": "CODHub-YourBot (https://yourbot.gg)"})
            if not isinstance(response, dict) or response.get("status") != 200:
                raise _BadResponse("http_status")
            if response.get("truncated"):
                raise _BadResponse("truncated")
            body = response.get("body_bytes")
            if isinstance(body, bytes):
                body = body.decode("utf8")
            if not isinstance(body, str) or len(body.encode("utf8")) > MAX_RESPONSE_BYTES:
                raise _BadResponse("response_size")
            data = json.loads(body, parse_constant=_reject_json_number)
            snapshot = _normalize(data, query, category, game)
            ready = {"version": _VERSION, "last_attempt": now, "fetched_at": now,
                     "last_error": None, "snapshot": snapshot}
            if len(json.dumps(ready, ensure_ascii=True, separators=(",", ":")).encode()) > 60_000:
                raise _BadResponse("cache_size")
            ctx.kv.set(key, ready, ttl_seconds=86_400)
            return _view(ready, query, category, game, now)
        except _BadResponse as error:
            reason = str(error)
        except (ValueError, TypeError, UnicodeError):
            reason = "invalid_response"
        except Exception:
            reason = "refresh_failed"
        pending["last_error"] = reason
        try:
            ctx.kv.set(key, pending, ttl_seconds=86_400)
        except Exception:
            pass
        return _view(pending, query, category, game, now)
