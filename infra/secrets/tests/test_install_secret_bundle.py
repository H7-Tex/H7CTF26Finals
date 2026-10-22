import base64
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "install-secret-bundle.py"
SPEC = importlib.util.spec_from_file_location("install_secret_bundle", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def document(bundle_type, values):
    return json.dumps({
        "type": bundle_type,
        "files": {name: base64.b64encode(value).decode() for name, value in values.items()},
    }).encode()


class SecretBundleTests(unittest.TestCase):
    def test_wireguard_bundle_installs_only_fixed_private_path(self):
        key = b"A" * 43 + b"=\n"
        files = MODULE.decode_bundle(document("gateway-wireguard", {"private_key": key}), "gateway-wireguard")
        with tempfile.TemporaryDirectory() as directory:
            MODULE.install_bundle(
                "gateway-wireguard",
                files,
                Path(directory),
                ownership=lambda _: (os.getuid(), os.getgid()),
            )
            target = Path(directory) / "etc/wireguard/private.key"
            self.assertEqual(target.read_bytes(), key)
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertEqual([path for path in Path(directory).rglob("*") if path.is_file()], [target])

    def test_type_confusion_and_extra_paths_are_rejected(self):
        payload = json.loads(document("gateway-wireguard", {"private_key": b"A" * 43 + b"="}))
        payload["files"]["destination"] = base64.b64encode(b"/tmp/escape").decode()
        with self.assertRaises(MODULE.BundleError):
            MODULE.decode_bundle(json.dumps(payload).encode(), "gateway-wireguard")
        with self.assertRaises(MODULE.BundleError):
            MODULE.decode_bundle(document("gateway-wireguard", {"private_key": b"A" * 43 + b"="}), "anvil")

    def test_gateway_reconciler_has_one_fixed_root_only_path(self):
        original = MODULE.validate_ssh_public_key
        MODULE.validate_ssh_public_key = lambda _: None
        try:
            files = MODULE.decode_bundle(document("gateway-reconciler", {"authorized_key": b"ssh-ed25519 AAAA test\n"}), "gateway-reconciler")
        finally:
            MODULE.validate_ssh_public_key = original
        with tempfile.TemporaryDirectory() as directory:
            MODULE.install_bundle("gateway-reconciler", files, Path(directory), ownership=lambda _: (os.getuid(), os.getgid()))
            target = Path(directory) / "etc/event-router/reconciler_authorized_key"
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_environment_parser_rejects_shell_syntax_and_unknown_names(self):
        with self.assertRaises(MODULE.BundleError):
            MODULE.parse_environment(b"GITEA_SECRET_KEY=$(id)\nGITEA_INTERNAL_TOKEN=a\n", MODULE.REPOSITORY_ENV)
        with self.assertRaises(MODULE.BundleError):
            MODULE.parse_environment(b"GITEA_SECRET_KEY=a\nUNKNOWN=b\n", MODULE.REPOSITORY_ENV)
        values = MODULE.parse_environment(b"GITEA_SECRET_KEY=abc=\nGITEA_INTERNAL_TOKEN=def=\n", MODULE.REPOSITORY_ENV)
        self.assertEqual(values["GITEA_SECRET_KEY"], "abc=")

    def test_control_token_must_be_non_whitespace_and_long(self):
        values = {
            "token": b"short",
            "ssh_private_key": b"not-a-key",
            "known_hosts": b"not-hosts",
        }
        with self.assertRaisesRegex(MODULE.BundleError, "token"):
            MODULE.decode_bundle(document("control-reconciler", values), "control-reconciler")

    def test_checker_commissioning_token_has_one_fixed_root_only_path(self):
        token = b"headersegment.payloadsegment.signaturesegment\n"
        files = MODULE.decode_bundle(document("control-checkers", {"admin_token": token}), "control-checkers")
        with tempfile.TemporaryDirectory() as directory:
            MODULE.install_bundle(
                "control-checkers",
                files,
                Path(directory),
                ownership=lambda _: (os.getuid(), os.getgid()),
            )
            target = Path(directory) / "etc/checker-runtime/anvil-admin.token"
            self.assertEqual(target.read_bytes(), token)
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertEqual([path for path in Path(directory).rglob("*") if path.is_file()], [target])
        with self.assertRaisesRegex(MODULE.BundleError, "commissioning token"):
            MODULE.decode_bundle(document("control-checkers", {"admin_token": b"not-a-jwt"}), "control-checkers")

    def test_operations_relay_has_only_fixed_root_paths(self):
        original_private = MODULE.validate_ssh_private_key
        original_hosts = MODULE.validate_known_hosts
        MODULE.validate_ssh_private_key = lambda _: None
        MODULE.validate_known_hosts = lambda content, expected: None
        try:
            files = MODULE.decode_bundle(document("operations-relay", {
                "ssh_private_key": b"dedicated-event-key",
                "known_hosts": b"verified-hosts",
            }), "operations-relay")
        finally:
            MODULE.validate_ssh_private_key = original_private
            MODULE.validate_known_hosts = original_hosts
        with tempfile.TemporaryDirectory() as directory:
            MODULE.install_bundle("operations-relay", files, Path(directory), ownership=lambda _: (os.getuid(), os.getgid()))
            installed = sorted(str(path.relative_to(directory)) for path in Path(directory).rglob("*") if path.is_file())
            self.assertEqual(installed, [
                "etc/finals-platform/operations/id_ed25519",
                "etc/finals-platform/operations/known_hosts",
            ])

    def test_operations_known_hosts_requires_exact_five_targets(self):
        self.assertEqual(MODULE.OPERATIONS_TARGETS, {
            "10.60.250.10",
            "10.60.250.11",
            "10.60.200.10",
            "10.60.201.20",
            "[10.60.201.30]:2222",
        })
        partial = b"10.60.250.10 ssh-ed25519 AAAA\n10.60.250.11 ssh-ed25519 AAAA\n"
        with self.assertRaisesRegex(MODULE.BundleError, "exact fixed host set"):
            MODULE.validate_known_hosts(partial, MODULE.OPERATIONS_TARGETS)

    def test_anvil_accepts_a_padded_wireguard_public_key(self):
        values = {
            "ANVIL_PRIVATE_ADDRESS": "10.60.200.10",
            "PUBLIC_API_URL": "https://finals.h7tex.com",
            "ANVIL_DATABASE_PASSWORD": "1" * 32,
            "ANVIL_JWT_SECRET": "2" * 32,
            "ANVIL_SECRETS_ENCRYPTION_KEY": "3" * 32,
            "ANVIL_GAME_INTERNAL_TOKEN": "4" * 32,
            "ANVIL_IMAGE_REVISION": "7e202e9594e2ccbdf4ef592529765f17ca60ccec",
            "ANVIL_VPN_ENABLED": "false",
            "ANVIL_VPN_PEER_CONTROL": "external",
            "ANVIL_VPN_PUBLIC_ENDPOINT": "vpn.h7tex.com:443",
            "ANVIL_VPN_PUBLIC_KEY": "A" * 43 + "=",
            "ANVIL_VPN_ALLOWED_IPS": "10.60.0.0/15",
            "ANVIL_TLS_CERT_PATH": "/etc/anvil/tls/fullchain.pem",
            "ANVIL_TLS_KEY_PATH": "/etc/anvil/tls/privkey.pem",
            "ANVIL_DATABASE_HOST_PATH": "/srv/anvil/postgres",
            "ANVIL_STORAGE_HOST_PATH": "/srv/anvil/storage",
            "ANVIL_BACKUP_DIR": "/srv/anvil/backups",
        }
        environment = "\n".join(f"{name}={value}" for name, value in values.items()).encode()
        original = MODULE.validate_tls
        MODULE.validate_tls = lambda certificate, private_key, hostname: None
        try:
            MODULE.validate_bundle("anvil", {
                "environment": environment,
                "certificate": b"certificate",
                "private_key": b"private-key",
            })
        finally:
            MODULE.validate_tls = original

    def test_anvil_environment_revision_is_bound_to_image_manifest(self):
        values = {name: "value" for name in MODULE.ANVIL_ENV}
        values["ANVIL_IMAGE_REVISION"] = "a" * 40
        environment = "\n".join(f"{name}={value}" for name, value in values.items()).encode()
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "manifest.json"
            manifest.write_text(json.dumps({"anvil_revision": "b" * 40}), encoding="utf-8")
            with self.assertRaisesRegex(MODULE.BundleError, "does not match"):
                MODULE.validate_anvil_image_binding({"environment": environment}, manifest)

    def test_self_signed_tls_bundle_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            certificate = Path(directory) / "certificate.pem"
            private_key = Path(directory) / "private-key.pem"
            subprocess.run([
                "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "30",
                "-subj", "/CN=finals.h7tex.com",
                "-addext", "subjectAltName=DNS:finals.h7tex.com",
                "-keyout", str(private_key), "-out", str(certificate),
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            with self.assertRaisesRegex(MODULE.BundleError, "validation failed"):
                MODULE.validate_tls(certificate.read_bytes(), private_key.read_bytes(), "finals.h7tex.com")


if __name__ == "__main__":
    unittest.main()
