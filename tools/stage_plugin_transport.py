"""Exercise the real plugin subprocess and SDK JSON-RPC transport, without Discord.

The host is deliberately local: KV is in memory and HTTP returns a fixed outage.
Unknown RPC methods fail. It never opens a network connection or reads game files.
Use --command to replace the Python child with an isolated Linux container.
"""
from __future__ import annotations

import argparse
import base64
from copy import deepcopy
import json
import os
from pathlib import Path
import queue
import struct
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "plugin/manifest.json").read_text(encoding="utf-8"))
NATIVE_ART = json.loads((ROOT / "plugin/cod_hub/data/native-artwork.json").read_text(encoding="utf-8"))
CAPS = ["interaction:respond", "storage:kv", "discord:send_message", "proxy:http"]
CODE = "A01-42J19-BU11"


def components(payload):
    return [item for row in payload.get("components", []) for item in row["components"]]


def control(payload, label):
    return next(item["custom_id"] for item in components(payload) if item.get("label") == label)


def menu(payload, placeholder):
    return next(item for item in components(payload) if item.get("placeholder") == placeholder)


def message_contract(payload):
    """Validate actual serialized messages, independently of SDK mock objects."""
    total = 0
    for embed in payload.get("embeds", []):
        assert len(embed.get("title", "")) <= 256
        assert len(embed.get("description", "")) <= 4096
        assert len(embed.get("fields", [])) <= 25
        total += len(embed.get("title", "")) + len(embed.get("description", ""))
        total += len(embed.get("footer", {}).get("text", "")) + len(embed.get("author", {}).get("name", ""))
        for field in embed.get("fields", []):
            assert 0 < len(field["name"]) <= 256
            assert 0 < len(field["value"]) <= 1024
            total += len(field["name"]) + len(field["value"])
    assert total <= 6000
    assert len(payload.get("components", [])) <= 5
    for row in payload.get("components", []):
        assert len(row["components"]) <= 5
        for item in row["components"]:
            assert len(item.get("custom_id", "")) <= 100
            if item["type"] == 3:
                assert len(row["components"]) == 1
                assert 1 <= len(item["options"]) <= 25
                for option in item["options"]:
                    assert 0 < len(option["label"]) <= 100
                    assert 0 < len(option["value"]) <= 100
    assert payload.get("allowed_mentions") == {"parse": []}


def modal_contract(payload):
    """Validate the SDK's serialized modal rows, not MockContext's raw fields."""
    assert 0 < len(payload["title"]) <= 45
    assert 0 < len(payload["custom_id"]) <= 100
    rows = payload.get("components")
    assert isinstance(rows, list) and 1 <= len(rows) <= 5
    seen = set()
    for row in rows:
        assert row.get("type") == 1
        assert len(row.get("components", [])) == 1
        field = row["components"][0]
        assert field.get("type") == 4
        assert field.get("style") in (1, 2)
        assert 0 < len(field["custom_id"]) <= 100
        assert field["custom_id"] not in seen
        seen.add(field["custom_id"])
        assert 0 < len(field["label"]) <= 45
        assert isinstance(field.get("required", True), bool)
        assert len(field.get("placeholder", "")) <= 100
        assert len(field.get("value", "")) <= 4000
        assert 0 <= field.get("min_length", 0) <= field.get("max_length", 4000) <= 4000


def modal_fields(payload):
    return {row["components"][0]["custom_id"]: row["components"][0] for row in payload["components"]}


class LocalHost:
    def __init__(self, command, kv=None):
        self.kv = kv if kv is not None else {}
        self.events, self.calls, self.logs, self.errors = {}, [], [], []
        self.messages, self.http_requests = [], []
        self.acks, self.boots = set(), set()
        self.queue = queue.Queue()
        environment = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        self.process = subprocess.Popen(command, cwd=ROOT, env=environment, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                        encoding="utf-8", bufsize=1)
        self.stderr = []
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=lambda: self.stderr.extend(self.process.stderr.readlines()), daemon=True).start()

    def _read(self):
        try:
            for line in self.process.stdout:
                self.queue.put(json.loads(line))
        except Exception as error:
            self.errors.append("Non-JSON child stdout: " + str(error))
        finally:
            self.queue.put(None)

    def write(self, payload):
        self.process.stdin.write(json.dumps(payload, ensure_ascii=True) + "\n")
        self.process.stdin.flush()

    def pump(self, until, timeout=20):
        deadline = time.monotonic() + timeout
        while not until():
            left = deadline - time.monotonic()
            assert left > 0, "Plugin transport timed out"
            value = self.queue.get(timeout=left)
            assert value is not None, "Plugin exited early: " + "".join(self.stderr)
            if value.get("id") in self.boots:
                self.boots.remove(value["id"])
                assert "error" not in value, value
                continue
            method, params = value.get("method"), value.get("params", {})
            if method == "plugin.log":
                self.logs.append(params)
                assert params.get("level") != "error", params
                continue
            if method == "event.ack":
                self.acks.update(params.get("event_ids", []))
                continue
            assert method != "event.fail", value
            event_id = params.get("_event_id")
            assert event_id in self.events, value
            event = self.events[event_id]
            assert params.get("_pool_discord_srv_id") == event["server"], value
            self.calls.append({"method": method, "params": deepcopy(params)})
            try:
                result = self.rpc(method, params, event)
            except Exception as error:
                self.errors.append(str(error))
                self.write({"jsonrpc": "2.0", "id": value["id"], "error": {"message": str(error)}})
                raise
            self.write({"jsonrpc": "2.0", "id": value["id"], "result": result})

    def rpc(self, method, params, event):
        namespace = event["server"]
        if method.startswith("interaction."):
            assert params["_interaction_id"] == event["interaction_id"]
            if method in {"interaction.respond", "interaction.defer", "interaction.send_modal"}:
                assert not event["acknowledgments"], "Double initial interaction acknowledgment"
                event["acknowledgments"].append(method)
                event["ack_ms"] = round((time.monotonic() - event["started"]) * 1000, 3)
                assert event["ack_ms"] < 3000, "Interaction missed the 3-second deadline"
            else:
                assert event["acknowledgments"] == ["interaction.defer"], "Followup without defer"
            if method in {"interaction.respond", "interaction.followup"}:
                message_contract(params)
                event["messages"].append(deepcopy(params))
            elif method == "interaction.send_modal":
                assert event["acknowledgments"] == [method]
                modal_contract(params)
                event["modals"].append(deepcopy(params))
            return {"message_id": "700", "channel_id": "333"}
        assert event["acknowledgments"], "Work before initial interaction acknowledgment"
        if method == "kv.get":
            return {"value": deepcopy(self.kv.get((namespace, params["key"])))}
        if method == "kv.put":
            self.kv[(namespace, params["key"])] = deepcopy(params["value"])
            return {}
        if method == "kv.del":
            self.kv.pop((namespace, params["key"]), None)
            return {}
        if method == "kv.list":
            keys = sorted(k for server, k in self.kv if server == namespace and k.startswith(params["prefix"]))
            if params.get("count_only"):
                return {"count": len(keys)}
            return {"keys": [k for k in keys if k > params.get("start_after", "")][:params["limit"]]}
        if method == "kv.mget":
            return {"values": {k: deepcopy(self.kv[(namespace, k)]) for k in params["keys"] if (namespace, k) in self.kv}}
        if method == "ephemeral.dedup":
            return {"is_new": True}
        if method == "proxy.request":
            self.http_requests.append(deepcopy(params))
            return {"status": 503, "body_bytes": "Local staging outage fixture", "headers": {}, "truncated": False}
        if method == "discord.send_message":
            assert event["allow_post"], "Unexpected public message"
            message_contract(params)
            self.messages.append(deepcopy(params))
            return {"message_id": "701", "channel_id": params["channel_id"]}
        raise AssertionError("Unexpected host RPC: " + str(method))

    def boot(self, mode):
        token = "boot-" + mode
        self.boots.add(token)
        self.write({"jsonrpc": "2.0", "id": token, "method": "host.boot", "params": {
            "discord_srv_id": "999", "plugin_id": MANIFEST["id"], "version": MANIFEST["version"],
            "capabilities": CAPS, "mode": mode}})
        self.pump(lambda: not self.boots)

    def event(self, *, name=None, custom_id=None, server="999", user="111", allow_post=False, **fields):
        token = "stage-" + str(len(self.events) + 1)
        iid = "interaction-" + token
        event = {"interaction_type": 2 if name else 3, "user_id": user, "channel_id": "333",
                 "interaction_id": iid, **fields}
        event.update({"command_name": name} if name else {"custom_id": custom_id})
        self.events[token] = {"server": server, "interaction_id": iid, "started": time.monotonic(),
                              "acknowledgments": [], "messages": [], "modals": [], "allow_post": allow_post}
        self.write({"jsonrpc": "2.0", "method": "event.interaction_create", "params": {
            "event_id": token, "event": event, "discord_srv_id": server,
            "plugin_id": MANIFEST["id"], "version": MANIFEST["version"], "capabilities": CAPS}})
        self.pump(lambda: token in self.acks)
        result = self.events[token]
        assert len(result["acknowledgments"]) == 1
        return (result["messages"][-1] if result["messages"]
                else result["modals"][-1] if result["modals"] else {})

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
                self.errors.append("Child needed forced termination")
        assert self.process.returncode == 0, "".join(self.stderr)
        assert not self.errors, self.errors

    def child_memory(self):
        """Read only this owned Python child's OS counters, never game processes."""
        if self.process.args[0] != sys.executable:
            return {"measured": False, "reason": "External launcher: measure the actual worker/container separately."}
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            class Counters(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                    (name, ctypes.c_size_t) for name in ("PeakWorkingSetSize", "WorkingSetSize",
                    "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                    "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]

            counters = Counters()
            counters.cb = ctypes.sizeof(counters)
            query = ctypes.WinDLL("psapi", use_last_error=True).GetProcessMemoryInfo
            query.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
            query.restype = wintypes.BOOL
            assert query(int(self.process._handle), ctypes.byref(counters), counters.cb)
            return {"measured": True, "scope": "Owned Windows Python child, not Linux cgroup usage",
                    "peak_working_set_bytes": counters.PeakWorkingSetSize,
                    "working_set_bytes": counters.WorkingSetSize}
        return {"measured": False, "reason": "Use worker/container memory accounting for this platform."}


def exercise(command):
    result, shared_kv = [], {}
    for mode in ("dedicated", "pool"):
        host = LocalHost(command, shared_kv)
        try:
            host.boot(mode)
            home = host.event(name="codhub")
            assert home["embeds"][0]["title"] == "COD Hub"
            assert [len(row["components"]) for row in home["components"]] == [3, 4]
            assert [item["label"] for item in components(home)] == [
                "Import code", "My builds", "Compare", "Weapons", "Item catalog", "Meta builds", "Game guide"]
            assert sum(item.get("style") == 1 for item in components(home)) == 1
            assert not home["embeds"][0].get("fields"), "Public launcher should not contain personal fields"
            native_items = host.event(custom_id=control(home, "Item catalog"))
            assert native_items["ephemeral"] and native_items["embeds"][0]["title"] == "MW4 catalog"
            categories = menu(native_items, "Choose an item category")
            assert any(row["value"] == "camo" for row in categories["options"])
            camos = host.event(custom_id=categories["custom_id"], values=["camo"])
            selection = menu(camos, "Choose an item")
            first_camo = host.event(custom_id=selection["custom_id"], values=[selection["options"][0]["value"]])
            assert first_camo["ephemeral"]
            assert first_camo["embeds"][0]["title"]
            assert control(first_camo, "Post card to channel")
            assert not host.http_requests, "Item browsing must not request a data or image provider"
            guide_home = host.event(custom_id=control(home, "Game guide"))
            assert guide_home["ephemeral"] and guide_home["embeds"][0]["title"] == "MW4 game guide"
            guide_categories = menu(guide_home, "Choose a guide category")
            maps = host.event(custom_id=guide_categories["custom_id"], values=["maps"])
            guide_selection = menu(maps, "Choose a guide reference")
            map_card = host.event(custom_id=guide_selection["custom_id"], values=[guide_selection["options"][0]["value"]])
            assert map_card["ephemeral"] and "Reference ID" in str(map_card["embeds"])
            assert control(map_card, "Post card to channel")
            assert not host.http_requests, "Native guide must stay offline"
            import_control = next(item for item in components(home) if item.get("custom_id") == "chh:import")
            before = len(host.calls)
            import_form = host.event(custom_id=import_control["custom_id"])
            assert [call["method"] for call in host.calls[before:]] == ["interaction.send_modal"]
            fields = modal_fields(import_form)
            assert fields["code"]["required"] and not fields["title"]["required"]
            assert fields["code"]["placeholder"] == CODE
            imported = host.event(custom_id=import_form["custom_id"], interaction_type=5,
                                  modal_values={"code": CODE, "title": "Transport staging"})
            assert imported["ephemeral"] and CODE in str(imported["embeds"])
            expected_image = "https://ember-kace.github.io/yourbot-plugin-codhub/artwork/v1/" + NATIVE_ART["build_images"][CODE]["filename"]
            assert imported["embeds"][0]["image"]["url"] == expected_image
            assert "Native attachment preview" in imported["embeds"][0]["description"]
            assert not host.http_requests, "Native image selection must not fetch artwork"
            assert control(imported, "Show code") and control(imported, "Post to channel")
            assert control(imported, "Post PNG to channel")
            saved = host.event(custom_id=control(imported, "Save"))
            empty_setup = host.event(custom_id=control(home, "Compare"))
            assert empty_setup["ephemeral"] and empty_setup["embeds"][0]["title"] == "Set up a comparison"
            assert next(item for item in components(empty_setup) if item.get("label") == "Compare A / B")["disabled"]
            # Reproduce the exact reported entry point: Astaroth .57 -> Compare.
            weapon = host.event(custom_id="chh:openweapon:R03")
            setup = host.event(custom_id=control(weapon, "Compare"))
            assert setup["ephemeral"] and "Astaroth .57" in str(setup["embeds"][0]["fields"])
            filters = menu(setup, "Filter comparison weapons")
            assault = next(option["value"] for option in filters["options"] if "assault" in option["label"].lower())
            setup = host.event(custom_id=filters["custom_id"], values=[assault])
            choices = menu(setup, "Choose weapon for B")
            second = next(option["value"] for option in choices["options"] if option["label"] == "M4")
            setup = host.event(custom_id=choices["custom_id"], values=[second])
            run = next(item for item in components(setup) if item.get("label") == "Compare A / B")
            assert not run.get("disabled")
            gui_comparison = host.event(custom_id=run["custom_id"])
            assert gui_comparison["ephemeral"] and gui_comparison["update_message"]
            assert "Astaroth .57" in str(gui_comparison["embeds"]) and "M4" in str(gui_comparison["embeds"])
            assert "couldn't open" not in str(gui_comparison).lower()
            before = len(host.calls)
            paste_form = host.event(custom_id=control(setup, "Paste names / codes"))
            assert [call["method"] for call in host.calls[before:]] == ["interaction.send_modal"]
            assert modal_fields(paste_form)["left"]["value"] == "Astaroth .57"
            assert modal_fields(paste_form)["right"]["value"] == "M4"
            pasted_comparison = host.event(custom_id=paste_form["custom_id"], interaction_type=5,
                                            modal_values={"left": CODE, "right": "M4"})
            assert pasted_comparison["ephemeral"] and CODE in str(pasted_comparison["embeds"])
            missing_graphs = menu(pasted_comparison, "Comparison view")
            assert {item["value"] for item in missing_graphs["options"]} == {"overview", "details"}
            # A valid side survives a rejected B input through the real modal wire.
            recovered = host.event(custom_id=paste_form["custom_id"], interaction_type=5,
                                   modal_values={"left": CODE, "right": "no-such-weapon-for-transport"})
            assert recovered["ephemeral"] and "B needs another selection" in recovered["content"]
            assert CODE in str(recovered["embeds"][0]["fields"])
            filters = menu(recovered, "Filter comparison weapons")
            assault = next(option["value"] for option in filters["options"] if "assault" in option["label"].lower())
            recovered = host.event(custom_id=filters["custom_id"], values=[assault])
            choices = menu(recovered, "Choose weapon for B")
            second = next(option["value"] for option in choices["options"] if option["label"] == "M4")
            recovered = host.event(custom_id=choices["custom_id"], values=[second])
            recovered = host.event(custom_id=control(recovered, "Compare A / B"))
            assert recovered["ephemeral"] and CODE in str(recovered["embeds"])
            assert "M4" in str(recovered["embeds"])
            host.event(name="codweapon", options={"query": "A01"})
            host.event(name="codattachment", options={"query": "FSS TAC90 GRIP", "weapon": "A01"})
            listing = host.event(name="codsaved", options={"action": "list"})
            assert "Transport staging" in listing["embeds"][0]["description"]
            comparison = host.event(name="codcompare", options={"left": "A01", "right": "A05", "view": "dps"})
            assert {item["value"] for item in menu(comparison, "Comparison view")["options"]} == {"overview", "dps", "details"}
            graphs = control(comparison, "Post graphs to channel")
            host.event(custom_id=graphs, allow_post=True)
            files = host.messages[-1]["files"]
            pngs = [f for f in files if f["filename"].endswith(".png")]
            notes = [f for f in files if f["filename"].endswith(".txt")]
            assert pngs and len(notes) == 1, "Graphs must include complete measurement notes"
            decoded = base64.b64decode(pngs[0]["data_b64"], validate=True)
            assert decoded.startswith(b"\x89PNG\r\n\x1a\n")
            note = base64.b64decode(notes[0]["data_b64"], validate=True).decode("utf-8")
            assert "https://www.callofduty.com/" in note and "2026-11-05" in note and "2026-10-19" in note
            details = host.event(custom_id=control(host.messages[-1], "Measurements / sources"), user="222")
            assert details["ephemeral"] and details["embeds"][0]["title"] == "Measurements / sources"
            next_details = next(item for item in components(details) if item.get("label") == "Next details")
            if not next_details.get("disabled"):
                page_two = host.event(custom_id=next_details["custom_id"], user="222")
                assert page_two.get("update_message") and "Details 2/" in page_two["embeds"][0]["footer"]["text"]
                denied = host.event(custom_id=next_details["custom_id"], user="111")
                assert "another person" in denied["content"] and denied["ephemeral"]
            host.event(name="codmeta", options={"mode": "multiplayer"})
            host.event(name="codreference", options={"query": "Sample map"})
            host.event(name="codsaved", options={"action": "list"}, user="222")
            if mode == "pool":
                other = host.event(name="codsaved", options={"action": "list"}, server="888")
                assert "empty" in other.get("content", "").lower(), "Tenant storage leaked"
            assert len(host.messages) == 1, "Unexpected implicit public message"
            result.append({"mode": mode, "events": len(host.events), "rpc_calls": len(host.calls),
                           "maximum_initial_ack_ms": max(e["ack_ms"] for e in host.events.values()),
                           "modal_forms_checked": sum(len(e["modals"]) for e in host.events.values()),
                           "gui_journeys": ["native_item_catalog", "native_game_guide", "home_import", "home_comparison_setup", "astaroth_weapon_comparison", "pasted_build_comparison", "invalid_side_recovery", "available_graph_views"],
                           "public_messages_simulated": len(host.messages), "http_outage_fixtures": len(host.http_requests),
                           "chart_dimensions": list(struct.unpack_from(">II", decoded, 16)),
                           "attachments": [f["filename"] for f in files],
                           "child_memory": host.child_memory(), "failures": []})
        finally:
            host.close()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command or [sys.executable, "-u", str(ROOT / "plugin/__main__.py")]
    report = {"scope": "Real SDK subprocess transport with a simulated local host, not a Discord or YourBot installation",
              "platform": sys.platform, "command": ["python", "-u", "plugin/__main__.py"] if not args.command else ["custom command"], "runs": exercise(command),
              "external_network_calls": 0, "installed_game_access": False, "release_output": False}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
