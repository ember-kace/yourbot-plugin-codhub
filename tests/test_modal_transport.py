"""Exercise the actual SDK modal serialization that MockContext does not perform."""
from copy import deepcopy
import json
import unittest

from yourbot_sdk import Context, DiscordApiError, CapabilityError, RateLimitError, RpcTimeoutError, __version__

from cod_hub import comparison_ui, hub
from tools.stage_plugin_transport import MANIFEST, message_contract, modal_contract, modal_fields


class WireTransport:
    def __init__(self, rejection=None, recovery_rejection=None):
        self.calls = []
        self.notifications = []
        self.rejection = rejection
        self.recovery_rejection = recovery_rejection

    def call(self, method, params):
        # A real transport JSON-encodes every outbound call. Raw TextInput
        # objects or incomplete rows must never pass this boundary unnoticed.
        self.calls.append((method, json.loads(json.dumps(params))))
        if method == "interaction.send_modal" and self.rejection is not None:
            raise self.rejection
        if method == "interaction.respond" and self.recovery_rejection is not None:
            raise self.recovery_rejection
        return {}

    def notify(self, method, params):
        self.notifications.append((method, json.loads(json.dumps(params))))


def context(rejection=None, recovery_rejection=None):
    transport = WireTransport(rejection, recovery_rejection)
    ctx = Context(server_id="999", plugin_id=MANIFEST["id"], version=MANIFEST["version"],
                  capabilities=["interaction:respond"], transport=transport)
    ctx._current_interaction_id = "modal-contract"
    return ctx, transport


class ModalWireContracts(unittest.TestCase):
    def test_gui_import_uses_one_immediate_modal_with_serialized_code_fields(self):
        ctx, transport = context()
        hub.handle_component(ctx, {"custom_id": "chh:import", "user_id": "111"})
        self.assertEqual([method for method, _ in transport.calls], ["interaction.send_modal"])
        payload = transport.calls[0][1]
        modal_contract(payload)
        self.assertEqual(payload["custom_id"], hub.IMPORT_MODAL)
        self.assertEqual(payload["_interaction_id"], "modal-contract")
        fields = modal_fields(payload)
        self.assertEqual(set(fields), {"code", "title"})
        self.assertTrue(fields["code"]["required"])
        self.assertFalse(fields["title"]["required"])

    def test_discord_rejected_hub_popups_offer_private_slash_recovery_once(self):
        forms = (
            ("chh:import", hub.IMPORT_MODAL, "import_build", "/codbuild code:<your build code>"),
            ("chh:search", hub.SEARCH_MODAL, "weapon_search", "/codweapon query:<weapon name>"),
            ("chh:reference", hub.REFERENCE_MODAL, "reference_search", "/codreference query:<search>"),
        )
        for control, modal, form, command in forms:
            with self.subTest(form=form):
                error = DiscordApiError("Discord API error 400: synthetic-secret-request-details", status_code=400)
                ctx, transport = context(error)
                hub.handle_component(ctx, {"custom_id": control, "user_id": "111"})
                self.assertEqual([method for method, _ in transport.calls],
                                 ["interaction.send_modal", "interaction.respond"])
                modal_contract(transport.calls[0][1])
                self.assertEqual(transport.calls[0][1]["custom_id"], modal)
                response = transport.calls[-1][1]
                message_contract(response)
                self.assertTrue(response["ephemeral"])
                self.assertNotIn("update_message", response)
                self.assertIn(command, response["content"])
                self.assertNotIn("couldn't open that card", response["content"])
                controls = response["components"][0]["components"]
                self.assertEqual([item["custom_id"] for item in controls], [control, "chh:private"])
                self.assertEqual(len(transport.notifications), 1)
                method, diagnostic = transport.notifications[0]
                self.assertEqual(method, "plugin.log")
                self.assertEqual(diagnostic["extra"], {
                    "method": "interaction.send_modal", "form": form, "sdk_version": __version__,
                    "error_type": "DiscordApiError", "error_code": "DISCORD_API_ERROR", "status_code": "400",
                })
                self.assertNotIn("synthetic-secret-request-details", str(transport.calls) + str(transport.notifications))
                self.assertNotIn("111", str(diagnostic))

    def test_hub_popup_timeout_permission_and_rate_failures_do_not_retry_or_leak(self):
        for error in (RpcTimeoutError("synthetic-private-host-detail"),
                      CapabilityError("synthetic-private-host-detail"),
                      RateLimitError("synthetic-private-host-detail", retry_after=30)):
            with self.subTest(error=type(error).__name__):
                ctx, transport = context(error)
                hub.handle_component(ctx, {"custom_id": "chh:import", "user_id": "111"})
                self.assertEqual([method for method, _ in transport.calls],
                                 ["interaction.send_modal", "interaction.respond"])
                diagnostic = transport.notifications[0][1]["extra"]
                self.assertEqual(diagnostic["error_code"], error.code)
                self.assertNotIn("status_code", diagnostic)
                self.assertTrue(transport.calls[-1][1]["ephemeral"])
                self.assertNotIn("synthetic-private-host-detail", str(transport.calls) + str(transport.notifications))

    def test_failed_popup_recovery_stops_after_one_private_response_attempt(self):
        ctx, transport = context(
            DiscordApiError("Discord API error 400: private-modal-request", status_code=400),
            DiscordApiError("Discord API error 404: private-expired-interaction", status_code=404))
        hub.handle_component(ctx, {"custom_id": "chh:import", "user_id": "111"})
        self.assertEqual([method for method, _ in transport.calls],
                         ["interaction.send_modal", "interaction.respond"])
        self.assertTrue(transport.calls[-1][1]["ephemeral"])
        diagnostics = [payload["extra"] for method, payload in transport.notifications if method == "plugin.log"]
        self.assertEqual([entry["method"] for entry in diagnostics],
                         ["interaction.send_modal", "interaction.respond"])
        self.assertEqual([entry["status_code"] for entry in diagnostics], ["400", "404"])
        self.assertTrue(all(entry["form"] == "import_build" for entry in diagnostics))
        self.assertNotIn("private-modal-request", str(transport.calls) + str(transport.notifications))
        self.assertNotIn("private-expired-interaction", str(transport.calls) + str(transport.notifications))

    def test_hub_popup_diagnostics_reject_untrusted_error_metadata(self):
        class UntrustedError(RuntimeError):
            status_code = True

        for code in ("private-token-in-code", "SYNTHETIC_PRIVATE_HOST_TOKEN", 987654321):
            with self.subTest(code=code):
                error = UntrustedError("private-response-body")
                error.code = code
                ctx, transport = context(error)
                hub.handle_component(ctx, {"custom_id": "chh:import", "user_id": "111"})
                diagnostic = transport.notifications[0][1]["extra"]
                self.assertNotIn("error_code", diagnostic)
                self.assertNotIn("status_code", diagnostic)
                self.assertNotIn(str(code), str(transport.notifications))
                self.assertNotIn("private-response", str(transport.calls) + str(transport.notifications))

    def test_pasted_comparison_uses_the_same_real_serialization_contract(self):
        ctx, transport = context()
        comparison_ui._form(ctx, "Astaroth .57")
        self.assertEqual([method for method, _ in transport.calls], ["interaction.send_modal"])
        payload = transport.calls[0][1]
        modal_contract(payload)
        self.assertEqual(payload["custom_id"], comparison_ui.MODAL)
        self.assertEqual(modal_fields(payload)["left"]["value"], "Astaroth .57")
        self.assertTrue(modal_fields(payload)["right"]["required"])

    def test_wire_validator_rejects_empty_or_unwrapped_modal_fields(self):
        ctx, transport = context()
        comparison_ui._form(ctx)
        payload = transport.calls[0][1]
        broken = deepcopy(payload)
        broken["components"] = []
        with self.assertRaises(AssertionError):
            modal_contract(broken)
        broken["components"] = [payload["components"][0]["components"][0]]
        with self.assertRaises(AssertionError):
            modal_contract(broken)


if __name__ == "__main__":
    unittest.main()
