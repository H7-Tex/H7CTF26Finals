#!/usr/bin/env python3
import argparse
import hashlib
import http.client
import json
import os
import re
import signal
import stat
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath

MANIFEST_PATH = Path("/etc/finals-platform/checkers/artifact-manifest.json")
ARTIFACT_ROOT = Path("/opt/finals-checkers")
STATE_ROOT = Path("/var/lib/checker-runtime")
STATE_PATH = STATE_ROOT / "state.json"
ENABLE_PATH = Path("/etc/checker-runtime/enabled")
TOKEN_PATH = Path("/etc/checker-runtime/anvil-admin.token")
CONTROL_ADDRESS = "10.60.201.20"
HEALTH_ADDRESS = "127.0.0.1"
HEALTH_PORT = 9160
ANVIL_BASE_URL = "https://finals.h7tex.com"
DATABASE_IMAGE = (
    "mongo@sha256:c53852c00c23ca9f23fc39690350ffa9a80e3642fe8f96879726d8da0abe80a7"
)
EGRESS_NETWORK = "checker-egress"
EGRESS_SUBNET = "172.31.28.0/24"
MANAGED_LABEL = "checker-runtime.managed"
SPEC_LABEL = "checker-runtime.spec"
CONTAINER_CONTRACT = 1
HEX64 = re.compile(r"[0-9a-f]{64}")
IMAGE = re.compile(r"[a-z0-9][a-z0-9._/-]*:[A-Za-z0-9][A-Za-z0-9._-]*")
JWT = re.compile(rb"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
MAX_ARTIFACT_SIZE = 2 * 1024 * 1024 * 1024


EXPECTED = (
    {
        "slot": "AD1",
        "name": "Sign Me In",
        "slug": "sign-me-in",
        "category": "web",
        "target_port": 7001,
        "checker_port": 9001,
        "flag_stores": 2,
        "noise_variants": 1,
        "havoc_variants": 5,
        "timeout_ms": 15000,
    },
    {
        "slot": "AD2",
        "name": "Can We Settle This?",
        "slug": "can-we-settle-this",
        "category": "web",
        "target_port": 7002,
        "checker_port": 9002,
        "flag_stores": 2,
        "noise_variants": 1,
        "havoc_variants": 3,
        "timeout_ms": 12000,
    },
    {
        "slot": "AD3",
        "name": "Update Pending",
        "slug": "update-pending",
        "category": "pwn",
        "target_port": 7003,
        "checker_port": 9003,
        "flag_stores": 2,
        "noise_variants": 1,
        "havoc_variants": 3,
        "timeout_ms": 10000,
    },
    {
        "slot": "AD4",
        "name": "Book Me If You Can",
        "slug": "book-me-if-you-can",
        "category": "web",
        "target_port": 7004,
        "checker_port": 9004,
        "flag_stores": 2,
        "noise_variants": 1,
        "havoc_variants": 2,
        "timeout_ms": 12000,
    },
    {
        "slot": "AD5",
        "name": "Ship It",
        "slug": "ship-it",
        "category": "web",
        "target_port": 7005,
        "checker_port": 9005,
        "flag_stores": 2,
        "noise_variants": 1,
        "havoc_variants": 4,
        "timeout_ms": 12000,
    },
    {
        "slot": "AD6",
        "name": "Terms May Apply",
        "slug": "terms-may-apply",
        "category": "pwn",
        "target_port": 7006,
        "checker_port": 9006,
        "flag_stores": 2,
        "noise_variants": 2,
        "havoc_variants": 4,
        "timeout_ms": 18000,
    },
)
SERVICE_FIELDS = set(EXPECTED[0]) | {"artifact"}
ARTIFACT_FIELDS = {"path", "sha256", "size", "executable", "image", "image_id"}


class RuntimeErrorSafe(Exception):
    pass


def log(event, **fields):
    record = {"event": event, **fields}
    print(json.dumps(record, sort_keys=True, separators=(",", ":")), flush=True)


def digest_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_digest(document):
    body = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(body).hexdigest()


def atomic_json(path, document, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(document, output, sort_keys=True, separators=(",", ":"))
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


def read_json(path, label):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeErrorSafe(f"{label} is missing or invalid") from error


def _safe_artifact(path, root):
    relative = PurePosixPath(path)
    if relative.is_absolute() or ".." in relative.parts or len(relative.parts) != 2:
        raise RuntimeErrorSafe(
            "artifact path must be a direct file below its service directory"
        )
    target = root / relative
    try:
        resolved_root = root.resolve(strict=True)
        resolved = target.resolve(strict=True)
    except OSError as error:
        raise RuntimeErrorSafe(f"artifact is absent: {path}") from error
    if (
        resolved.parent.parent != resolved_root
        or resolved.parent.name != relative.parts[0]
    ):
        raise RuntimeErrorSafe(f"artifact escapes its service directory: {path}")
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise RuntimeErrorSafe(f"artifact path contains a symbolic link: {path}")
    return target


def validate_manifest(
    document, artifact_root=ARTIFACT_ROOT, verify_files=True, require_root=False
):
    if not isinstance(document, dict) or set(document) != {
        "version",
        "database_image",
        "services",
    }:
        raise RuntimeErrorSafe("artifact manifest schema is invalid")
    if document["version"] != 2 or document["database_image"] != DATABASE_IMAGE:
        raise RuntimeErrorSafe("artifact manifest version or database image is invalid")
    services = document["services"]
    if not isinstance(services, list) or len(services) != len(EXPECTED):
        raise RuntimeErrorSafe("artifact manifest must contain exactly six services")
    seen_paths = set()
    seen_digests = set()
    seen_images = set()
    seen_image_ids = set()
    for index, (service, expected) in enumerate(zip(services, EXPECTED)):
        if not isinstance(service, dict) or set(service) != SERVICE_FIELDS:
            raise RuntimeErrorSafe(f"service entry {index + 1} schema is invalid")
        for key, value in expected.items():
            if service.get(key) != value:
                raise RuntimeErrorSafe(
                    f"service entry {index + 1} does not match the locked {expected['slot']} contract"
                )
        artifact = service["artifact"]
        if not isinstance(artifact, dict) or set(artifact) != ARTIFACT_FIELDS:
            raise RuntimeErrorSafe(f"artifact entry for {expected['slug']} is invalid")
        required_path = f"{expected['slug']}/checker-image.tar"
        if artifact["path"] != required_path or artifact["path"] in seen_paths:
            raise RuntimeErrorSafe(
                f"artifact path for {expected['slug']} is invalid or duplicate"
            )
        if (
            not isinstance(artifact["sha256"], str)
            or not HEX64.fullmatch(artifact["sha256"])
            or artifact["sha256"] in seen_digests
        ):
            raise RuntimeErrorSafe(
                f"artifact digest for {expected['slug']} is invalid or duplicate"
            )
        if (
            type(artifact["size"]) is not int
            or not 1 <= artifact["size"] <= MAX_ARTIFACT_SIZE
            or artifact["executable"] is not False
        ):
            raise RuntimeErrorSafe(
                f"artifact size or executable marker for {expected['slug']} is invalid"
            )
        if (
            not isinstance(artifact["image"], str)
            or not IMAGE.fullmatch(artifact["image"])
            or artifact["image"].endswith(":latest")
        ):
            raise RuntimeErrorSafe(
                f"artifact image reference for {expected['slug']} is not immutable"
            )
        if (
            artifact["image"] in seen_images
            or not isinstance(artifact["image_id"], str)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", artifact["image_id"])
            or artifact["image_id"] in seen_image_ids
        ):
            raise RuntimeErrorSafe(
                f"artifact image identity for {expected['slug']} is invalid or duplicate"
            )
        if verify_files:
            target = _safe_artifact(artifact["path"], artifact_root)
            try:
                metadata = target.stat()
            except OSError as error:
                raise RuntimeErrorSafe(
                    f"artifact cannot be read: {artifact['path']}"
                ) from error
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_size != artifact["size"]
            ):
                raise RuntimeErrorSafe(f"artifact size changed: {artifact['path']}")
            if (
                stat.S_IMODE(metadata.st_mode) != 0o600
                or bool(metadata.st_mode & 0o111) != artifact["executable"]
            ):
                raise RuntimeErrorSafe(f"artifact mode changed: {artifact['path']}")
            if require_root and metadata.st_uid != 0:
                raise RuntimeErrorSafe(
                    f"artifact is not root-owned: {artifact['path']}"
                )
            if digest_file(target) != artifact["sha256"]:
                raise RuntimeErrorSafe(f"artifact digest changed: {artifact['path']}")
        seen_paths.add(artifact["path"])
        seen_digests.add(artifact["sha256"])
        seen_images.add(artifact["image"])
        seen_image_ids.add(artifact["image_id"])
    return services


def load_manifest(
    path=MANIFEST_PATH,
    artifact_root=ARTIFACT_ROOT,
    verify_files=True,
    require_root=False,
):
    if require_root:
        try:
            manifest_metadata = path.lstat()
            root_metadata = artifact_root.lstat()
        except OSError as error:
            raise RuntimeErrorSafe("artifact manifest or root is missing") from error
        if (
            not stat.S_ISREG(manifest_metadata.st_mode)
            or path.is_symlink()
            or stat.S_IMODE(manifest_metadata.st_mode) != 0o600
            or manifest_metadata.st_uid != 0
        ):
            raise RuntimeErrorSafe("artifact manifest ownership or mode is unsafe")
        if (
            not stat.S_ISDIR(root_metadata.st_mode)
            or artifact_root.is_symlink()
            or stat.S_IMODE(root_metadata.st_mode) != 0o700
            or root_metadata.st_uid != 0
        ):
            raise RuntimeErrorSafe("artifact root ownership or mode is unsafe")
    document = read_json(path, "artifact manifest")
    validate_manifest(document, artifact_root, verify_files, require_root)
    return document


def load_state(path=STATE_PATH):
    if not path.exists():
        return {"version": 1, "imports": {}, "registrations": {}}
    document = read_json(path, "runtime state")
    if not isinstance(document, dict) or document.get("version") != 1:
        raise RuntimeErrorSafe("runtime state schema is invalid")
    if not isinstance(document.get("imports"), dict) or not isinstance(
        document.get("registrations"), dict
    ):
        raise RuntimeErrorSafe("runtime state schema is invalid")
    return document


class DockerEngine:
    def __init__(self, binary="docker"):
        self.binary = binary

    def _run(self, arguments, operation, allow_missing=False):
        try:
            result = subprocess.run(
                [self.binary, *arguments],
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
                env={
                    "PATH": os.environ.get("PATH", "/usr/sbin:/usr/bin:/sbin:/bin"),
                    "HOME": "/run/checker-runtime",
                },
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise RuntimeErrorSafe(
                f"container engine failed during {operation}"
            ) from error
        if result.returncode != 0:
            if allow_missing:
                return None
            raise RuntimeErrorSafe(f"container engine rejected {operation}")
        return result.stdout

    def image_id(self, reference):
        output = self._run(
            ["image", "inspect", "--format", "{{.Id}}", reference],
            "image inspection",
            True,
        )
        return output.strip() if output else None

    def load_image(self, archive):
        self._run(["image", "load", "--input", str(archive)], "image import")

    def network(self, name):
        output = self._run(["network", "inspect", name], "network inspection", True)
        if not output:
            return None
        try:
            return json.loads(output)[0]
        except (json.JSONDecodeError, IndexError, TypeError) as error:
            raise RuntimeErrorSafe(
                "container network inspection was invalid"
            ) from error

    def ensure_network(self, name, subnet, internal, disable_icc=False):
        existing = self.network(name)
        if existing is not None:
            labels = existing.get("Labels") or {}
            options = existing.get("Options") or {}
            configs = (existing.get("IPAM") or {}).get("Config") or []
            actual_subnets = {
                entry.get("Subnet") for entry in configs if isinstance(entry, dict)
            }
            if (
                labels.get(MANAGED_LABEL) != "true"
                or existing.get("Internal") is not internal
                or actual_subnets != {subnet}
                or (
                    disable_icc
                    and options.get("com.docker.network.bridge.enable_icc") != "false"
                )
            ):
                raise RuntimeErrorSafe(
                    f"container network {name} does not match the fixed contract"
                )
            return
        command = [
            "network",
            "create",
            "--driver",
            "bridge",
            "--subnet",
            subnet,
            "--label",
            f"{MANAGED_LABEL}=true",
        ]
        if internal:
            command.append("--internal")
        if disable_icc:
            command.extend(["--opt", "com.docker.network.bridge.enable_icc=false"])
        command.append(name)
        self._run(command, "network creation")

    def container(self, name):
        output = self._run(["container", "inspect", name], "container inspection", True)
        if not output:
            return None
        try:
            return json.loads(output)[0]
        except (json.JSONDecodeError, IndexError, TypeError) as error:
            raise RuntimeErrorSafe("container inspection was invalid") from error

    def remove_container(self, name):
        self._run(["container", "rm", "--force", name], "managed container replacement")

    def create_container(self, arguments):
        self._run(["container", "create", *arguments], "container creation")

    def ensure_connected(self, network, name):
        existing = self.container(name)
        networks = ((existing or {}).get("NetworkSettings") or {}).get("Networks") or {}
        if network not in networks:
            self._run(
                ["network", "connect", network, name], "container network attachment"
            )

    def container_networks(self, name):
        existing = self.container(name)
        return set(
            (
                ((existing or {}).get("NetworkSettings") or {}).get("Networks") or {}
            ).keys()
        )

    def start_container(self, name):
        self._run(["container", "start", name], "container start")

    def stop_container(self, name):
        existing = self.container(name)
        if existing is not None:
            labels = (existing.get("Config") or {}).get("Labels") or {}
            if labels.get(MANAGED_LABEL) != "true":
                raise RuntimeErrorSafe(
                    f"refusing to remove unmanaged container: {name}"
                )
            self._run(["container", "rm", "--force", name], "container stop")


def _spec_hash(kind, service, image):
    fields = {key: service[key] for key in EXPECTED[0]}
    fields.update(
        {
            "kind": kind,
            "image": image,
            "address": CONTROL_ADDRESS,
            "contract": CONTAINER_CONTRACT,
        }
    )
    return canonical_digest(fields)


def state_network(service):
    index = int(service["slot"][2:])
    return f"checker-state-{service['slug']}", f"172.31.{30 + index}.0/24"


def database_arguments(service):
    slug = service["slug"]
    name = f"checker-db-{slug}"
    state = STATE_ROOT / "data" / slug / "mongo"
    network, _ = state_network(service)
    specification = _spec_hash("database", service, DATABASE_IMAGE)
    return (
        name,
        specification,
        [
            "--name",
            name,
            "--hostname",
            name,
            "--label",
            f"{MANAGED_LABEL}=true",
            "--label",
            f"{SPEC_LABEL}={specification}",
            "--network",
            network,
            "--user",
            "999:999",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,size=32m,mode=1777",
            "--tmpfs",
            "/data/configdb:rw,noexec,nosuid,nodev,size=32m,uid=999,gid=999,mode=0700",
            "--mount",
            f"type=bind,src={state},dst=/data/db",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--pids-limit",
            "128",
            "--memory",
            "512m",
            "--cpus",
            "0.5",
            "--log-driver",
            "none",
            "--health-cmd",
            "mongosh --quiet --eval 'quit(db.runCommand({ping:1}).ok ? 0 : 1)'",
            "--health-interval",
            "5s",
            "--health-timeout",
            "10s",
            "--health-retries",
            "18",
            DATABASE_IMAGE,
            "mongod",
            "--bind_ip_all",
            "--quiet",
            "--wiredTigerCacheSizeGB",
            "0.25",
        ],
    )


def checker_arguments(service, address=CONTROL_ADDRESS):
    slug = service["slug"]
    name = f"checker-{slug}"
    artifact = service["artifact"]
    network, _ = state_network(service)
    specification = _spec_hash("checker", service, artifact["image_id"])
    return (
        name,
        specification,
        [
            "--name",
            name,
            "--hostname",
            name,
            "--label",
            f"{MANAGED_LABEL}=true",
            "--label",
            f"{SPEC_LABEL}={specification}",
            "--network",
            network,
            "--env",
            f"MONGO_HOST=checker-db-{slug}",
            "--env",
            "MONGO_PORT=27017",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,size=32m,mode=1777",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--pids-limit",
            "96",
            "--memory",
            "384m",
            "--cpus",
            "0.5",
            "--log-driver",
            "none",
            "--publish",
            f"{address}:{service['checker_port']}:8000/tcp",
            artifact["image"],
        ],
    )


class Runtime:
    def __init__(
        self,
        engine=None,
        manifest_path=MANIFEST_PATH,
        artifact_root=ARTIFACT_ROOT,
        state_path=STATE_PATH,
        address=CONTROL_ADDRESS,
        probe=None,
    ):
        self.engine = engine or DockerEngine()
        self.manifest_path = Path(manifest_path)
        self.artifact_root = Path(artifact_root)
        self.state_path = Path(state_path)
        self.address = address
        self.probe = probe or self._probe
        self.artifact_snapshot = None

    def manifest(self, verify_files=True):
        document = load_manifest(
            self.manifest_path,
            self.artifact_root,
            verify_files,
            require_root=os.geteuid() == 0 and self.manifest_path == MANIFEST_PATH,
        )
        snapshot = {}
        for service in document["services"]:
            path = _safe_artifact(service["artifact"]["path"], self.artifact_root)
            metadata = path.stat()
            snapshot[service["slug"]] = (
                metadata.st_dev,
                metadata.st_ino,
                metadata.st_size,
                metadata.st_mtime_ns,
                stat.S_IMODE(metadata.st_mode),
                metadata.st_uid,
            )
        if verify_files:
            self.artifact_snapshot = snapshot
        elif self.artifact_snapshot is None or snapshot != self.artifact_snapshot:
            raise RuntimeErrorSafe(
                "checker artifacts changed after integrity verification"
            )
        return document

    def import_artifacts(self):
        document = self.manifest(True)
        if self.engine.image_id(DATABASE_IMAGE) is None:
            raise RuntimeErrorSafe(
                "pinned checker database image is absent from the reviewed host image"
            )
        state = load_state(self.state_path)
        manifest_sha = canonical_digest(document)
        imports = {}
        for service in document["services"]:
            artifact = service["artifact"]
            actual = self.engine.image_id(artifact["image"])
            if actual != artifact["image_id"]:
                if actual is not None:
                    raise RuntimeErrorSafe(
                        f"loaded checker image does not match manifest: {service['slug']}"
                    )
                self.engine.load_image(self.artifact_root / artifact["path"])
                actual = self.engine.image_id(artifact["image"])
                if actual != artifact["image_id"]:
                    raise RuntimeErrorSafe(
                        f"checker archive imported an unexpected image: {service['slug']}"
                    )
                log("checker_image_imported", service=service["slug"])
            imports[service["slug"]] = artifact["image_id"]
        state["manifest_sha256"] = manifest_sha
        state["imports"] = imports
        atomic_json(self.state_path, state)
        return document

    def _verify_import(self, document):
        state = load_state(self.state_path)
        if state.get("manifest_sha256") != canonical_digest(document):
            raise RuntimeErrorSafe("runtime manifest has not been imported")
        for service in document["services"]:
            expected = service["artifact"]["image_id"]
            if (
                state["imports"].get(service["slug"]) != expected
                or self.engine.image_id(service["artifact"]["image"]) != expected
            ):
                raise RuntimeErrorSafe(
                    f"checker image is not imported exactly: {service['slug']}"
                )
        if self.engine.image_id(DATABASE_IMAGE) is None:
            raise RuntimeErrorSafe("pinned checker database image is absent")

    def _ensure_container(self, name, specification, arguments, extra_network=None):
        existing = self.engine.container(name)
        if existing is not None:
            labels = (existing.get("Config") or {}).get("Labels") or {}
            image_id = existing.get("Image")
            wanted_image = (
                DATABASE_IMAGE if name.startswith("checker-db-") else arguments[-1]
            )
            expected_image_id = self.engine.image_id(wanted_image)
            if labels.get(MANAGED_LABEL) != "true":
                raise RuntimeErrorSafe(
                    f"refusing to replace unmanaged container: {name}"
                )
            if labels.get(SPEC_LABEL) != specification or image_id != expected_image_id:
                self.engine.remove_container(name)
                existing = None
                log("checker_container_replaced", component=name)
        if existing is None:
            self.engine.create_container(arguments)
        primary_network = arguments[arguments.index("--network") + 1]
        self.engine.ensure_connected(primary_network, name)
        if extra_network:
            self.engine.ensure_connected(extra_network, name)
        expected_networks = {primary_network} | (
            {extra_network} if extra_network else set()
        )
        if self.engine.container_networks(name) != expected_networks:
            raise RuntimeErrorSafe(
                f"managed container network attachments drifted: {name}"
            )
        current = self.engine.container(name)
        if current is None or not (current.get("State") or {}).get("Running", False):
            self.engine.start_container(name)

    def reconcile(self, verify_files=True):
        document = self.manifest(verify_files)
        self._verify_import(document)
        self.engine.ensure_network(
            EGRESS_NETWORK, EGRESS_SUBNET, False, disable_icc=True
        )
        for service in document["services"]:
            network, subnet = state_network(service)
            self.engine.ensure_network(network, subnet, True)
            directory = STATE_ROOT / "data" / service["slug"] / "mongo"
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(directory, 0o700)
            if os.geteuid() == 0:
                os.chown(directory, 999, 999)
            db_name, db_spec, db_arguments = database_arguments(service)
            self._ensure_container(db_name, db_spec, db_arguments)
            checker_name, checker_spec, checker_args = checker_arguments(
                service, self.address
            )
            self._ensure_container(
                checker_name, checker_spec, checker_args, EGRESS_NETWORK
            )
        return document

    def stop(self):
        names = []
        for service in reversed(EXPECTED):
            names.extend(
                (
                    f"checker-{service['slug']}",
                    f"checker-db-{service['slug']}",
                )
            )
        for name in names:
            existing = self.engine.container(name)
            labels = ((existing or {}).get("Config") or {}).get("Labels") or {}
            if existing is not None and labels.get(MANAGED_LABEL) != "true":
                raise RuntimeErrorSafe(
                    f"refusing to remove unmanaged container: {name}"
                )
        for name in names:
            self.engine.stop_container(name)

    @staticmethod
    def _probe(address, port):
        connection = None
        try:
            connection = http.client.HTTPConnection(address, port, timeout=2)
            connection.request("GET", "/openapi.json")
            response = connection.getresponse()
            response.read(4096)
            return response.status == 200
        except (OSError, http.client.HTTPException):
            return False
        finally:
            if connection is not None:
                connection.close()

    def status(self, verify_files=True):
        try:
            document = self.manifest(verify_files)
            self._verify_import(document)
        except RuntimeErrorSafe as error:
            return {"ready": False, "reason": str(error), "services": []}
        result = []
        ready = True
        for service in document["services"]:
            db = self.engine.container(f"checker-db-{service['slug']}")
            checker = self.engine.container(f"checker-{service['slug']}")
            db_state = (db or {}).get("State") or {}
            checker_state = (checker or {}).get("State") or {}
            database_ready = (
                db_state.get("Running", False)
                and (db_state.get("Health") or {}).get("Status") == "healthy"
            )
            checker_ready = checker_state.get("Running", False) and self.probe(
                self.address, service["checker_port"]
            )
            service_ready = bool(database_ready and checker_ready)
            ready = ready and service_ready
            result.append({"slug": service["slug"], "ready": service_ready})
        return {"ready": ready, "services": result}


class AnvilClient:
    def __init__(self, base_url=ANVIL_BASE_URL, token_path=TOKEN_PATH, timeout=10):
        self.base_url = base_url.rstrip("/")
        self.token_path = Path(token_path)
        self.timeout = timeout
        parsed = urllib.parse.urlsplit(self.base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise RuntimeErrorSafe("Anvil registration URL is invalid")
        if parsed.scheme != "https" and parsed.hostname not in {
            "127.0.0.1",
            "::1",
            "localhost",
        }:
            raise RuntimeErrorSafe("Anvil registration URL must use HTTPS")

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(
                self, _request, _fp, _code, _message, _headers, _new_url
            ):
                return None

        self.opener = urllib.request.build_opener(NoRedirect)

    def _token(self):
        try:
            metadata = self.token_path.lstat()
            token = self.token_path.read_bytes().strip()
        except OSError as error:
            raise RuntimeErrorSafe("Anvil commissioning token is missing") from error
        if (
            not stat.S_ISREG(metadata.st_mode)
            or self.token_path.is_symlink()
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or (os.geteuid() == 0 and metadata.st_uid != 0)
        ):
            raise RuntimeErrorSafe("Anvil commissioning token permissions are unsafe")
        if not 32 <= len(token) <= 4096 or not JWT.fullmatch(token):
            raise RuntimeErrorSafe("Anvil commissioning token is malformed")
        return token.decode("ascii")

    def request(self, method, path, payload=None):
        body = (
            None
            if payload is None
            else json.dumps(payload, separators=(",", ":")).encode()
        )
        request = urllib.request.Request(
            self.base_url + path,
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self._token()}",
                "Content-Type": "application/json",
            },
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read(1024 * 1024 + 1)
                status = response.status
        except urllib.error.HTTPError as error:
            raise RuntimeErrorSafe(
                f"Anvil registration request returned HTTP {error.code}"
            ) from None
        except (OSError, urllib.error.URLError) as error:
            raise RuntimeErrorSafe("Anvil registration request failed") from error
        if len(raw) > 1024 * 1024:
            raise RuntimeErrorSafe("Anvil registration response exceeded its limit")
        try:
            document = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RuntimeErrorSafe("Anvil registration response was invalid") from error
        return status, document


def registration_payload(service):
    return {
        "name": service["name"],
        "slug": service["slug"],
        "category": service["category"],
        "tier": "core",
        "port": service["target_port"],
        "checker_ref": f"http://{CONTROL_ADDRESS}:{service['checker_port']}",
        "flag_stores": service["flag_stores"],
        "noise_variants": service["noise_variants"],
        "havoc_variants": service["havoc_variants"],
    }


def _visible_registration(payload):
    try:
        return {
            key: payload[key]
            for key in ("name", "slug", "category", "tier", "port", "checker_ref")
        }
    except KeyError as error:
        raise RuntimeErrorSafe("Anvil service inventory response is invalid") from error


def _registration_inventory(response, require_complete=False):
    if not isinstance(response, dict) or not isinstance(response.get("services"), list):
        raise RuntimeErrorSafe("Anvil service inventory response is invalid")
    expected = {service["slug"] for service in EXPECTED}
    inventory = {}
    for item in response["services"]:
        if not isinstance(item, dict) or not isinstance(item.get("slug"), str):
            raise RuntimeErrorSafe("Anvil service inventory response is invalid")
        slug = item["slug"]
        if slug not in expected:
            raise RuntimeErrorSafe(f"Anvil service inventory is unexpected: {slug}")
        if slug in inventory:
            raise RuntimeErrorSafe(f"Anvil service inventory is duplicated: {slug}")
        if item.get("enabled") is not True:
            raise RuntimeErrorSafe(f"Anvil service is not enabled: {slug}")
        inventory[slug] = item
    if require_complete and set(inventory) != expected:
        raise RuntimeErrorSafe("Anvil service inventory is not exactly six services")
    return inventory


def register_services(runtime, client):
    document = runtime.manifest(True)
    runtime._verify_import(document)
    health = runtime.status(False)
    if not health["ready"]:
        raise RuntimeErrorSafe(
            "all six checker services must be ready before Anvil registration"
        )
    info_status, info = client.request("GET", "/api/v1/info")
    if (
        info_status != 200
        or not isinstance(info, dict)
        or info.get("game_state") != "stopped"
    ):
        raise RuntimeErrorSafe(
            "Anvil game state must be explicitly stopped before service registration"
        )
    status, response = client.request("GET", "/api/v1/admin/arena/services")
    if status != 200:
        raise RuntimeErrorSafe("Anvil service inventory response is invalid")
    existing = _registration_inventory(response)
    state = load_state(runtime.state_path)
    registrations = state["registrations"]
    for service in document["services"]:
        slug = service["slug"]
        payload = registration_payload(service)
        fingerprint = canonical_digest(payload)
        record = registrations.get(slug)
        found = existing.get(slug)
        if found is not None:
            if _visible_registration(found) != _visible_registration(payload):
                raise RuntimeErrorSafe(f"Anvil service registration drifted: {slug}")
            if (
                not isinstance(record, dict)
                or record.get("fingerprint") != fingerprint
                or record.get("status") not in {"pending", "registered"}
            ):
                raise RuntimeErrorSafe(
                    f"Anvil service exists without a matching local registration journal: {slug}"
                )
            registrations[slug] = {"fingerprint": fingerprint, "status": "registered"}
            atomic_json(runtime.state_path, state)
            continue
        registrations[slug] = {"fingerprint": fingerprint, "status": "pending"}
        atomic_json(runtime.state_path, state)
        created_status, created = client.request(
            "POST", "/api/v1/admin/arena/services", payload
        )
        if (
            created_status != 201
            or not isinstance(created, dict)
            or not isinstance(created.get("id"), str)
        ):
            raise RuntimeErrorSafe(f"Anvil rejected service registration: {slug}")
        registrations[slug] = {"fingerprint": fingerprint, "status": "registered"}
        atomic_json(runtime.state_path, state)
        log("checker_registered", service=slug)
    final_status, final_response = client.request("GET", "/api/v1/admin/arena/services")
    if final_status != 200:
        raise RuntimeErrorSafe("Anvil service inventory response is invalid")
    final_inventory = _registration_inventory(final_response, require_complete=True)
    for service in document["services"]:
        slug = service["slug"]
        payload = registration_payload(service)
        if _visible_registration(final_inventory[slug]) != _visible_registration(
            payload
        ):
            raise RuntimeErrorSafe(f"Anvil service registration drifted: {slug}")
    state["registration_manifest_sha256"] = canonical_digest(document)
    atomic_json(runtime.state_path, state)


class HealthHandler(BaseHTTPRequestHandler):
    runtime = None

    def do_GET(self):
        if self.path == "/healthz":
            body, status = {"status": "ok"}, 200
        elif self.path == "/readyz":
            body = self.runtime.status(False)
            status = 200 if body["ready"] else 503
        else:
            body, status = {"error": "not found"}, 404
        encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, _format, *_args):
        return


def enabled(path=ENABLE_PATH):
    try:
        metadata = path.stat()
        value = path.read_text(encoding="ascii")
    except (OSError, UnicodeDecodeError) as error:
        raise RuntimeErrorSafe(
            "checker runtime enable gate is absent or invalid"
        ) from error
    if (
        value != "enabled\n"
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or (os.geteuid() == 0 and metadata.st_uid != 0)
    ):
        raise RuntimeErrorSafe("checker runtime enable gate is invalid")


def serve(runtime, interval=15):
    enabled()
    runtime.manifest(True)
    stop = threading.Event()
    for event in (signal.SIGINT, signal.SIGTERM):
        signal.signal(event, lambda *_: stop.set())

    class Handler(HealthHandler):
        pass

    Handler.runtime = runtime
    server = ThreadingHTTPServer((HEALTH_ADDRESS, HEALTH_PORT), Handler)
    server.daemon_threads = True
    server.timeout = 1
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    log("checker_runtime_started", service_count=6)
    while not stop.is_set():
        try:
            runtime.reconcile(False)
            health = runtime.status(False)
            log(
                "checker_reconciled",
                ready=health["ready"],
                ready_services=sum(item["ready"] for item in health["services"]),
            )
        except RuntimeErrorSafe as error:
            log("checker_reconcile_failed", reason=str(error))
        stop.wait(interval)
    server.shutdown()
    worker.join(timeout=5)
    server.server_close()
    log("checker_runtime_stopped")


def parse_args(arguments=None):
    parser = argparse.ArgumentParser(
        description="Manage the private six-checker runtime"
    )
    parser.add_argument(
        "command",
        choices=(
            "validate-artifacts",
            "import",
            "reconcile",
            "register",
            "status",
            "serve",
            "stop",
        ),
    )
    parser.add_argument("--wait", type=int, default=0, metavar="SECONDS")
    return parser.parse_args(arguments)


def main(arguments=None):
    options = parse_args(arguments)
    runtime = Runtime()
    try:
        if options.command == "validate-artifacts":
            runtime.manifest(True)
            log("checker_artifacts_valid", service_count=6)
        elif options.command == "import":
            runtime.import_artifacts()
            log("checker_import_complete", service_count=6)
        elif options.command == "reconcile":
            runtime.manifest(True)
            deadline = time.monotonic() + max(0, options.wait)
            while True:
                runtime.reconcile(False)
                health = runtime.status(False)
                if health["ready"] or time.monotonic() >= deadline:
                    if not health["ready"]:
                        raise RuntimeErrorSafe(
                            "checker services did not become ready before the deadline"
                        )
                    break
                time.sleep(2)
            log("checker_reconcile_complete", service_count=6)
        elif options.command == "register":
            register_services(runtime, AnvilClient())
            log("checker_registration_complete", service_count=6)
        elif options.command == "status":
            print(
                json.dumps(runtime.status(True), sort_keys=True, separators=(",", ":"))
            )
        elif options.command == "serve":
            serve(runtime)
        elif options.command == "stop":
            runtime.stop()
            log("checker_runtime_stopped", service_count=6)
    except RuntimeErrorSafe as error:
        log("checker_runtime_failed", reason=str(error))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
