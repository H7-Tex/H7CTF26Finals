#!/usr/bin/env python3
import base64
import binascii
import json
import os
import pwd
import re
import subprocess
import sys
import tempfile
from pathlib import Path


MAX_CIPHERTEXT = 2 * 1024 * 1024
ENV_LINE = re.compile(r"^[A-Z][A-Z0-9_]*=[A-Za-z0-9_./:@+,=-]+$")
WIREGUARD_KEY = re.compile(rb"^[A-Za-z0-9+/]{43}=$")
JWT = re.compile(rb"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")

ANVIL_ENV = {
    "ANVIL_PRIVATE_ADDRESS",
    "PUBLIC_API_URL",
    "ANVIL_DATABASE_PASSWORD",
    "ANVIL_JWT_SECRET",
    "ANVIL_SECRETS_ENCRYPTION_KEY",
    "ANVIL_GAME_INTERNAL_TOKEN",
    "ANVIL_IMAGE_REVISION",
    "ANVIL_VPN_ENABLED",
    "ANVIL_VPN_PEER_CONTROL",
    "ANVIL_VPN_PUBLIC_ENDPOINT",
    "ANVIL_VPN_PUBLIC_KEY",
    "ANVIL_VPN_ALLOWED_IPS",
    "ANVIL_TLS_CERT_PATH",
    "ANVIL_TLS_KEY_PATH",
    "ANVIL_DATABASE_HOST_PATH",
    "ANVIL_STORAGE_HOST_PATH",
    "ANVIL_BACKUP_DIR",
}
REPOSITORY_ENV = {"GITEA_SECRET_KEY", "GITEA_INTERNAL_TOKEN"}
GATEWAY_HOSTS = {"10.60.250.10", "10.60.250.11"}
OPERATIONS_TARGETS = GATEWAY_HOSTS | {
    "10.60.200.10",
    "10.60.201.20",
    "[10.60.201.30]:2222",
}

BUNDLES = {
    "gateway-wireguard": {
        "private_key": ("etc/wireguard/private.key", 0o600, "root"),
    },
    "gateway-reconciler": {
        "authorized_key": ("etc/event-router/reconciler_authorized_key", 0o600, "root"),
    },
    "anvil": {
        "environment": ("etc/anvil/finals.env", 0o600, "root"),
        "certificate": ("etc/anvil/tls/fullchain.pem", 0o644, "root"),
        "private_key": ("etc/anvil/tls/privkey.pem", 0o600, "root"),
    },
    "control-reconciler": {
        "token": ("etc/peer-reconciler/anvil.token", 0o600, "peer-reconciler"),
        "ssh_private_key": ("etc/peer-reconciler/id_ed25519", 0o600, "peer-reconciler"),
        "known_hosts": ("etc/peer-reconciler/known_hosts", 0o600, "peer-reconciler"),
    },
    "control-checkers": {
        "admin_token": ("etc/checker-runtime/anvil-admin.token", 0o600, "root"),
    },
    "repository": {
        "environment": ("etc/finals-platform/repository/repository.env", 0o600, "root"),
        "certificate": ("etc/finals-platform/repository/tls/fullchain.pem", 0o644, "root"),
        "private_key": ("etc/finals-platform/repository/tls/privkey.pem", 0o600, "root"),
    },
    "operations-relay": {
        "ssh_private_key": ("etc/finals-platform/operations/id_ed25519", 0o600, "root"),
        "known_hosts": ("etc/finals-platform/operations/known_hosts", 0o600, "root"),
    },
}


class BundleError(Exception):
    pass


def decode_bundle(data, expected_type):
    try:
        document = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BundleError("decrypted bundle is not valid JSON") from error
    if not isinstance(document, dict) or set(document) != {"type", "files"}:
        raise BundleError("bundle must contain only type and files")
    if document["type"] != expected_type or expected_type not in BUNDLES:
        raise BundleError("bundle type does not match the requested fixed type")
    files = document["files"]
    if not isinstance(files, dict) or set(files) != set(BUNDLES[expected_type]):
        raise BundleError("bundle file set does not match the fixed type")
    decoded = {}
    for name, value in files.items():
        if not isinstance(value, str):
            raise BundleError(f"{name} must be base64 text")
        try:
            content = base64.b64decode(value, validate=True)
        except (ValueError, binascii.Error) as error:
            raise BundleError(f"{name} is not valid base64") from error
        if not content or len(content) > 1024 * 1024 or b"\x00" in content:
            raise BundleError(f"{name} has an invalid size or content")
        decoded[name] = content
    validate_bundle(expected_type, decoded)
    return decoded


def parse_environment(content, expected_names):
    try:
        lines = content.decode("ascii").splitlines()
    except UnicodeDecodeError as error:
        raise BundleError("environment must be ASCII") from error
    if not lines or any(not ENV_LINE.fullmatch(line) for line in lines):
        raise BundleError("environment contains an unsafe or malformed line")
    names = [line.split("=", 1)[0] for line in lines]
    if len(names) != len(set(names)) or set(names) != expected_names:
        raise BundleError("environment variable set is not exact")
    return dict(line.split("=", 1) for line in lines)


def validate_tls(certificate, private_key, hostname):
    with tempfile.TemporaryDirectory(prefix="finals-secret-") as directory:
        cert_path = Path(directory) / "certificate.pem"
        key_path = Path(directory) / "private-key.pem"
        cert_path.write_bytes(certificate)
        key_path.write_bytes(private_key)
        commands = (
            ["openssl", "x509", "-in", str(cert_path), "-noout", "-checkend", "604800"],
            ["openssl", "x509", "-in", str(cert_path), "-noout", "-checkhost", hostname],
            [
                "openssl", "verify",
                "-CAfile", "/etc/ssl/certs/ca-certificates.crt",
                "-untrusted", str(cert_path),
                str(cert_path),
            ],
            ["openssl", "pkey", "-in", str(key_path), "-pubout", "-out", f"{directory}/key.pub"],
            ["openssl", "x509", "-in", str(cert_path), "-pubkey", "-noout", "-out", f"{directory}/cert.pub"],
        )
        for command in commands:
            try:
                subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except (OSError, subprocess.SubprocessError) as error:
                raise BundleError("TLS certificate or private key validation failed") from error
        if (Path(directory) / "key.pub").read_bytes() != (Path(directory) / "cert.pub").read_bytes():
            raise BundleError("TLS certificate and private key do not match")


def validate_ssh_private_key(content):
    if not content.startswith(b"-----BEGIN OPENSSH PRIVATE KEY-----\n"):
        raise BundleError("control SSH identity is not an OpenSSH private key")
    with tempfile.NamedTemporaryFile(prefix="finals-ssh-", mode="wb") as handle:
        handle.write(content)
        handle.flush()
        os.fchmod(handle.fileno(), 0o600)
        try:
            subprocess.run(
                ["ssh-keygen", "-y", "-f", handle.name],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise BundleError("control SSH identity is invalid or encrypted") from error


def validate_ssh_public_key(content):
    if content.count(b"\n") > 1 or not content.startswith(b"ssh-ed25519 "):
        raise BundleError("gateway reconciler key is not one Ed25519 public key")
    with tempfile.NamedTemporaryFile(prefix="finals-public-", mode="wb") as handle:
        handle.write(content)
        handle.flush()
        try:
            result = subprocess.run(
                ["ssh-keygen", "-l", "-E", "sha256", "-f", handle.name],
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise BundleError("gateway reconciler key is invalid") from error
    if " (ED25519)" not in result.stdout:
        raise BundleError("gateway reconciler key must be Ed25519")


def validate_known_hosts(content, expected_hosts):
    try:
        lines = content.decode("ascii").splitlines()
    except UnicodeDecodeError as error:
        raise BundleError("known_hosts must be ASCII") from error
    hosts = []
    for line in lines:
        fields = line.split()
        if len(fields) not in {2, 3} or fields[1] != "ssh-ed25519" or "," in fields[0] or fields[0].startswith("|"):
            raise BundleError("known_hosts must contain plain, single-host Ed25519 entries")
        hosts.append(fields[0])
    if len(hosts) != len(set(hosts)) or set(hosts) != expected_hosts:
        raise BundleError("known_hosts does not contain the exact fixed host set")
    with tempfile.NamedTemporaryFile(prefix="finals-hosts-", mode="wb") as handle:
        handle.write(content)
        handle.flush()
        try:
            result = subprocess.run(
                ["ssh-keygen", "-l", "-f", handle.name],
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise BundleError("known_hosts does not contain valid host keys") from error
    if result.stdout.count("SHA256:") != len(expected_hosts):
        raise BundleError("known_hosts contains an invalid host key")


def validate_bundle(bundle_type, files):
    if bundle_type == "gateway-wireguard":
        key = files["private_key"].strip()
        if not WIREGUARD_KEY.fullmatch(key):
            raise BundleError("WireGuard private key is malformed")
    elif bundle_type == "gateway-reconciler":
        validate_ssh_public_key(files["authorized_key"])
    elif bundle_type == "anvil":
        values = parse_environment(files["environment"], ANVIL_ENV)
        fixed = {
            "ANVIL_PRIVATE_ADDRESS": "10.60.200.10",
            "PUBLIC_API_URL": "https://finals.h7tex.com",
            "ANVIL_VPN_PEER_CONTROL": "external",
            "ANVIL_VPN_PUBLIC_ENDPOINT": "vpn.h7tex.com:443",
            "ANVIL_VPN_ALLOWED_IPS": "10.60.0.0/15",
            "ANVIL_TLS_CERT_PATH": "/etc/anvil/tls/fullchain.pem",
            "ANVIL_TLS_KEY_PATH": "/etc/anvil/tls/privkey.pem",
            "ANVIL_DATABASE_HOST_PATH": "/srv/anvil/postgres",
            "ANVIL_STORAGE_HOST_PATH": "/srv/anvil/storage",
            "ANVIL_BACKUP_DIR": "/srv/anvil/backups",
        }
        if any(values[name] != value for name, value in fixed.items()):
            raise BundleError("Anvil environment contains a non-fixed deployment value")
        secrets = [values[name] for name in (
            "ANVIL_DATABASE_PASSWORD",
            "ANVIL_JWT_SECRET",
            "ANVIL_SECRETS_ENCRYPTION_KEY",
            "ANVIL_GAME_INTERNAL_TOKEN",
        )]
        if any(len(value) < 32 or value.startswith("replace-") for value in secrets) or len(set(secrets)) != len(secrets):
            raise BundleError("Anvil secrets must be independent non-placeholder values")
        if not re.fullmatch(r"[0-9a-f]{40}", values["ANVIL_IMAGE_REVISION"]):
            raise BundleError("Anvil image revision must be a full lowercase commit")
        if values["ANVIL_VPN_ENABLED"] not in {"true", "false"}:
            raise BundleError("Anvil VPN enable gate must be true or false")
        if not WIREGUARD_KEY.fullmatch(values["ANVIL_VPN_PUBLIC_KEY"].encode("ascii")):
            raise BundleError("Anvil VPN public key is malformed")
        validate_tls(files["certificate"], files["private_key"], "finals.h7tex.com")
    elif bundle_type == "control-reconciler":
        token = files["token"].strip()
        if len(token) < 32 or len(token) > 4096 or any(character in token for character in b" \t\r\n"):
            raise BundleError("reconciler token is malformed")
        validate_ssh_private_key(files["ssh_private_key"])
        validate_known_hosts(files["known_hosts"], GATEWAY_HOSTS)
    elif bundle_type == "control-checkers":
        token = files["admin_token"].strip()
        if not 32 <= len(token) <= 4096 or not JWT.fullmatch(token):
            raise BundleError("checker commissioning token is malformed")
    elif bundle_type == "repository":
        values = parse_environment(files["environment"], REPOSITORY_ENV)
        if any(len(value) < 32 for value in values.values()) or len(set(values.values())) != 2:
            raise BundleError("repository secrets must be independent values")
        validate_tls(files["certificate"], files["private_key"], "git.h7tex.com")
    elif bundle_type == "operations-relay":
        validate_ssh_private_key(files["ssh_private_key"])
        validate_known_hosts(files["known_hosts"], OPERATIONS_TARGETS)


def validate_anvil_image_binding(files, manifest_path=Path("/etc/runtime-image.json")):
    try:
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BundleError("runtime image manifest is missing or invalid") from error
    expected = document.get("anvil_revision") if isinstance(document, dict) else None
    values = parse_environment(files["environment"], ANVIL_ENV)
    if not isinstance(expected, str) or values["ANVIL_IMAGE_REVISION"] != expected:
        raise BundleError("Anvil environment revision does not match the immutable image")


def owner_ids(account):
    try:
        entry = pwd.getpwnam(account)
    except KeyError as error:
        raise BundleError(f"required local account is missing: {account}") from error
    return entry.pw_uid, entry.pw_gid


def atomic_install(path, content, mode, uid, gid):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, mode)
        os.fchown(descriptor, uid, gid)
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def install_bundle(bundle_type, files, root=Path("/"), ownership=owner_ids):
    targets = BUNDLES[bundle_type]
    identities = {account: ownership(account) for _, _, account in targets.values()}
    for name, (relative_path, mode, account) in targets.items():
        uid, gid = identities[account]
        atomic_install(root / relative_path, files[name], mode, uid, gid)


def decrypt(ciphertext):
    if not ciphertext or len(ciphertext) > MAX_CIPHERTEXT:
        raise BundleError("ciphertext has an invalid size")
    host_identity = Path("/etc/ssh/ssh_host_ed25519_key")
    if not host_identity.is_file() or host_identity.stat().st_mode & 0o077:
        raise BundleError("unique host Ed25519 identity is missing or exposed")
    try:
        result = subprocess.run(
            ["age", "--decrypt", "--identity", str(host_identity)],
            input=ciphertext,
            capture_output=True,
            check=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise BundleError("age decryption failed") from error
    if not result.stdout or len(result.stdout) > MAX_CIPHERTEXT:
        raise BundleError("decrypted bundle has an invalid size")
    return result.stdout


def main():
    if os.geteuid() != 0 or len(sys.argv) != 2 or sys.argv[1] not in BUNDLES:
        print(f"usage: {Path(sys.argv[0]).name} {{{'|'.join(BUNDLES)}}} < bundle.age", file=sys.stderr)
        return 2
    try:
        ciphertext = sys.stdin.buffer.read(MAX_CIPHERTEXT + 1)
        files = decode_bundle(decrypt(ciphertext), sys.argv[1])
        if sys.argv[1] == "anvil":
            validate_anvil_image_binding(files)
        install_bundle(sys.argv[1], files)
    except BundleError as error:
        print(f"secret bundle rejected: {error}", file=sys.stderr)
        return 1
    print(f"installed fixed {sys.argv[1]} secret bundle")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
