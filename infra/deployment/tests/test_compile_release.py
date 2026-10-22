import copy
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


DEPLOYMENT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("compile_release", DEPLOYMENT / "compile-release.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def final_release():
    release = json.loads((DEPLOYMENT / "release.template.json").read_text(encoding="utf-8"))
    for index, service in enumerate(release["services"], 1):
        service["base_commit"] = f"{index:x}" * 40
        service["bundle_sha256"] = f"{index:x}" * 64
        service["factory_image"] = f"registry.invalid/finals/{service['slug']}@sha256:{index:x}" + "a" * 63
        service["private_gate_artifact"] = f"registry.invalid/finals/{service['slug']}-gate@sha256:{index:x}" + "b" * 63
    return release


def team():
    return {
        "schema_version": 1,
        "team_id": "11111111-1111-4111-8111-111111111111",
        "team_number": 1,
        "allowed_uid": 991,
        "repository_path": "/var/lib/deployment-orchestrator/repository",
    }


class ReleaseCompilerTests(unittest.TestCase):
    def test_checked_in_template_locks_six_mappings_but_cannot_compile(self):
        template = json.loads((DEPLOYMENT / "release.template.json").read_text(encoding="utf-8"))
        self.assertEqual(
            [(service["slot"], service["slug"], service["protocol"], service["port"]) for service in template["services"]],
            [
                ("AD1", "sign-me-in", "http", 7001),
                ("AD2", "can-we-settle-this", "http", 7002),
                ("AD3", "update-pending", "tcp", 7003),
                ("AD4", "book-me-if-you-can", "http", 7004),
                ("AD5", "ship-it", "http", 7005),
                ("AD6", "terms-may-apply", "http", 7006),
            ],
        )
        with self.assertRaisesRegex(MODULE.ReleaseError, "final base commit"):
            MODULE.validate_release(template)

    def test_compiles_all_outputs_from_one_release(self):
        release = final_release()
        MODULE.validate_release(release)
        MODULE.validate_team(team())
        services, executor, volumes, proxy = MODULE.compile_documents(release, team())
        self.assertEqual(services["schema_version"], 1)
        self.assertEqual(len(services["services"]), 6)
        expected_service_keys = {
            "slug", "base_commit", "bundle_sha256", "factory_digest", "allowed_paths",
            "maximum_context_bytes", "memory_bytes", "cpu_millis", "pids", "build_timeout",
            "gate_timeout", "promotion_timeout", "health_timeout", "previous_flag_ticks",
        }
        self.assertTrue(all(set(service) == expected_service_keys for service in services["services"]))
        self.assertEqual(json.dumps(services).count('"promotion_timeout"'), 6)
        terms = next(service for service in services["services"] if service["slug"] == "terms-may-apply")
        self.assertEqual(terms["maximum_context_bytes"], 100 * 1024 * 1024)
        self.assertEqual(executor["schema_version"], 2)
        self.assertEqual(executor["live_address"], "10.60.1.2")
        self.assertEqual(executor["staging_address"], "10.60.1.3")
        self.assertEqual(set(executor["commands"]), {"build", "gate", "promote", "rollback", "health"})
        self.assertEqual(len(volumes["services"]), 6)
        ship = next(service for service in volumes["services"] if service["slug"] == "ship-it")
        self.assertEqual(ship["quota"], {"bytes": 2147483648, "inodes": 131072})
        self.assertEqual(ship["generations"]["recovery"]["project_id"], 27005)
        self.assertEqual(proxy.count("frontend live_"), 6)
        self.assertEqual(proxy.count("frontend staging_"), 6)
        for port in range(7001, 7007):
            self.assertEqual(proxy.count(f"bind 10.60.1.2:{port}"), 1)
            self.assertEqual(proxy.count(f"bind 10.60.1.3:{port}"), 1)
            self.assertEqual(proxy.count(f"server slot_a 127.0.0.1:{port + 10000} check disabled"), 1)
            self.assertEqual(proxy.count(f"server slot_b 127.0.0.1:{port + 11000} check disabled"), 1)
            self.assertEqual(proxy.count(f"server gate 127.0.0.1:{port + 12000} check disabled"), 1)
        self.assertNotIn("send-proxy", proxy)
        self.assertNotIn("forwardfor", proxy)
        self.assertNotIn("mode http", proxy)
        haproxy = shutil.which("haproxy")
        if haproxy:
            with tempfile.TemporaryDirectory() as directory:
                config = Path(directory) / "haproxy.cfg"
                config.write_text(proxy, encoding="utf-8")
                subprocess.run([haproxy, "-c", "-f", str(config)], check=True, stdout=subprocess.DEVNULL)

    def test_rejects_unknown_fields_mutable_images_and_changed_fixed_ports(self):
        mutations = []
        unknown = final_release()
        unknown["services"][0]["unknown"] = True
        mutations.append(unknown)
        mutable = final_release()
        mutable["services"][0]["factory_image"] = "registry.invalid/finals/sign-me-in:latest"
        mutations.append(mutable)
        moved = final_release()
        moved["services"][0]["backends"]["gate_port"] = 29999
        mutations.append(moved)
        shared = final_release()
        shared["services"][0]["generations"]["gate"] = copy.deepcopy(shared["services"][0]["generations"]["live"])
        mutations.append(shared)
        weakened = final_release()
        weakened["services"][0]["runtime"]["outbound_network"] = True
        mutations.append(weakened)
        for release in mutations:
            with self.assertRaises(MODULE.ReleaseError):
                MODULE.validate_release(release)

    def test_writes_private_outputs_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "compiled"
            MODULE.write_outputs(output, MODULE.compile_documents(final_release(), team()))
            self.assertEqual({path.name for path in output.iterdir()}, {"services.json", "executor-policy.json", "volume-policy.json", "haproxy.cfg"})
            self.assertEqual(stat_mode(output), 0o700)
            for path in output.iterdir():
                self.assertEqual(stat_mode(path), 0o600)
            with self.assertRaisesRegex(MODULE.ReleaseError, "empty"):
                MODULE.write_outputs(output, MODULE.compile_documents(final_release(), team()))

    def test_rejects_duplicate_json_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.json"
            path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
            with self.assertRaisesRegex(MODULE.ReleaseError, "duplicate"):
                MODULE.read_document(path, "test")


def stat_mode(path):
    return os.stat(path).st_mode & 0o777


if __name__ == "__main__":
    unittest.main()
