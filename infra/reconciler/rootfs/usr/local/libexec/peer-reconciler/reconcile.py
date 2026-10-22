#!/usr/bin/env python3
import argparse
import fcntl
import ipaddress
import json
import os
import ssl
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

MAX_RESPONSE_BYTES = 256 * 1024
CONFIG_KEYS = {
    "endpoint",
    "token_path",
    "ssh_identity_path",
    "known_hosts_path",
    "validator_path",
    "gateways",
}


class ReconcileError(Exception):
    pass


class PublishError(ReconcileError):
    def __init__(self, role):
        super().__init__(f"{role} gateway publish failed")
        self.role = role


class RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        raise ReconcileError("desired-state endpoint redirected")


def emit(event, **fields):
    print(json.dumps({"event": event, **fields}, sort_keys=True), flush=True)


def load_config(path):
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReconcileError("cannot read reconciler configuration") from error

    if not isinstance(config, dict) or set(config) != CONFIG_KEYS:
        raise ReconcileError("configuration contains unexpected fields")

    if not isinstance(config["endpoint"], str):
        raise ReconcileError("endpoint must be a string")
    parsed = urllib.parse.urlsplit(config["endpoint"])
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ReconcileError("endpoint must be an HTTPS URL without credentials, query or fragment")

    for field in ("token_path", "ssh_identity_path", "known_hosts_path", "validator_path"):
        if not isinstance(config[field], str) or not config[field].startswith("/"):
            raise ReconcileError(f"{field} must be an absolute path")

    gateways = config["gateways"]
    if not isinstance(gateways, dict) or set(gateways) != {"standby", "primary"}:
        raise ReconcileError("gateways must define standby and primary")
    try:
        addresses = [str(ipaddress.ip_address(gateways[role])) for role in ("standby", "primary")]
    except (TypeError, ValueError) as error:
        raise ReconcileError("gateway addresses must be IP addresses") from error
    if len(set(addresses)) != 2:
        raise ReconcileError("standby and primary must be different gateways")
    return config


def atomic_write_json(path, value):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(value, output, sort_keys=True, separators=(",", ":"))
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def read_json(path):
    try:
        if path.stat().st_size > MAX_RESPONSE_BYTES:
            raise ReconcileError("state file exceeds size limit")
        value = json.loads(path.read_text(encoding="utf-8"))
    except ReconcileError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReconcileError("cannot read reconciler state") from error
    return value


def validate_inventory(path, validator_path, active_path=None):
    with tempfile.TemporaryDirectory(prefix="peer-reconciler-") as directory:
        arguments = [
            validator_path,
            str(path),
            "--wireguard-output",
            f"{directory}/wireguard.conf",
            "--nft-output",
            f"{directory}/peers.nft",
        ]
        if active_path and active_path.exists():
            arguments.extend(("--active-inventory", str(active_path)))
        try:
            subprocess.run(
                arguments,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise ReconcileError("peer inventory validation failed") from error


def read_private_text(path, maximum):
    try:
        stat = path.stat()
        if not path.is_file() or stat.st_mode & 0o077:
            raise ReconcileError("secret file permissions are too broad")
        value = path.read_bytes()
    except ReconcileError:
        raise
    except OSError as error:
        raise ReconcileError("cannot read secret file") from error
    if not value or len(value) > maximum:
        raise ReconcileError("secret file has an invalid size")
    try:
        text = value.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ReconcileError("secret file is not UTF-8") from error
    text = text.strip()
    if not text or any(character.isspace() for character in text):
        raise ReconcileError("secret must not contain whitespace")
    return text


def require_private_file(path, maximum):
    try:
        stat = path.stat()
    except OSError as error:
        raise ReconcileError("private file is missing") from error
    if not path.is_file() or stat.st_mode & 0o077 or not 0 < stat.st_size <= maximum:
        raise ReconcileError("private file permissions or size are invalid")


def fetch_desired(config):
    token = read_private_text(Path(config["token_path"]), 4096)
    request = urllib.request.Request(
        config["endpoint"],
        headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
        method="GET",
    )
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        RejectRedirects(),
    )
    try:
        with opener.open(request, timeout=10) as response:
            content_type = response.headers.get_content_type()
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except (OSError, urllib.error.URLError, ReconcileError) as error:
        raise ReconcileError("desired-state request failed") from error
    if content_type != "application/json" or len(body) > MAX_RESPONSE_BYTES:
        raise ReconcileError("desired-state response is invalid")
    try:
        desired = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReconcileError("desired-state response is not valid JSON") from error
    if not isinstance(desired, dict) or set(desired) != {"peers"} or not isinstance(desired["peers"], list):
        raise ReconcileError("desired-state response must contain only peers")
    return desired["peers"]


def publish(config, role, address, payload):
    identity = Path(config["ssh_identity_path"])
    require_private_file(identity, 32 * 1024)
    known_hosts = Path(config["known_hosts_path"])
    if not known_hosts.is_file():
        raise ReconcileError("known-hosts file is missing")
    command = [
        "/usr/bin/ssh",
        "-T",
        "-o", "BatchMode=yes",
        "-o", "ClearAllForwardings=yes",
        "-o", "ConnectTimeout=5",
        "-o", "GlobalKnownHostsFile=/dev/null",
        "-o", "IdentitiesOnly=yes",
        "-o", "KbdInteractiveAuthentication=no",
        "-o", "PasswordAuthentication=no",
        "-o", "RequestTTY=no",
        "-o", "StrictHostKeyChecking=yes",
        "-o", f"UserKnownHostsFile={known_hosts}",
        "-i", str(identity),
        f"peer-reconciler@{address}",
    ]
    try:
        subprocess.run(
            command,
            input=payload,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise PublishError(role) from error


def reconcile(config, state_directory, fetcher=fetch_desired, publisher=publish):
    active_path = state_directory / "active.json"
    pending_path = state_directory / "pending.json"
    validator_path = config["validator_path"]

    active = None
    if active_path.exists():
        validate_inventory(active_path, validator_path)
        active = read_json(active_path)

    if pending_path.exists():
        validate_inventory(pending_path, validator_path, active_path)
        candidate = read_json(pending_path)
    else:
        desired = fetcher(config)
        peers = sorted(desired, key=lambda peer: json.dumps(peer, sort_keys=True, separators=(",", ":")))
        if active is not None and peers == active["peers"]:
            emit("reconcile_no_change", generation=active["generation"], peer_count=len(peers))
            return "unchanged"
        candidate = {
            "version": 1,
            "generation": 1 if active is None else active["generation"] + 1,
            "peers": peers,
        }
        candidate_path = state_directory / ".candidate.json"
        atomic_write_json(candidate_path, candidate)
        try:
            validate_inventory(candidate_path, validator_path, active_path)
            os.replace(candidate_path, pending_path)
            directory = os.open(state_directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            candidate_path.unlink(missing_ok=True)

    payload = json.dumps(candidate, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
    if len(payload) > MAX_RESPONSE_BYTES:
        raise ReconcileError("peer inventory exceeds publish size limit")

    for role in ("standby", "primary"):
        publisher(config, role, config["gateways"][role], payload)

    atomic_write_json(active_path, candidate)
    try:
        pending_path.unlink()
    except FileNotFoundError:
        pass
    emit("reconcile_applied", generation=candidate["generation"], peer_count=len(candidate["peers"]))
    return "applied"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("/etc/peer-reconciler/config.json"))
    parser.add_argument("--state-directory", type=Path, default=Path("/var/lib/peer-reconciler"))
    args = parser.parse_args()

    try:
        config = load_config(args.config)
        args.state_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        lock = (args.state_directory / "lock").open("w", encoding="utf-8")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            emit("reconcile_skipped", reason="already_running")
            return
        reconcile(config, args.state_directory)
    except PublishError as error:
        emit("reconcile_failed", gateway_role=error.role)
        raise SystemExit(1)
    except ReconcileError:
        emit("reconcile_failed")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
