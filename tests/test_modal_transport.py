"""Exercise the actual SDK modal serialization that MockContext does not perform."""
from copy import deepcopy
import json
import unittest

from yourbot_sdk import Context

from cod_hub import comparison_ui, hub
from tools.stage_plugin_transport import MANIFEST, modal_contract, modal_fields


class WireTransport:
    def __init__(self):
        self.calls = []

    def call(self, method, params):
        # A real transport JSON-encodes every outbound call. Raw TextInput
        # objects or incomplete rows must never pass this boundary unnoticed.
        self.calls.append((method, json.loads(json.dumps(params))))
        return {}

    def notify(self, method, params):
        raise AssertionError("Unexpected SDK notification: " + method)


def context():
    transport = WireTransport()
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
