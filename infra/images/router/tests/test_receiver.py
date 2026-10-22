import base64
import importlib.machinery
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "rootfs/usr/local/sbin/event-router-receive-inventory"
VALIDATOR_PATH = Path(__file__).parents[1] / "rootfs/usr/local/libexec/event-router/render_inventory.py"
LOADER = importlib.machinery.SourceFileLoader("receive_inventory", str(MODULE_PATH))
SPEC = importlib.util.spec_from_loader("receive_inventory", LOADER)
MODULE = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(MODULE)


def peer(byte=1):
    return {
        "peer_id": "peer-a",
        "team_id": "team-01",
        "team_number": 1,
        "public_key": base64.b64encode(bytes([byte]) * 32).decode(),
        "address": "10.80.1.200/32",
    }


def payload(generation, peers=None):
    return json.dumps({
        "version": 1,
        "generation": generation,
        "peers": [peer()] if peers is None else peers,
    }).encode()


class ReceiverTests(unittest.TestCase):
    def paths(self, directory):
        root = Path(directory)
        return root / "active.json", root / "staged.json"

    def test_valid_inventory_is_atomically_staged_and_applied(self):
        with tempfile.TemporaryDirectory() as directory:
            active, staged = self.paths(directory)
            result = MODULE.receive(io.BytesIO(payload(1)), active, staged, VALIDATOR_PATH, Path("/bin/true"))
            self.assertEqual(result, ("applied", 1, 1))
            self.assertEqual(json.loads(staged.read_text())["generation"], 1)
            self.assertEqual(staged.stat().st_mode & 0o777, 0o600)

    def test_exact_replay_is_a_no_op(self):
        with tempfile.TemporaryDirectory() as directory:
            active, staged = self.paths(directory)
            active.write_bytes(payload(2))
            result = MODULE.receive(io.BytesIO(payload(2)), active, staged, VALIDATOR_PATH, Path("/bin/false"))
            self.assertEqual(result, ("unchanged", 2, 1))
            self.assertFalse(staged.exists())

    def test_out_of_order_inventory_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            active, staged = self.paths(directory)
            active.write_bytes(payload(3))
            with self.assertRaises(MODULE.ReceiveError):
                MODULE.receive(io.BytesIO(payload(2)), active, staged, VALIDATOR_PATH, Path("/bin/true"))
            self.assertEqual(json.loads(active.read_text())["generation"], 3)

    def test_changed_replay_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            active, staged = self.paths(directory)
            active.write_bytes(payload(3))
            with self.assertRaises(MODULE.ReceiveError):
                MODULE.receive(io.BytesIO(payload(3, [peer(2)])), active, staged, VALIDATOR_PATH, Path("/bin/true"))

    def test_oversized_input_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            active, staged = self.paths(directory)
            with self.assertRaisesRegex(MODULE.ReceiveError, "invalid size"):
                MODULE.receive(
                    io.BytesIO(b"x" * (MODULE.MAX_INVENTORY_BYTES + 1)),
                    active, staged, VALIDATOR_PATH, Path("/bin/true"),
                )

    def test_apply_failure_keeps_active_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            active, staged = self.paths(directory)
            active.write_bytes(payload(1))
            with self.assertRaisesRegex(MODULE.ReceiveError, "apply failed"):
                MODULE.receive(io.BytesIO(payload(2)), active, staged, VALIDATOR_PATH, Path("/bin/false"))
            self.assertEqual(json.loads(active.read_text())["generation"], 1)


if __name__ == "__main__":
    unittest.main()
