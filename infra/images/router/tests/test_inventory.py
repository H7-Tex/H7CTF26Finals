#!/usr/bin/env python3
import base64
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "rootfs/usr/local/libexec/event-router/render_inventory.py"
SPEC = importlib.util.spec_from_file_location("render_inventory", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def public_key(byte):
    return base64.b64encode(bytes([byte]) * 32).decode()


def inventory(peers):
    return {"version": 1, "generation": 7, "peers": peers}


def peer(peer_id, team, host, key_byte):
    return {
        "peer_id": peer_id,
        "team_id": f"team-{team:02d}",
        "team_number": team,
        "public_key": public_key(key_byte),
        "address": f"10.80.{team}.{host}/32",
    }


class InventoryTests(unittest.TestCase):
    def test_renders_distinct_peers_to_one_team_identity(self):
        wireguard, nftables = MODULE.render(inventory([
            peer("peer-a", 3, 201, 1),
            peer("peer-b", 3, 202, 2),
        ]))
        self.assertIn("AllowedIPs = 10.80.3.201/32", wireguard)
        self.assertIn("10.80.3.201 : 10.60.250.123", nftables)
        self.assertIn("10.80.3.202 : 10.60.250.123", nftables)
        self.assertIn("10.80.3.201 . 10.61.3.2", nftables)
        self.assertIn("10.80.3.202 . 10.61.3.2", nftables)

    def test_production_ssh_reaches_only_the_own_team_box(self):
        peers = inventory([peer("peer-a", 3, 201, 1), peer("peer-b", 7, 205, 2)])
        _, closed = MODULE.render(peers)
        self.assertIn("flush set inet event_router peer_production_access", closed)
        self.assertNotIn("add element inet event_router peer_production_access", closed)
        _, opened = MODULE.render(peers, production_ssh=True)
        line = next(item for item in opened.splitlines() if "add element inet event_router peer_production_access" in item)
        self.assertIn("10.80.3.201 . 10.60.3.2", line)
        self.assertIn("10.80.7.205 . 10.60.7.2", line)
        self.assertNotIn("10.80.3.201 . 10.60.7.2", line)

    def test_team_bound_follows_the_constant(self):
        with self.assertRaises(ValueError):
            MODULE.render(inventory([peer("peer-a", MODULE.MAX_TEAM_NUMBER + 1, 201, 1)]))

    def test_rejects_duplicate_addresses(self):
        with self.assertRaisesRegex(ValueError, "addresses must be unique"):
            MODULE.render(inventory([
                peer("peer-a", 1, 200, 1),
                peer("peer-b", 1, 200, 2),
            ]))

    def test_rejects_private_material(self):
        record = peer("peer-a", 1, 200, 1)
        record["private_key"] = public_key(2)
        with self.assertRaisesRegex(ValueError, "must contain only"):
            MODULE.render(inventory([record]))

    def test_rejects_address_outside_team_pool(self):
        with self.assertRaisesRegex(ValueError, "team's 10.80.T.200-239 pool"):
            MODULE.render(inventory([peer("peer-a", 4, 199, 1)]))

    def test_load_rejects_unknown_top_level_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "peers.json"
            path.write_text(json.dumps({**inventory([]), "user_id": "forbidden"}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "only version, generation and peers"):
                MODULE.load_inventory(path)

    def test_generation_is_monotonic_and_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            active_path = Path(directory) / "active.json"
            active = inventory([peer("peer-a", 1, 200, 1)])
            active_path.write_text(json.dumps(active), encoding="utf-8")
            MODULE.ensure_successor(active, active_path)
            with self.assertRaisesRegex(ValueError, "without a new generation"):
                MODULE.ensure_successor(inventory([]), active_path)
            stale = {**active, "generation": 6}
            with self.assertRaisesRegex(ValueError, "cannot move backward"):
                MODULE.ensure_successor(stale, active_path)


if __name__ == "__main__":
    unittest.main()
