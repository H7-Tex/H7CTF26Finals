import hashlib
import importlib.util
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar
from unittest import mock

MODULE_PATH = (
    Path(__file__).parents[1] / "rootfs/usr/local/libexec/checker-runtime/runtime.py"
)
SPEC = importlib.util.spec_from_file_location("checker_runtime", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def image_id(index):
    return "sha256:" + f"{index:064x}"


def fixture(directory):
    root = Path(directory)
    artifacts = root / "artifacts"
    services = []
    for index, expected in enumerate(MODULE.EXPECTED, 1):
        content = f"fake checker image {expected['slug']}".encode()
        target = artifacts / expected["slug"] / "checker-image.tar"
        target.parent.mkdir(parents=True)
        target.write_bytes(content)
        target.chmod(0o600)
        services.append(
            {
                **expected,
                "artifact": {
                    "path": f"{expected['slug']}/checker-image.tar",
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "size": len(content),
                    "executable": False,
                    "image": f"finals/checkers/{expected['slug']}:r{index:02d}",
                    "image_id": image_id(index),
                },
            }
        )
    document = {
        "version": 2,
        "database_image": MODULE.DATABASE_IMAGE,
        "services": services,
    }
    manifest = root / "manifest.json"
    manifest.write_text(json.dumps(document), encoding="utf-8")
    manifest.chmod(0o600)
    return manifest, artifacts, document


class FakeEngine:
    def __init__(self, document):
        self.document = document
        self.images = {MODULE.DATABASE_IMAGE: image_id(99)}
        self.containers = {}
        self.networks = {}
        self.loads = []

    def image_id(self, reference):
        return self.images.get(reference)

    def load_image(self, archive):
        slug = archive.parent.name
        service = next(
            item for item in self.document["services"] if item["slug"] == slug
        )
        self.images[service["artifact"]["image"]] = service["artifact"]["image_id"]
        self.loads.append(slug)

    def ensure_network(self, name, subnet, internal, disable_icc=False):
        wanted = {
            "subnet": subnet,
            "internal": internal,
            "disable_icc": disable_icc,
        }
        current = self.networks.get(name)
        if current is not None and current != wanted:
            raise MODULE.RuntimeErrorSafe("fake network drift")
        self.networks[name] = wanted

    def container(self, name):
        return self.containers.get(name)

    def remove_container(self, name):
        self.containers.pop(name, None)

    def create_container(self, arguments):
        name = arguments[arguments.index("--name") + 1]
        labels = {}
        for index, value in enumerate(arguments):
            if value == "--label":
                key, label = arguments[index + 1].split("=", 1)
                labels[key] = label
        image = (
            self.images[MODULE.DATABASE_IMAGE]
            if name.startswith("checker-db-")
            else self.images[arguments[-1]]
        )
        self.containers[name] = {
            "Config": {"Labels": labels},
            "Image": image,
            "State": {"Running": False, "Health": {"Status": "starting"}},
            "Networks": {arguments[arguments.index("--network") + 1]},
        }

    def ensure_connected(self, network, name):
        self.containers[name]["Networks"].add(network)

    def container_networks(self, name):
        return set(self.containers[name]["Networks"])

    def start_container(self, name):
        state = self.containers[name]["State"]
        state["Running"] = True
        if name.startswith("checker-db-"):
            state["Health"]["Status"] = "healthy"

    def stop_container(self, name):
        self.containers.pop(name, None)


class FakeChecker(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/openapi.json":
            self.send_response(404)
            self.end_headers()
            return
        body = b'{"openapi":"3.0.0"}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args):
        return


class FakeAnvil(BaseHTTPRequestHandler):
    services: ClassVar[list] = []
    payloads: ClassVar[list] = []
    posts = 0
    token = "headersegment.payloadsegment.signaturesegment"

    def _write(self, status, document):
        body = json.dumps(document).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.headers.get("Authorization") != f"Bearer {self.token}":
            self._write(404, {"error": "not found"})
            return
        if self.path == "/api/v1/info":
            self._write(200, {"game_state": "stopped"})
        else:
            self._write(200, {"services": self.services})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        self.__class__.posts += 1
        self.payloads.append(payload)
        item = {
            key: payload[key]
            for key in ("name", "slug", "category", "tier", "port", "checker_ref")
        }
        item.update({"id": f"service-{self.posts}", "enabled": True})
        self.services.append(item)
        self._write(201, {"id": item["id"]})

    def log_message(self, _format, *_args):
        return


class RuntimeTests(unittest.TestCase):
    def test_manifest_requires_exact_six_and_verified_private_archives(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, artifacts, document = fixture(directory)
            MODULE.load_manifest(manifest, artifacts)
            document["services"].pop()
            with self.assertRaisesRegex(MODULE.RuntimeErrorSafe, "exactly six"):
                MODULE.validate_manifest(document, artifacts)

    def test_manifest_rejects_digest_change_and_parent_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, artifacts, document = fixture(directory)
            target = artifacts / "sign-me-in/checker-image.tar"
            target.write_bytes(b"changed")
            target.chmod(0o600)
            with self.assertRaisesRegex(
                MODULE.RuntimeErrorSafe, "size changed|digest changed"
            ):
                MODULE.load_manifest(manifest, artifacts)

            external = Path(directory) / "external"
            external.mkdir()
            (external / "checker-image.tar").write_bytes(b"x")
            (external / "checker-image.tar").chmod(0o600)
            target.unlink()
            target.parent.rmdir()
            target.parent.symlink_to(external, target_is_directory=True)
            service = document["services"][0]
            service["artifact"]["size"] = 1
            service["artifact"]["sha256"] = hashlib.sha256(b"x").hexdigest()
            manifest.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(
                MODULE.RuntimeErrorSafe, "symbolic link|escapes"
            ):
                MODULE.load_manifest(manifest, artifacts)

    def test_root_runtime_rejects_linked_or_exposed_manifest_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, artifacts, _ = fixture(directory)
            manifest.chmod(0o644)
            with self.assertRaisesRegex(
                MODULE.RuntimeErrorSafe, "manifest ownership or mode"
            ):
                MODULE.load_manifest(manifest, artifacts, require_root=True)
            manifest.chmod(0o600)
            artifacts.chmod(0o700)
            linked = Path(directory) / "linked-artifacts"
            linked.symlink_to(artifacts, target_is_directory=True)
            real_lstat = Path.lstat

            def root_owned(path):
                metadata = real_lstat(path)
                return SimpleNamespace(st_mode=metadata.st_mode, st_uid=0)

            with (
                mock.patch.object(Path, "lstat", root_owned),
                self.assertRaisesRegex(
                    MODULE.RuntimeErrorSafe, "root ownership or mode"
                ),
            ):
                MODULE.load_manifest(manifest, linked, require_root=True)

    def test_import_is_idempotent_and_rejects_wrong_loaded_image(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, artifacts, document = fixture(directory)
            engine = FakeEngine(document)
            runtime = MODULE.Runtime(
                engine, manifest, artifacts, Path(directory) / "state.json"
            )
            runtime.import_artifacts()
            runtime.import_artifacts()
            self.assertEqual(
                engine.loads, [item["slug"] for item in document["services"]]
            )
            engine.images[document["services"][0]["artifact"]["image"]] = image_id(500)
            with self.assertRaisesRegex(MODULE.RuntimeErrorSafe, "does not match"):
                runtime.import_artifacts()

    def test_fast_runtime_checks_close_readiness_after_artifact_change(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, artifacts, document = fixture(directory)
            engine = FakeEngine(document)
            runtime = MODULE.Runtime(
                engine, manifest, artifacts, Path(directory) / "state.json"
            )
            runtime.import_artifacts()
            target = artifacts / "sign-me-in/checker-image.tar"
            target.write_bytes(b"changed artifact")
            target.chmod(0o600)
            status = runtime.status(False)
            self.assertFalse(status["ready"])
            self.assertIn("changed after integrity verification", status["reason"])

    def test_container_contract_has_private_publish_and_no_database_listener(self):
        with tempfile.TemporaryDirectory() as directory:
            _, _, document = fixture(directory)
            service = document["services"][0]
            _, _, checker = MODULE.checker_arguments(service)
            _, _, database = MODULE.database_arguments(service)
            self.assertIn("10.60.201.20:9001:8000/tcp", checker)
            self.assertNotIn("0.0.0.0:9001:8000/tcp", checker)
            self.assertNotIn("--publish", database)
            self.assertIn("--read-only", checker)
            self.assertIn("no-new-privileges:true", checker)
            self.assertIn("/tmp:rw,noexec,nosuid,nodev,size=32m,mode=1777", database)
            self.assertEqual(checker[checker.index("--log-driver") + 1], "none")
            self.assertEqual(database[database.index("--log-driver") + 1], "none")

    def test_egress_network_requires_icc_disabled(self):
        engine = MODULE.DockerEngine()
        network = {
            "Labels": {MODULE.MANAGED_LABEL: "true"},
            "Internal": False,
            "IPAM": {"Config": [{"Subnet": MODULE.EGRESS_SUBNET}]},
            "Options": {"com.docker.network.bridge.enable_icc": "false"},
        }
        with mock.patch.object(engine, "network", return_value=network):
            engine.ensure_network(
                MODULE.EGRESS_NETWORK,
                MODULE.EGRESS_SUBNET,
                False,
                disable_icc=True,
            )
        network["Options"] = {}
        with (
            mock.patch.object(engine, "network", return_value=network),
            self.assertRaisesRegex(MODULE.RuntimeErrorSafe, "fixed contract"),
        ):
            engine.ensure_network(
                MODULE.EGRESS_NETWORK,
                MODULE.EGRESS_SUBNET,
                False,
                disable_icc=True,
            )
        with (
            mock.patch.object(engine, "network", return_value=None),
            mock.patch.object(engine, "_run") as run,
        ):
            engine.ensure_network(
                MODULE.EGRESS_NETWORK,
                MODULE.EGRESS_SUBNET,
                False,
                disable_icc=True,
            )
            self.assertIn(
                "com.docker.network.bridge.enable_icc=false",
                run.call_args.args[0],
            )

    def test_restart_recreates_six_checkers_with_persistent_state_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, artifacts, document = fixture(directory)
            engine = FakeEngine(document)
            state = Path(directory) / "state.json"
            original_root = MODULE.STATE_ROOT
            MODULE.STATE_ROOT = Path(directory) / "runtime"
            try:
                runtime = MODULE.Runtime(
                    engine,
                    manifest,
                    artifacts,
                    state,
                    "127.0.0.1",
                    probe=lambda *_: True,
                )
                runtime.import_artifacts()
                runtime.reconcile()
                self.assertEqual(len(engine.containers), 12)
                self.assertEqual(len(engine.networks), 7)
                self.assertEqual(
                    engine.networks[MODULE.EGRESS_NETWORK],
                    {
                        "subnet": MODULE.EGRESS_SUBNET,
                        "internal": False,
                        "disable_icc": True,
                    },
                )
                for service in document["services"]:
                    state_network, _ = MODULE.state_network(service)
                    self.assertEqual(
                        engine.containers[f"checker-db-{service['slug']}"]["Networks"],
                        {state_network},
                    )
                    self.assertEqual(
                        engine.containers[f"checker-{service['slug']}"]["Networks"],
                        {state_network, MODULE.EGRESS_NETWORK},
                    )
                checker = engine.containers["checker-sign-me-in"]
                checker["Networks"].remove(MODULE.EGRESS_NETWORK)
                runtime.reconcile()
                self.assertIn(MODULE.EGRESS_NETWORK, checker["Networks"])
                checker["Networks"].add("unexpected")
                with self.assertRaisesRegex(
                    MODULE.RuntimeErrorSafe, "network attachments drifted"
                ):
                    runtime.reconcile()
                checker["Networks"].remove("unexpected")
                engine.containers.clear()
                restarted = MODULE.Runtime(
                    engine,
                    manifest,
                    artifacts,
                    state,
                    "127.0.0.1",
                    probe=lambda *_: True,
                )
                restarted.reconcile()
                self.assertEqual(len(engine.containers), 12)
                for service in document["services"]:
                    self.assertTrue(
                        (
                            MODULE.STATE_ROOT / "data" / service["slug"] / "mongo"
                        ).is_dir()
                    )
            finally:
                MODULE.STATE_ROOT = original_root

    def test_stop_refuses_unmanaged_exact_name_before_commissioning_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, artifacts, document = fixture(directory)
            engine = FakeEngine(document)
            original_root = MODULE.STATE_ROOT
            MODULE.STATE_ROOT = Path(directory) / "runtime"
            try:
                runtime = MODULE.Runtime(
                    engine,
                    manifest,
                    artifacts,
                    Path(directory) / "state.json",
                    "127.0.0.1",
                    probe=lambda *_: True,
                )
                runtime.import_artifacts()
                runtime.reconcile()
                name = "checker-sign-me-in"
                engine.containers[name]["Config"]["Labels"][MODULE.MANAGED_LABEL] = (
                    "false"
                )
                with self.assertRaisesRegex(
                    MODULE.RuntimeErrorSafe, "refusing to remove unmanaged"
                ):
                    runtime.stop()
                self.assertEqual(len(engine.containers), 12)
                engine.containers[name]["Config"]["Labels"][MODULE.MANAGED_LABEL] = (
                    "true"
                )
                runtime.stop()
                self.assertEqual(engine.containers, {})
            finally:
                MODULE.STATE_ROOT = original_root

        engine = MODULE.DockerEngine()
        unmanaged = {"Config": {"Labels": {}}}
        with (
            mock.patch.object(engine, "container", return_value=unmanaged),
            mock.patch.object(engine, "_run") as run,
            self.assertRaisesRegex(
                MODULE.RuntimeErrorSafe, "refusing to remove unmanaged"
            ),
        ):
            engine.stop_container("checker-sign-me-in")
        run.assert_not_called()

    def test_registration_inventory_is_exact_unique_and_enabled(self):
        services = []
        for service in MODULE.EXPECTED:
            item = MODULE._visible_registration(MODULE.registration_payload(service))
            item["enabled"] = True
            services.append(item)
        self.assertEqual(
            len(
                MODULE._registration_inventory(
                    {"services": services}, require_complete=True
                )
            ),
            6,
        )
        with self.assertRaisesRegex(MODULE.RuntimeErrorSafe, "exactly six"):
            MODULE._registration_inventory(
                {"services": services[:-1]}, require_complete=True
            )
        with self.assertRaisesRegex(MODULE.RuntimeErrorSafe, "duplicated"):
            MODULE._registration_inventory({"services": services + [services[0]]})
        with self.assertRaisesRegex(MODULE.RuntimeErrorSafe, "unexpected"):
            MODULE._registration_inventory(
                {"services": services + [{"slug": "unexpected", "enabled": True}]}
            )
        disabled = [dict(item) for item in services]
        disabled[0]["enabled"] = False
        with self.assertRaisesRegex(MODULE.RuntimeErrorSafe, "not enabled"):
            MODULE._registration_inventory({"services": disabled})

    def test_real_health_probes_and_registration_are_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, artifacts, document = fixture(directory)
            engine = FakeEngine(document)
            state = Path(directory) / "state.json"
            token = Path(directory) / "token"
            token.write_text(FakeAnvil.token, encoding="ascii")
            token.chmod(0o600)
            checker_servers = []
            checker_threads = []
            for service in document["services"]:
                server = ThreadingHTTPServer(
                    ("127.0.0.1", service["checker_port"]), FakeChecker
                )
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                checker_servers.append(server)
                checker_threads.append(thread)
            FakeAnvil.services = []
            FakeAnvil.payloads = []
            FakeAnvil.posts = 0
            anvil = ThreadingHTTPServer(("127.0.0.1", 0), FakeAnvil)
            anvil_thread = threading.Thread(target=anvil.serve_forever, daemon=True)
            anvil_thread.start()
            original_root = MODULE.STATE_ROOT
            MODULE.STATE_ROOT = Path(directory) / "runtime"
            try:
                runtime = MODULE.Runtime(
                    engine, manifest, artifacts, state, "127.0.0.1"
                )
                runtime.import_artifacts()
                runtime.reconcile()
                self.assertTrue(runtime.status()["ready"])
                client = MODULE.AnvilClient(
                    f"http://127.0.0.1:{anvil.server_port}", token
                )
                MODULE.register_services(runtime, client)
                MODULE.register_services(runtime, client)
                self.assertEqual(FakeAnvil.posts, 6)
                self.assertEqual(len(FakeAnvil.services), 6)
                self.assertEqual(
                    [
                        (
                            item["slug"],
                            item["flag_stores"],
                            item["noise_variants"],
                            item["havoc_variants"],
                        )
                        for item in FakeAnvil.payloads
                    ],
                    [
                        (
                            item["slug"],
                            2,
                            item["noise_variants"],
                            item["havoc_variants"],
                        )
                        for item in document["services"]
                    ],
                )

                state_document = MODULE.load_state(state)
                first = document["services"][0]
                first_payload = MODULE.registration_payload(first)
                state_document["registrations"] = {
                    first["slug"]: {
                        "fingerprint": MODULE.canonical_digest(first_payload),
                        "status": "pending",
                    }
                }
                MODULE.atomic_json(state, state_document)
                FakeAnvil.services = FakeAnvil.services[:1]
                FakeAnvil.payloads = []
                FakeAnvil.posts = 0
                MODULE.register_services(runtime, client)
                self.assertEqual(FakeAnvil.posts, 5)
                self.assertEqual(len(FakeAnvil.services), 6)
                recovered = MODULE.load_state(state)["registrations"]
                self.assertEqual(recovered[first["slug"]]["status"], "registered")

                unexpected = {
                    "slug": "unexpected",
                    "enabled": True,
                }
                FakeAnvil.services.append(unexpected)
                FakeAnvil.posts = 0
                with self.assertRaisesRegex(MODULE.RuntimeErrorSafe, "unexpected"):
                    MODULE.register_services(runtime, client)
                self.assertEqual(FakeAnvil.posts, 0)
                FakeAnvil.services.pop()

                FakeAnvil.services.append(dict(FakeAnvil.services[0]))
                with self.assertRaisesRegex(MODULE.RuntimeErrorSafe, "duplicated"):
                    MODULE.register_services(runtime, client)
                FakeAnvil.services.pop()

                FakeAnvil.services[0]["enabled"] = False
                with self.assertRaisesRegex(MODULE.RuntimeErrorSafe, "not enabled"):
                    MODULE.register_services(runtime, client)
                FakeAnvil.services[0]["enabled"] = True

                FakeAnvil.services = []
                FakeAnvil.payloads = []
                FakeAnvil.posts = 0
                original_get = FakeAnvil.do_GET

                def paused(handler):
                    if handler.path == "/api/v1/info":
                        handler._write(200, {"game_state": "paused"})
                    else:
                        original_get(handler)

                FakeAnvil.do_GET = paused
                try:
                    with self.assertRaisesRegex(
                        MODULE.RuntimeErrorSafe, "explicitly stopped"
                    ):
                        MODULE.register_services(runtime, client)
                    self.assertEqual(FakeAnvil.posts, 0)
                finally:
                    FakeAnvil.do_GET = original_get
            finally:
                MODULE.STATE_ROOT = original_root
                anvil.shutdown()
                anvil_thread.join(timeout=2)
                anvil.server_close()
                for server in checker_servers:
                    server.shutdown()
                for thread in checker_threads:
                    thread.join(timeout=2)
                for server in checker_servers:
                    server.server_close()

    def test_registration_error_does_not_disclose_response_or_token(self):
        class RejectingAnvil(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b"private-response-body")

            def log_message(self, _format, *_args):
                return

        with tempfile.TemporaryDirectory() as directory:
            token = Path(directory) / "token"
            token.write_text(
                "headersegment.payloadsegment.signaturesegment", encoding="ascii"
            )
            token.chmod(0o600)
            server = ThreadingHTTPServer(("127.0.0.1", 0), RejectingAnvil)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                client = MODULE.AnvilClient(
                    f"http://127.0.0.1:{server.server_port}", token
                )
                with self.assertRaises(MODULE.RuntimeErrorSafe) as caught:
                    client.request("GET", "/api/v1/admin/arena/services")
                self.assertNotIn("private-response-body", str(caught.exception))
                self.assertNotIn("header", str(caught.exception))
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

    def test_registration_does_not_follow_token_bearing_redirects(self):
        class RedirectingAnvil(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302)
                self.send_header("Location", "http://127.0.0.1:1/token-leak")
                self.end_headers()

            def log_message(self, _format, *_args):
                return

        with tempfile.TemporaryDirectory() as directory:
            token = Path(directory) / "token"
            token.write_text(
                "headersegment.payloadsegment.signaturesegment", encoding="ascii"
            )
            token.chmod(0o600)
            server = ThreadingHTTPServer(("127.0.0.1", 0), RedirectingAnvil)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                client = MODULE.AnvilClient(
                    f"http://127.0.0.1:{server.server_port}", token
                )
                with self.assertRaisesRegex(MODULE.RuntimeErrorSafe, "HTTP 302"):
                    client.request("GET", "/api/v1/admin/arena/services")
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()


if __name__ == "__main__":
    unittest.main()
