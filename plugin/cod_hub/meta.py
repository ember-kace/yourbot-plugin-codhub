"""Optional attributed MetaRadar display feed, fetched through YourBot's proxy.

No static provider feed is bundled. A durable rolling cooldown also applies to
failed refreshes; Redis deduplication prevents parallel refreshes across workers.
"""
from __future__ import annotations

import copy
import json
import math
import threading
import time
from urllib.parse import urlsplit

PROVIDER = "MetaRadar"
TERMS_URL = "https://metaradar.gg/developers"
MIN_REFRESH_SECONDS = 3600
MAX_RESPONSE_BYTES = 200_000
MAX_CACHE_BYTES = 60_000
_CACHE_VERSION = 1
_REFRESH_LOCK = threading.Lock()
_SLUGS = {"mw4": "modernwarfare4", "bo7": "blackops7", "warzone": "warzone"}
_ALIASES = {
    "mw4": "mw4", "modernwarfare4": "mw4", "modern warfare 4": "mw4",
    "bo7": "bo7", "blackops7": "bo7", "black ops 7": "bo7", "warzone": "warzone",
}


class _InvalidFeed(ValueError):
    pass


def _text(value, limit, *, required=False):
    if value is None and not required:
        return None
    if not isinstance(value, str) or len(value) > limit:
        raise _InvalidFeed("invalid text field")
    value = value.strip()
    if (required and not value) or any(ord(char) < 32 for char in value):
        raise _InvalidFeed("invalid text field")
    return value


def _url(value, *, required=False):
    if value is None and not required:
        return None
    value = _text(value, 1200, required=required)
    try:
        parsed = urlsplit(value or "")
        port = parsed.port
    except ValueError as error:
        raise _InvalidFeed("invalid provider link") from error
    if (parsed.scheme != "https" or parsed.hostname not in {"metaradar.gg", "www.metaradar.gg"}
            or parsed.username or parsed.password or port not in (None, 443)):
        raise _InvalidFeed("invalid provider link")
    return value


def _normalize_feed(feed, game):
    if not isinstance(feed, dict) or not isinstance(feed.get("game"), dict):
        raise _InvalidFeed("invalid feed")
    if feed["game"].get("slug") != _SLUGS[game]:
        raise _InvalidFeed("wrong game")
    credit = feed.get("attribution")
    if not isinstance(credit, dict):
        raise _InvalidFeed("missing attribution")
    attribution = {"text": _text(credit.get("text"), 200, required=True),
                   "url": _url(credit.get("url"), required=True)}
    source_rows = feed.get("weapons")
    if not isinstance(source_rows, list) or not 1 <= len(source_rows) <= 300:
        raise _InvalidFeed("invalid weapon list")
    rows, seen_slugs, seen_ranks = [], set(), set()
    for source in source_rows:
        if not isinstance(source, dict):
            raise _InvalidFeed("invalid weapon")
        rank = source.get("rank")
        slug = _text(source.get("slug"), 160, required=True)
        if type(rank) is not int or not 1 <= rank <= 10_000 or rank in seen_ranks or slug in seen_slugs:
            raise _InvalidFeed("invalid ranking")
        seen_ranks.add(rank)
        seen_slugs.add(slug)
        build = source.get("build")
        if build is None:
            build = {}
        if not isinstance(build, dict):
            raise _InvalidFeed("invalid build")
        parts = build.get("attachments", [])
        if not isinstance(parts, list) or len(parts) > 20:
            raise _InvalidFeed("invalid attachments")
        attachments = []
        for part in parts:
            if not isinstance(part, dict):
                raise _InvalidFeed("invalid attachment")
            attachments.append({"slot": _text(part.get("slot"), 80, required=True),
                                "name": _text(part.get("name"), 200, required=True)})
        icons = source.get("icons") or []
        if not isinstance(icons, list):
            raise _InvalidFeed("invalid icons")
        icon_url = None
        for icon in icons[:8]:
            try:
                icon_url = _url(icon, required=True)
            except _InvalidFeed:
                continue
            break
        rows.append({
            "name": _text(source.get("name"), 180, required=True), "slug": slug,
            "rank": rank, "tier": _text(source.get("tier"), 80),
            "tier_letter": _text(source.get("tierLetter"), 8),
            "class": _text(source.get("class"), 80),
            "role": _text(source.get("role"), 160),
            "mode": _text(build.get("mode"), 80),
            "build_label": _text(build.get("label"), 160),
            "attachments": attachments,
            "code": _text(build.get("shareCode"), 128),
            "url": _url(source.get("url"), required=True),
            "icon_url": icon_url,
            "updated_at": _text(build.get("updatedAt"), 80),
        })
    # Keep provider ranking; COD Hub must not create a competing tier list.
    rows.sort(key=lambda row: row["rank"])
    return {
        "schema_version": _CACHE_VERSION, "provider": PROVIDER, "game": game,
        "provider_game": _SLUGS[game], "game_name": _text(feed["game"].get("name"), 120),
        "source_url": _url(feed["game"].get("url"), required=True),
        "terms_url": TERMS_URL, "attribution": attribution,
        "updated_at": _text(feed.get("updatedAt"), 80, required=True),
        "season": _text(feed.get("season"), 80),
        "coverage": "MetaRadar ranked recommendations; not a complete game catalog.",
        "weapons": rows,
    }


def _timestamp(value):
    return (float(value) if type(value) in (int, float) and math.isfinite(value)
            and value >= 0 else None)


def _reject_json_number(token):
    raise _InvalidFeed("invalid_json")


def _cached_snapshot(state, game):
    value = state.get("snapshot")
    if not isinstance(value, dict) or value.get("schema_version") != _CACHE_VERSION:
        return None
    if value.get("game") != game or value.get("provider") != PROVIDER:
        return None
    rows, credit = value.get("weapons"), value.get("attribution")
    if not isinstance(rows, list) or not rows or not isinstance(credit, dict):
        return None
    try:
        _text(credit.get("text"), 200, required=True)
        _url(credit.get("url"), required=True)
        for row in rows:
            if not isinstance(row, dict):
                return None
            _text(row.get("name"), 180, required=True)
            _url(row.get("url"), required=True)
    except _InvalidFeed:
        return None
    return value


def _view(state, game, now, *, error=None):
    snapshot = _cached_snapshot(state, game)
    fetched = _timestamp(state.get("fetched_at"))
    last_attempt = _timestamp(state.get("last_attempt"))
    reason = error or state.get("last_error")
    stale = snapshot is not None and (fetched is None or now - fetched >= MIN_REFRESH_SECONDS or bool(reason))
    if snapshot is None:
        result = {"provider": PROVIDER, "game": game, "provider_game": _SLUGS[game],
                  "weapons": [], "updated_at": None,
                  "attribution": {"text": "Data by MetaRadar", "url": "https://metaradar.gg/"},
                  "terms_url": TERMS_URL, "source_url": "https://metaradar.gg/"}
    else:
        result = copy.deepcopy(snapshot)
    warning = None
    if snapshot is None:
        warning = "MetaRadar recommendations are temporarily unavailable. Offline build tools still work."
    elif stale:
        warning = "Showing cached MetaRadar recommendations; the latest refresh is unavailable."
    result.update({"available": snapshot is not None, "stale": stale,
                   "warning": warning, "error": reason,
                   "fetched_at": fetched,
                   "next_refresh_at": last_attempt + MIN_REFRESH_SECONDS if last_attempt is not None else None})
    return result


def get_meta(ctx, game, *, now=None):
    """Return an attributed feed view; upstream/storage failures are nonfatal.

    SDK methods are synchronous. Call this after deferring an interaction.
    ``now`` is an optional Unix timestamp for deterministic integration tests.
    """
    game = _ALIASES.get(str(game).strip().lower())
    if game is None:
        raise ValueError("Meta recommendations support MW4, BO7 and Warzone.")
    now = time.time() if now is None else _timestamp(now)
    if now is None:
        raise ValueError("Invalid refresh time.")
    key = "metaradar:v1:" + game
    with _REFRESH_LOCK:
        try:
            state = ctx.kv.get(key)
        except Exception:
            return _view({}, game, now, error="cache_unavailable")
        if not isinstance(state, dict) or state.get("version") != _CACHE_VERSION:
            state = {"version": _CACHE_VERSION}
        attempted = _timestamp(state.get("last_attempt"))
        if attempted is not None and now - attempted < MIN_REFRESH_SECONDS:
            return _view(state, game, now)
        try:
            if not ctx.ephemeral.dedup("codhub:metaradar:refresh:" + game, ttl_seconds=MIN_REFRESH_SECONDS):
                return _view(state, game, now, error="refresh_pending")
        except Exception:
            # Without a cross-worker claim, do not risk an extra upstream fetch.
            return _view(state, game, now, error="refresh_unavailable")
        pending = copy.deepcopy(state)
        pending.update({"last_attempt": now, "last_error": "refresh_pending"})
        try:
            ctx.kv.set(key, pending)
        except Exception:
            return _view(state, game, now, error="cache_unavailable")
        reason = None
        try:
            response = ctx.http.request("GET", "https://metaradar.gg/api/v1/meta/" + _SLUGS[game],
                                        headers={"Accept": "application/json"})
            if not isinstance(response, dict) or response.get("status") != 200:
                raise _InvalidFeed("http_status")
            if response.get("truncated"):
                raise _InvalidFeed("truncated")
            body = response.get("body_bytes")
            if isinstance(body, bytes):
                body = body.decode("utf8")
            if not isinstance(body, str) or len(body.encode("utf8")) > MAX_RESPONSE_BYTES:
                raise _InvalidFeed("response_size")
            feed = json.loads(body, parse_constant=_reject_json_number)
            snapshot = _normalize_feed(feed, game)
            ready = {"version": _CACHE_VERSION, "last_attempt": now,
                     "fetched_at": now, "snapshot": snapshot, "last_error": None}
            if len(json.dumps(ready, ensure_ascii=True, separators=(",", ":")).encode("utf8")) > MAX_CACHE_BYTES:
                raise _InvalidFeed("cache_size")
            ctx.kv.set(key, ready)
            return _view(ready, game, now)
        except _InvalidFeed as error:
            reason = str(error)
        except (ValueError, TypeError, UnicodeError):
            reason = "invalid_response"
        except Exception:
            reason = "refresh_failed"
        pending["last_error"] = reason
        try:
            ctx.kv.set(key, pending)
        except Exception:
            pass
        return _view(pending, game, now)
