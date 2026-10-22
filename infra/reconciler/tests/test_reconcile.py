import base64
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "rootfs/usr/local/libexec/peer-reconciler/reconcile.py"
DEFAULT_CONFIG_PATH = Path(__file__).parents[1] / "rootfs/etc/peer-reconciler/config.json"
VALIDATOR_PATH = Path(__file__).parents[2] / "images/router/rootfs/usr/local/libexec/event-router/render_inventory.py"
SPEC = importlib.util.spec_from_file_location("reconcile", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def peer(peer_id="peer-a", team=1, host=200, byte=1):
    return {
        "peer_id": peer_id,
        "team_id": f"team-{team:02d}",
        "team_number": team,
        "public_key": base64.b64encode(bytes([byte]) * 32).decode(),
        "address": f"10.80.{team}.{host}/32",
    }


def inventory(generation, peers):
    return {"version": 1, "generation": generation, "peers": peers}


def config():
    return {
        "validator_path": str(VALIDATOR_PATH),
        "gateways": {"standby": "10.60.250.11", "primary": "10.60.250.10"},
    }


class ReconcileTests(unittest.TestCase):
    def test_default_config_matches_the_internal_arena_contract(self):
        value = MODULE.load_config(DEFAULT_CONFIG_PATH)
        self.assertEqual(value["endpoint"], "https://finals.h7tex.com/api/v1/internal/arena/vpn/peers")
        self.assertEqual(value["gateways"], {
            "standby": "10.60.250.11",
            "primary": "10.60.250.10",
        })

    def test_no_change_does_not_publish(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            MODULE.atomic_write_json(state / "active.json", inventory(4, [peer()]))
            published = []
            result = MODULE.reconcile(
                config(), state,
                fetcher=lambda _: [peer()],
                publisher=lambda *args: published.append(args),
            )
            self.assertEqual(result, "unchanged")
            self.assertEqual(published, [])
            self.assertFalse((state / "pending.json").exists())

    def test_standby_failure_leaves_primary_and_active_state_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            MODULE.atomic_write_json(state / "active.json", inventory(3, [peer()]))
            calls = []

            def fail_standby(_, role, address, payload):
                calls.append((role, address))
                raise MODULE.ReconcileError("unavailable")

            with self.assertRaises(MODULE.ReconcileError):
                MODULE.reconcile(config(), state, lambda _: [peer("peer-b", byte=2)], fail_standby)
            self.assertEqual(calls, [("standby", "10.60.250.11")])
            self.assertEqual(json.loads((state / "active.json").read_text())["generation"], 3)
            self.assertEqual(json.loads((state / "pending.json").read_text())["generation"], 4)

    def test_partial_failure_replays_pending_without_refetching(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            MODULE.atomic_write_json(state / "active.json", inventory(1, [peer()]))
            first_calls = []

            def fail_primary(_, role, address, payload):
                first_calls.append(role)
                if role == "primary":
                    raise MODULE.ReconcileError("unavailable")

            with self.assertRaises(MODULE.ReconcileError):
                MODULE.reconcile(config(), state, lambda _: [peer("peer-b", byte=2)], fail_primary)
            self.assertEqual(first_calls, ["standby", "primary"])

            second_calls = []

            def no_fetch(_):
                raise AssertionError("pending state must be retried before fetching")

            result = MODULE.reconcile(
                config(), state, no_fetch,
                lambda _, role, address, payload: second_calls.append(role),
            )
            self.assertEqual(result, "applied")
            self.assertEqual(second_calls, ["standby", "primary"])
            self.assertEqual(json.loads((state / "active.json").read_text())["generation"], 2)
            self.assertFalse((state / "pending.json").exists())

    def test_invalid_desired_state_never_publishes(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            published = []
            invalid = peer()
            invalid["private_key"] = "forbidden"
            with self.assertRaises(MODULE.ReconcileError):
                MODULE.reconcile(
                    config(), state,
                    fetcher=lambda _: [invalid],
                    publisher=lambda *args: published.append(args),
                )
            self.assertEqual(published, [])


if __name__ == "__main__":
    unittest.main()
