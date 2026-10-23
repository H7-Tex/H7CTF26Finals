import hashlib
import json
import stat
import subprocess
from pathlib import PurePosixPath

SOURCE_COMMIT = "c901df95b3fad91349c66e40a631a633b92e9241"
# Team 16 is the NOP exploit-test target and runs the same six services.
MAX_TEAM_NUMBER = 16
SERVICES = (
    {
        "slug": "sign-me-in",
        "port": 7001,
        "uid": 10001,
        "subnet": "172.31.60.0/28",
        "build_context": "service",
        "environment": {"SIGN_DATA": "/data", "SIGN_PORT": "7001"},
        "tmpfs": "/tmp:size=32m,mode=1777",
        "cpus": 1,
        "memory": "768m",
        "pids": 128,
        "storage_bytes": 1073741824,
        "storage_inodes": 65536,
        "secret_name": "instance.key",
        "secret_format": "hex",
        "health": [
            "CMD",
            "python3",
            "-c",
            "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7001/healthz', timeout=2)",
        ],
        "health_retries": 10,
        "health_start": "5s",
    },
    {
        "slug": "can-we-settle-this",
        "port": 7002,
        "uid": 10002,
        "subnet": "172.31.60.16/28",
        "build_context": "service",
        "environment": {"SETTLE_DATA": "/data", "SETTLE_PORT": "7002"},
        "tmpfs": "/tmp:size=32m,mode=1777",
        "cpus": 1,
        "memory": "512m",
        "pids": 96,
        "storage_bytes": 1073741824,
        "storage_inodes": 65536,
        "secret_name": "receipt.key",
        "secret_format": "raw",
        "health": [
            "CMD",
            "python3",
            "-c",
            "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7002/healthz', timeout=2)",
        ],
        "health_retries": 10,
        "health_start": "5s",
    },
    {
        "slug": "update-pending",
        "port": 7003,
        "uid": 10003,
        "subnet": "172.31.60.32/28",
        "build_context": "service",
        "environment": {"UPDATE_DATA": "/data", "UPDATE_PORT": "7003"},
        "tmpfs": "/tmp:size=16m,mode=1777",
        "cpus": 0.75,
        "memory": "256m",
        "pids": 128,
        "storage_bytes": 536870912,
        "storage_inodes": 32768,
        "secret_name": "admin.secret",
        "secret_format": "hex",
        "health": ["CMD", "/app/gateway", "health"],
        "health_retries": 10,
        "health_start": "3s",
    },
    {
        "slug": "book-me-if-you-can",
        "port": 7004,
        "uid": 10004,
        "subnet": "172.31.60.48/28",
        "build_context": "service/app",
        "environment": {"BOOK_DATA": "/data", "BOOK_PORT": "7004"},
        "tmpfs": "/tmp:size=32m,mode=1777",
        "cpus": 0.75,
        "memory": "512m",
        "pids": 96,
        "storage_bytes": 1073741824,
        "storage_inodes": 65536,
        "secret_name": "download.key",
        "secret_format": "hex",
        "health": [
            "CMD",
            "python3",
            "-c",
            "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7004/healthz', timeout=2)",
        ],
        "health_retries": 10,
        "health_start": "5s",
    },
    {
        "slug": "ship-it",
        "port": 7005,
        "uid": 10005,
        "subnet": "172.31.60.64/28",
        "build_context": "service",
        "environment": {"SHIP_DATA": "/data", "SHIP_PORT": "7005"},
        "tmpfs": "/tmp:size=32m,mode=1777",
        "cpus": 1,
        "memory": "768m",
        "pids": 128,
        "storage_bytes": 2147483648,
        "storage_inodes": 131072,
        "secret_name": "token.key",
        "secret_format": "raw",
        "health": ["CMD", "/usr/local/bin/ship-it", "health"],
        "health_retries": 10,
        "health_start": "5s",
    },
    {
        "slug": "terms-may-apply",
        "port": 7006,
        "uid": 10006,
        "subnet": "172.31.60.80/28",
        "build_context": "service/app",
        "environment": {},
        "tmpfs": "/tmp:size=32m,mode=1777",
        "cpus": 1.25,
        "memory": "1024m",
        "pids": 128,
        "storage_bytes": 1073741824,
        "storage_inodes": 65536,
        "secret_name": "instance.key",
        "secret_format": "raw",
        "health": ["CMD", "dotnet", "TermsMayApply.dll", "--probe"],
        "health_retries": 18,
        "health_start": "10s",
    },
)
BASE_IMAGES = (
    "python@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f",
    "golang@sha256:972b4110ba0f47539a975c31e52c64765e1ff19f2d74469ae4a595c6676e80a5",
    "debian@sha256:6ebd97fa83deb272194a2cf015b3d26a4d538e9ad3a7a79d544c8af5b0a01443",
    "gcc@sha256:9ca91b05c7b07d2979f16413e8b2cd6ec8a7c80ffca4121ccab0aeba33f90460",
    "alpine@sha256:d406446bc05b82480756ce8f1287964d28768c23955fa9480d2a74a2eae7a654",
    "mcr.microsoft.com/dotnet/sdk@sha256:747cbade5bfd918a175ac32f8f1d931edec2c7d0d5397a3de72eaef1ac1f66d2",
    "mcr.microsoft.com/dotnet/aspnet@sha256:8af87eba5e7cdafb1514d7388be287365da97c132509e84dfe252ffd552398ca",
)
SERVICE_BY_SLUG = {service["slug"]: service for service in SERVICES}


class ModelAError(Exception):
    pass


def run(arguments, **kwargs):
    try:
        return subprocess.run(arguments, check=True, **kwargs)
    except (OSError, subprocess.CalledProcessError) as error:
        raise ModelAError(f"command failed: {arguments[0]}") from error


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular_file(path, maximum=None):
    try:
        info = path.lstat()
    except OSError as error:
        raise ModelAError(f"cannot inspect {path}") from error
    if not stat.S_ISREG(info.st_mode) or (
        maximum is not None and info.st_size > maximum
    ):
        raise ModelAError(f"{path} is not a bounded regular file")
    return info


def read_json(path, maximum=1024 * 1024):
    regular_file(path, maximum)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ModelAError(f"cannot read {path}") from error


def compose_document(service, image_id, data_path=None, backend_address="127.0.0.1"):
    if not image_id.startswith("sha256:") or len(image_id) != 71:
        raise ModelAError("factory image ID is invalid")
    if data_path is None:
        data_path = f"/srv/finals/service-data/{service['port']}/live"
    runtime = {
        "build": {"context": service["build_context"], "network": "none"},
        "image": "${H7_IMAGE:-" + image_id + "}",
        "pull_policy": "never",
        "environment": service["environment"],
        "volumes": [f"{data_path}:/data"],
        "read_only": True,
        "tmpfs": [service["tmpfs"]],
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "pids_limit": service["pids"],
        "cpus": service["cpus"],
        "mem_limit": service["memory"],
        "healthcheck": {
            "test": service["health"],
            "interval": "5s",
            "timeout": "3s",
            "retries": service["health_retries"],
            "start_period": service["health_start"],
        },
        "restart": "unless-stopped",
        "ports": [f"{backend_address}:{service['port'] + 10000}:{service['port']}"],
        "networks": ["target"],
    }
    return {
        "name": f"finals-model-a-{service['slug']}",
        "services": {"service": runtime},
        "networks": {
            "target": {
                "internal": True,
                "ipam": {"config": [{"subnet": service["subnet"]}]},
            }
        },
    }


def proxy_config(team_number, frontend_address=None):
    if not isinstance(team_number, int) or team_number not in range(
        1, MAX_TEAM_NUMBER + 1
    ):
        raise ModelAError("team number must be from 1 to 16")
    address = frontend_address or f"10.60.{team_number}.2"
    lines = [
        "global",
        "  user haproxy",
        "  group haproxy",
        "  maxconn 4096",
        "  stats socket /run/finals-service-proxy/control.sock user root group root mode 600 level admin",
        "",
        "defaults",
        "  mode tcp",
        "  timeout connect 3s",
        "  timeout client 30s",
        "  timeout server 30s",
        "",
    ]
    for service in SERVICES:
        name = service["slug"].replace("-", "_")
        lines.extend(
            [
                f"frontend live_{name}",
                "  mode tcp",
                f"  bind {address}:{service['port']}",
                f"  default_backend live_{name}",
                "",
                f"backend live_{name}",
                "  mode tcp",
                f"  server model_a 127.0.0.1:{service['port'] + 10000} check",
                "",
            ]
        )
    return "\n".join(lines)


def verify_player_bundle(root, slug):
    bundle = read_json(root / "BUNDLE.json")
    if (
        set(bundle) != {"schema_version", "slug", "files"}
        or bundle["schema_version"] != 1
        or bundle["slug"] != slug
    ):
        raise ModelAError(f"{slug} has an invalid BUNDLE.json")
    files = bundle["files"]
    if not isinstance(files, dict) or not files:
        raise ModelAError(f"{slug} has an empty player bundle")
    expected = set()
    for name, digest in files.items():
        relative = PurePosixPath(name)
        if (
            not isinstance(name, str)
            or relative.is_absolute()
            or ".." in relative.parts
            or relative.parts[0] not in {"service", "player"}
        ):
            raise ModelAError(f"{slug} has an unsafe player path")
        if any(
            part in {"checker", "validation", ".git", "__pycache__"}
            for part in relative.parts
        ):
            raise ModelAError(f"{slug} contains private material")
        path = root.joinpath(*relative.parts)
        regular_file(path, 100 * 1024 * 1024)
        if not isinstance(digest, str) or sha256_file(path) != digest:
            raise ModelAError(f"{slug} player file hash mismatch: {name}")
        expected.add(relative.as_posix())
    actual = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ModelAError(f"{slug} player bundle contains a symlink")
        if path.is_file() and path.name not in {"BUNDLE.json", "compose.yaml"}:
            actual.add(path.relative_to(root).as_posix())
    if actual != expected:
        raise ModelAError(f"{slug} player bundle inventory mismatch")


def write_json(path, value, mode=0o644):
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    path.chmod(mode)
