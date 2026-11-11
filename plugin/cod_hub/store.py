"""Durable, owner-scoped build records without shared mutable indexes.

Saved records have no TTL. Previews use 512 fixed keys per server and expire;
collisions can invalidate old preview buttons but never replace a saved record.
Striped locks coordinate SDK dispatch threads in this process. With no KV CAS,
the 50-save admission limit is advisory across distinct pooled worker processes.
"""
import hashlib
import re
import threading
import time


MAX_SAVED = 50
PREVIEW_SLOTS = 512
PREVIEW_TTL = 7 * 24 * 60 * 60
_OWNER = re.compile(r"[0-9]{1,22}\Z")
_IDENTIFIER = re.compile(r"[a-f0-9]{16}\Z")
_SNAPSHOT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
_LOCKS = [threading.RLock() for _ in range(64)]


def owner_id(value):
    value = str(value or "")
    if not _OWNER.fullmatch(value):
        raise ValueError("This action needs a Discord user identity.")
    return value


def build_id(game, code):
    return hashlib.sha256((game + "\0" + code).encode("utf-8")).hexdigest()[:16]


def clean_title(value):
    return " ".join(str(value or "").replace("`", "'").split())[:80]


class BuildStore:
    def __init__(self, kv, server_id=""):
        self.kv = kv
        self.server_id = str(server_id)

    def _lock(self, owner):
        index = int(hashlib.sha256((self.server_id + ":" + owner).encode()).hexdigest()[:8], 16)
        return _LOCKS[index % len(_LOCKS)]

    @staticmethod
    def _saved_prefix(owner):
        return "codhub:saved:" + owner_id(owner) + ":"

    def _key(self, kind, owner, identifier):
        owner = owner_id(owner)
        if not isinstance(identifier, str) or not _IDENTIFIER.fullmatch(identifier):
            raise ValueError("Use the build ID shown by /codsaved.")
        if kind == "s":
            return self._saved_prefix(owner) + identifier
        if kind != "p":
            raise ValueError("That build reference is invalid.")
        digest = hashlib.sha256((owner + ":" + identifier).encode()).hexdigest()
        return "codhub:preview:" + str(int(digest[:8], 16) % PREVIEW_SLOTS).zfill(3)

    @staticmethod
    def _valid(record, owner, identifier):
        return (isinstance(record, dict) and record.get("schema") == 1
                and record.get("owner") == owner and record.get("id") == identifier
                and record.get("game") == "mw4" and isinstance(record.get("code"), str)
                and 0 < len(record["code"]) <= 256
                and build_id(record["game"], record["code"]) == identifier)

    def get(self, kind, owner, identifier):
        owner = owner_id(owner)
        record = self.kv.get(self._key(kind, owner, identifier))
        if not self._valid(record, owner, identifier):
            return None
        return dict(record)

    def preview(self, owner, build, title=None):
        owner = owner_id(owner)
        code = build.get("code")
        game = build.get("game")
        if game != "mw4" or not isinstance(code, str) or not 0 < len(code) <= 256:
            raise ValueError("This build cannot be stored in the MW4 library.")
        identifier = build_id(game, code)
        record = {"schema": 1, "id": identifier, "owner": owner, "game": game,
                  "code": code, "title": clean_title(title or build.get("title")
                    or build.get("weapon", {}).get("name") or "MW4 build"),
                  "created_at": int(time.time())}
        snapshot = build.get("snapshot_date")
        if isinstance(snapshot, str) and _SNAPSHOT.fullmatch(snapshot):
            record["snapshot_date"] = snapshot
        self.kv.set(self._key("p", owner, identifier), record, ttl_seconds=PREVIEW_TTL)
        return record

    def save(self, owner, source):
        owner = owner_id(owner)
        code, game = source.get("code"), source.get("game")
        if game != "mw4" or not isinstance(code, str) or not 0 < len(code) <= 256:
            raise ValueError("That build record is invalid. Import the build again to create a new preview.")
        identifier = build_id(game, code)
        key = self._key("s", owner, identifier)
        with self._lock(owner):
            existing = self.get("s", owner, identifier)
            if existing is not None:
                return existing, False
            if self.kv.count(prefix=self._saved_prefix(owner)) >= MAX_SAVED:
                raise ValueError("Your library has 50 builds. Delete a saved build from My builds before saving another.")
            record = {"schema": 1, "id": identifier, "owner": owner, "game": game,
                      "code": code, "title": clean_title(source.get("title") or "MW4 build"),
                      "created_at": int(time.time())}
            snapshot = source.get("snapshot_date")
            if isinstance(snapshot, str) and _SNAPSHOT.fullmatch(snapshot):
                record["snapshot_date"] = snapshot
            self.kv.set(key, record)
            return record, True

    def list_saved(self, owner):
        owner = owner_id(owner)
        # A cross-worker admission race can exceed the advisory 50 limit;
        # retain visibility of those independent records so they can be deleted.
        keys = self.kv.list(prefix=self._saved_prefix(owner), limit=100)
        values = {}
        for at in range(0, len(keys), 50):
            values.update(self.kv.get_many(keys[at:at + 50]))
        records = []
        for key in keys:
            record = values.get(key)
            identifier = key.rsplit(":", 1)[-1]
            if self._valid(record, owner, identifier):
                records.append(dict(record))
        return sorted(records, key=lambda r: (-int(r.get("created_at", 0)), r["id"]))

    def delete(self, owner, identifier):
        owner = owner_id(owner)
        with self._lock(owner):
            record = self.get("s", owner, identifier)
            if record is None:
                return False
            self.kv.delete(self._key("s", owner, identifier))
            return True

    def rename(self, owner, identifier, title):
        """Rename one existing saved record without changing identity or TTL."""
        owner = owner_id(owner)
        if not isinstance(title, str) or not 0 < len(title) <= 80:
            raise ValueError("Use a build name between 1 and 80 characters.")
        title = clean_title(title)
        if not title:
            raise ValueError("Give the saved build a name.")
        with self._lock(owner):
            record = self.get("s", owner, identifier)
            if record is None:
                raise ValueError("That saved build wasn't found in your library.")
            record["title"] = title
            self.kv.set(self._key("s", owner, identifier), record)
            return dict(record)
