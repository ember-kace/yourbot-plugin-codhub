"""Bounded, mode-scoped reviewed telemetry; unavailable data stays unavailable."""
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path

from .comparison import normalize_mode, validate_profile

DATA = Path(__file__).parent / "data/telemetry.json"
MAX_BYTES = 1_000_000


def _unique(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("Duplicate telemetry key.")
        out[key] = value
    return out


@lru_cache(maxsize=1)
def _load(path):
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            return {}, "00000000"
        data = json.loads(raw, object_pairs_hook=_unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite telemetry")))
        if data.get("format_version") != 1 or data.get("game") != "mw4" or set(data["profiles"]) != {"multiplayer", "dmz", "warzone"}:
            return {}, "00000000"
        result = {}
        for mode, source in data["profiles"].items():
            if not isinstance(source, dict) or len(source) > 128:
                raise ValueError("Invalid telemetry collection.")
            result[mode] = {}
            for key, value in source.items():
                profile = validate_profile(value, mode=mode)
                expected = profile["asset_id"] if profile["variant"]["kind"] == "base" else profile["variant"]["code"]
                if key != expected:
                    raise ValueError("Telemetry identity mismatch.")
                result[mode][key] = profile
        return result, hashlib.sha256(raw).hexdigest()[:8]
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        return {}, "00000000"


def profiles_for(mode):
    return snapshot(mode)[0]


def snapshot(mode):
    """Return profiles and their fingerprint from one immutable cached read."""
    data, digest = _load(str(DATA))
    return deepcopy(data.get(normalize_mode(mode), {})), digest


def fingerprint():
    return _load(str(DATA))[1]


def clear_cache():
    _load.cache_clear()
