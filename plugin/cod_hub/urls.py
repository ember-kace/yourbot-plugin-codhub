"""Pure URL text handling for citations and the plugin's fixed provider hosts.

This supports absolute HTTPS URLs with ASCII DNS-style authorities. It performs
no requests, DNS lookups or URL resolution. Unsupported authority forms fail
closed; callers retain their exact provider-host and path allowlists.
"""
import re
from typing import NamedTuple


_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\Z")
_BAD_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")
_ESCAPE = re.compile(r"%([0-9A-Fa-f]{2})")
_DOT_ESCAPE = re.compile(r"%2e", re.I)
_UNRESERVED = frozenset(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")


class HTTPSParts(NamedTuple):
    scheme: str
    netloc: str
    path: str
    query: str
    fragment: str
    hostname: str
    port: int | None
    username: None = None
    password: None = None


def split_https(value):
    """Split a strict HTTPS citation without decoding or changing its text.

    Unicode, spaces and Markdown punctuation are retained in path/query/fragment
    so display code can percent-encode them. Credentials, ambiguous authorities,
    controls, malformed escapes and path traversal/separator escapes are rejected.
    DNS-style hosts include the ASCII punycode form of internationalized names;
    bracketed IP literals and other unsupported authority syntax are rejected.
    """
    if not isinstance(value, str):
        raise TypeError("URL must be text.")
    if (not value or len(value) > 8192 or value[:8].lower() != "https://"
            or any(ord(char) < 32 or ord(char) == 127 or char == "\\" for char in value)):
        raise ValueError("URL must be an unambiguous absolute HTTPS URL.")
    try:
        value.encode("utf8")
    except UnicodeError as error:
        raise ValueError("URL contains invalid Unicode.") from error
    remainder = value[8:]
    end = min((pos for marker in "/?#" if (pos := remainder.find(marker)) >= 0), default=len(remainder))
    authority, tail = remainder[:end], remainder[end:]
    if (not authority or not authority.isascii() or "@" in authority
            or any(char.isspace() for char in authority) or any(char in authority for char in "%[]")):
        raise ValueError("URL authority must be an ASCII host without credentials.")
    hostname, port = authority, None
    if ":" in authority:
        if authority.count(":") != 1:
            raise ValueError("Unsupported URL authority.")
        hostname, digits = authority.split(":", 1)
        if not digits or len(digits) > 5 or not all("0" <= char <= "9" for char in digits):
            raise ValueError("URL port must be decimal.")
        port = int(digits)
        if port > 65535:
            raise ValueError("URL port is outside its supported range.")
    dns_name = hostname[:-1] if hostname.endswith(".") else hostname
    if (not dns_name or len(dns_name) > 253
            or any(not _LABEL.fullmatch(label) for label in dns_name.split("."))):
        raise ValueError("URL host is malformed.")
    before_fragment, separator, fragment = tail.partition("#")
    path, separator, query = before_fragment.partition("?")
    if _BAD_ESCAPE.search(tail):
        raise ValueError("URL contains malformed percent escapes.")
    for match in _ESCAPE.finditer(tail):
        byte = int(match.group(1), 16)
        if byte < 32 or byte == 127:
            raise ValueError("URL contains escaped control characters.")
    if any(int(match.group(1), 16) in (47, 92) for match in _ESCAPE.finditer(path)):
        raise ValueError("URL path contains escaped separators.")
    if any(part in (".", "..") for part in _DOT_ESCAPE.sub(".", path).split("/")):
        raise ValueError("URL path contains dot segments.")
    return HTTPSParts("https", authority, path, query, fragment, hostname.lower(), port)


def percent_encode(value, safe=""):
    """Percent-encode UTF-8 text, retaining RFC 3986 unreserved ASCII bytes."""
    if not isinstance(value, str) or not isinstance(safe, str) or not safe.isascii():
        raise TypeError("URL encoding requires text and an ASCII safe set.")
    allowed = _UNRESERVED | frozenset(safe.encode("ascii"))
    return "".join(chr(byte) if byte in allowed else "%" + format(byte, "02X") for byte in value.encode("utf8"))


def encode_query(values):
    """Encode a mapping of text pairs as UTF-8 form-query text; spaces become +."""
    if not isinstance(values, dict):
        raise TypeError("Query parameters must be a mapping of text pairs.")
    pairs = []
    for key, value in values.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise TypeError("Query names and values must be text.")
        pairs.append(percent_encode(key).replace("%20", "+") + "=" + percent_encode(value).replace("%20", "+"))
    return "&".join(pairs)
