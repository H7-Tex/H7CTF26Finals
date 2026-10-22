import importlib.machinery
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "rootfs/usr/local/sbin/event-router-capture"
LOADER = importlib.machinery.SourceFileLoader("event_router_capture", str(MODULE_PATH))
SPEC = importlib.util.spec_from_loader("event_router_capture", LOADER)
MODULE = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(MODULE)


class CaptureTests(unittest.TestCase):
    def test_retention_and_crash_loss_bounds_are_event_sized(self):
        self.assertGreaterEqual(MODULE.MAX_LOG_BYTES * MODULE.RETAINED_LOGS, 300 * 1024 ** 3)
        self.assertLessEqual(MODULE.FLUSH_INTERVAL_SECONDS, 2)
        self.assertLessEqual(MODULE.MAX_BUFFER_BYTES, 1024 ** 2)

    def test_conntrack_event_is_correlated_to_peer_and_team(self):
        with tempfile.TemporaryDirectory() as directory:
            inventory = Path(directory) / "active.json"
            inventory.write_text(json.dumps({
                "version": 1,
                "generation": 12,
                "peers": [{
                    "peer_id": "player-7",
                    "team_id": "team-03",
                    "team_number": 3,
                    "public_key": "unused-by-capture",
                    "address": "10.80.3.207/32",
                }],
            }), encoding="utf-8")
            generation, peers = MODULE.correlations(
                "[NEW] tcp src=10.80.3.207 dst=10.60.3.2 sport=40000 dport=7001",
                inventory,
            )
            self.assertEqual(generation, 12)
            self.assertEqual(peers, [{
                "address": "10.80.3.207",
                "peer_id": "player-7",
                "team_id": "team-03",
                "team_number": 3,
            }])

    def test_logs_are_size_bounded_and_rotated(self):
        with tempfile.TemporaryDirectory() as directory:
            events = Path(directory) / "events.jsonl"
            for sequence in range(8):
                MODULE.append_event(events, {"event": "test", "sequence": sequence}, maximum=70, retained=2)
            self.assertTrue(events.exists())
            self.assertTrue(events.with_name("events.jsonl.1").exists())
            self.assertFalse(events.with_name("events.jsonl.3").exists())
            event_types = []
            for path in Path(directory).glob("events.jsonl*"):
                if path.name.endswith(".lock"):
                    continue
                event_types.extend(json.loads(line)["event"] for line in path.read_text().splitlines())
            self.assertIn("log_rollover", event_types)
            self.assertIn("retention_drop", event_types)

    def test_writer_batches_until_flush_or_size_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            events = Path(directory) / "events.jsonl"
            writer = MODULE.EventWriter(events, buffer_limit=1024)
            writer.append({"event": "one"})
            self.assertFalse(events.exists())
            writer.flush()
            self.assertEqual(json.loads(events.read_text())["event"], "one")

    def test_inventory_cache_refreshes_when_file_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            inventory = Path(directory) / "active.json"
            def write(generation, address):
                inventory.write_text(json.dumps({
                    "version": 1,
                    "generation": generation,
                    "peers": [{
                        "peer_id": f"player-{generation}",
                        "team_id": "team-03",
                        "team_number": 3,
                        "public_key": "unused-by-capture",
                        "address": f"{address}/32",
                    }],
                }), encoding="utf-8")
                os.utime(inventory, ns=(generation * 1_000_000_000, generation * 1_000_000_000))

            write(1, "10.80.3.207")
            cache = MODULE.InventoryCache(inventory)
            self.assertEqual(cache.correlate("src=10.80.3.207 dst=10.60.3.2")[0], 1)
            write(2, "10.80.3.208")
            generation, peers = cache.correlate("src=10.80.3.208 dst=10.60.3.2")
            self.assertEqual(generation, 2)
            self.assertEqual(peers[0]["peer_id"], "player-2")

    def test_start_event_reports_collection_gap(self):
        event = MODULE.gap_event({"clean_shutdown": False, "heartbeat_epoch": 100.0}, 112.5)
        self.assertEqual(event["event"], "collection_gap")
        self.assertFalse(event["previous_clean_shutdown"])
        self.assertEqual(event["gap_seconds"], 12.5)


if __name__ == "__main__":
    unittest.main()
