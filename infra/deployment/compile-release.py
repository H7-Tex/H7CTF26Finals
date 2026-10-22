#!/usr/bin/env python3
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path, PurePosixPath


COMMAND_DIRECTORY = "/usr/local/libexec/deployment-executor/commands"
COMMANDS = {name: f"{COMMAND_DIRECTORY}/{name}" for name in ("build", "gate", "promote", "rollback", "health")}
SERVICE_KEYS = {
    "slot", "slug", "protocol", "port", "base_commit", "bundle_sha256", "factory_image",
    "private_gate_artifact", "build", "runtime", "quota", "generations", "backends", "timeouts",
    "previous_flag_ticks",
}
BUILD_KEYS = {"context", "dockerfile", "base_images", "allowed_paths", "maximum_context_bytes"}
RUNTIME_KEYS = {
    "uid", "container_data_path", "environment", "health_command", "read_only", "no_new_privileges",
    "drop_all_capabilities", "outbound_network", "tmpfs_bytes", "memory_bytes", "cpu_millis", "pids",
}
GENERATION_KEYS = {"path", "project_name", "project_id"}
TIMEOUT_KEYS = {"build_seconds", "gate_seconds", "deploy_seconds", "health_seconds"}
TEAM_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
IMAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*@sha256:[0-9a-f]{64}$")
ENVIRONMENT = re.compile(r"^[A-Z][A-Z0-9_]*$")


class ReleaseError(Exception):
    pass


def exact(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ReleaseError(f"{label} must contain exactly {', '.join(sorted(keys))}")


def positive_integer(value, minimum, maximum, label):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ReleaseError(f"{label} is outside its fixed bounds")


def relative_path(value, label, directory=False):
    if not isinstance(value, str) or not value or "\\" in value or value.startswith("/"):
        raise ReleaseError(f"{label} must be a relative POSIX path")
    candidate = value[:-1] if directory and value.endswith("/") else value
    normalized = str(PurePosixPath(candidate))
    if normalized in (".", "..") or normalized != candidate or normalized.startswith("../"):
        raise ReleaseError(f"{label} is not normalized")


def duplicate_safe_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ReleaseError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def read_document(path, label):
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > 1024 * 1024:
            raise ReleaseError(f"{label} must be a regular file no larger than 1 MiB")
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=duplicate_safe_object)
    except ReleaseError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ReleaseError(f"cannot read {label}: {error}") from error


def immutable_image(value, label):
    if not isinstance(value, str) or not IMAGE.fullmatch(value):
        raise ReleaseError(f"{label} must be an immutable sha256 image reference")


def validate_release(release):
    exact(release, {"schema_version", "policy_version", "services"}, "release")
    if release["schema_version"] != 1 or not isinstance(release["policy_version"], str) or not SLUG.fullmatch(release["policy_version"]):
        raise ReleaseError("release identity is invalid")
    services = release["services"]
    if not isinstance(services, list) or len(services) != 6:
        raise ReleaseError("release must contain exactly six services")
    seen = {"slot": set(), "slug": set(), "port": set(), "uid": set(), "project_id": set(), "backend": set()}
    quota_bytes = 0
    quota_inodes = 0
    for service in services:
        exact(service, SERVICE_KEYS, "service")
        slot, slug, protocol, port = service["slot"], service["slug"], service["protocol"], service["port"]
        if not isinstance(slot, str) or not re.fullmatch(r"AD[1-6]", slot):
            raise ReleaseError("service slot is invalid")
        if not isinstance(slug, str) or not SLUG.fullmatch(slug):
            raise ReleaseError("service slug is invalid")
        if protocol not in ("http", "tcp"):
            raise ReleaseError(f"service {slug} has an invalid protocol")
        positive_integer(port, 7001, 7006, f"service {slug} port")
        for name, value in (("slot", slot), ("slug", slug), ("port", port)):
            if value in seen[name]:
                raise ReleaseError(f"duplicate service {name} {value}")
            seen[name].add(value)
        if not isinstance(service["base_commit"], str) or not COMMIT.fullmatch(service["base_commit"]):
            raise ReleaseError(f"service {slug} has no final base commit")
        if not isinstance(service["bundle_sha256"], str) or not DIGEST.fullmatch(service["bundle_sha256"]):
            raise ReleaseError(f"service {slug} has no final player bundle digest")
        immutable_image(service["factory_image"], f"service {slug} factory image")
        immutable_image(service["private_gate_artifact"], f"service {slug} private gate artifact")

        build = service["build"]
        exact(build, BUILD_KEYS, f"service {slug} build")
        relative_path(build["context"], f"service {slug} build context")
        relative_path(build["dockerfile"], f"service {slug} Dockerfile")
        if not build["dockerfile"].startswith(build["context"] + "/"):
            raise ReleaseError(f"service {slug} Dockerfile is outside its build context")
        if not isinstance(build["base_images"], list) or not 1 <= len(build["base_images"]) <= 8:
            raise ReleaseError(f"service {slug} must pin its base images")
        for image in build["base_images"]:
            immutable_image(image, f"service {slug} base image")
        if len(set(build["base_images"])) != len(build["base_images"]):
            raise ReleaseError(f"service {slug} repeats a base image")
        if not isinstance(build["allowed_paths"], list) or not build["allowed_paths"]:
            raise ReleaseError(f"service {slug} has no patchable paths")
        for path in build["allowed_paths"]:
            relative_path(path, f"service {slug} patchable path", directory=True)
            if not path.startswith(build["context"] + "/"):
                raise ReleaseError(f"service {slug} patchable path is outside its build context")
        positive_integer(build["maximum_context_bytes"], 1024, 100 * 1024 * 1024, f"service {slug} build context")

        runtime = service["runtime"]
        exact(runtime, RUNTIME_KEYS, f"service {slug} runtime")
        positive_integer(runtime["uid"], 10000, 65535, f"service {slug} runtime UID")
        if runtime["uid"] in seen["uid"]:
            raise ReleaseError(f"service {slug} repeats a runtime UID")
        seen["uid"].add(runtime["uid"])
        if runtime["container_data_path"] != "/data":
            raise ReleaseError(f"service {slug} must use the fixed /data bind")
        environment = runtime["environment"]
        if not isinstance(environment, dict) or len(environment) > 16:
            raise ReleaseError(f"service {slug} environment is invalid")
        for name, value in environment.items():
            if not isinstance(name, str) or not ENVIRONMENT.fullmatch(name) or not isinstance(value, str) or len(value) > 256:
                raise ReleaseError(f"service {slug} environment is invalid")
        health = runtime["health_command"]
        if not isinstance(health, list) or not 1 <= len(health) <= 16 or not all(isinstance(value, str) and value and len(value) <= 512 for value in health):
            raise ReleaseError(f"service {slug} health command is invalid")
        if any(runtime[name] is not True for name in ("read_only", "no_new_privileges", "drop_all_capabilities")) or runtime["outbound_network"] is not False:
            raise ReleaseError(f"service {slug} weakens the fixed runtime isolation")
        positive_integer(runtime["tmpfs_bytes"], 1024 * 1024, 64 * 1024 * 1024, f"service {slug} tmpfs")
        positive_integer(runtime["memory_bytes"], 64 * 1024 * 1024, 8 * 1024 * 1024 * 1024, f"service {slug} memory")
        positive_integer(runtime["cpu_millis"], 100, 4000, f"service {slug} CPU")
        positive_integer(runtime["pids"], 16, 1024, f"service {slug} PID limit")

        quota = service["quota"]
        exact(quota, {"bytes", "inodes"}, f"service {slug} quota")
        positive_integer(quota["bytes"], 64 * 1024 * 1024, 4 * 1024 * 1024 * 1024, f"service {slug} quota bytes")
        positive_integer(quota["inodes"], 1024, 262144, f"service {slug} quota inodes")
        quota_bytes += quota["bytes"] * 3
        quota_inodes += quota["inodes"] * 3
        generations = service["generations"]
        exact(generations, {"live", "gate", "recovery"}, f"service {slug} generations")
        generation_offsets = {"live": 0, "gate": 10000, "recovery": 20000}
        for name, offset in generation_offsets.items():
            generation = generations[name]
            exact(generation, GENERATION_KEYS, f"service {slug} {name} generation")
            expected = {
                "path": f"/srv/finals/service-data/{port}/{name}",
                "project_name": f"finals-{port}-{name}",
                "project_id": port + offset,
            }
            if generation != expected:
                raise ReleaseError(f"service {slug} {name} generation is not fixed")
            if generation["project_id"] in seen["project_id"]:
                raise ReleaseError(f"service {slug} repeats a project ID")
            seen["project_id"].add(generation["project_id"])

        backends = service["backends"]
        exact(backends, {"live_a_port", "live_b_port", "gate_port"}, f"service {slug} backends")
        expected_backends = {"live_a_port": port + 10000, "live_b_port": port + 11000, "gate_port": port + 12000}
        if backends != expected_backends:
            raise ReleaseError(f"service {slug} backend ports are not fixed")
        for backend in backends.values():
            if backend in seen["backend"]:
                raise ReleaseError(f"service {slug} repeats a backend port")
            seen["backend"].add(backend)

        timeouts = service["timeouts"]
        exact(timeouts, TIMEOUT_KEYS, f"service {slug} timeouts")
        for name, seconds in timeouts.items():
            positive_integer(seconds, 1, 600, f"service {slug} {name}")
        if service["previous_flag_ticks"] != 5:
            raise ReleaseError(f"service {slug} must retain five previous flag ticks")
    if seen["slot"] != {f"AD{number}" for number in range(1, 7)} or seen["port"] != set(range(7001, 7007)):
        raise ReleaseError("release service slots and ports are incomplete")
    if quota_bytes > 32 * 1024 * 1024 * 1024 or quota_inodes > 2_000_000:
        raise ReleaseError("release generation quotas exceed the production volume reserve")


def validate_team(team):
    exact(team, {"schema_version", "team_id", "team_number", "allowed_uid", "repository_path"}, "team")
    if team["schema_version"] != 1 or not isinstance(team["team_id"], str) or not TEAM_ID.fullmatch(team["team_id"]):
        raise ReleaseError("team identity is invalid")
    positive_integer(team["team_number"], 1, 15, "team number")
    positive_integer(team["allowed_uid"], 1, 2 ** 32 - 1, "allowed UID")
    if team["repository_path"] != "/var/lib/deployment-orchestrator/repository":
        raise ReleaseError("team repository path is not fixed")


def executor_service(service):
    runtime, build, quota = service["runtime"], service["build"], service["quota"]
    return {
        "base_commit": service["base_commit"],
        "bundle_sha256": service["bundle_sha256"],
        "factory_digest": service["factory_image"].rsplit("@", 1)[1],
        "factory_image": service["factory_image"],
        "private_gate_artifact": service["private_gate_artifact"],
        "protocol": service["protocol"],
        "port": service["port"],
        "build": build,
        "runtime": runtime,
        "quota": quota,
        "generations": service["generations"],
        "backends": service["backends"],
        "resources": {
            "network_mode": "none",
            "maximum_context_bytes": build["maximum_context_bytes"],
            "memory_bytes": runtime["memory_bytes"],
            "cpu_millis": runtime["cpu_millis"],
            "pids": runtime["pids"],
            "timeout_seconds": 0,
        },
        "build_timeout_seconds": service["timeouts"]["build_seconds"],
        "gate_timeout_seconds": service["timeouts"]["gate_seconds"],
        "deploy_timeout_seconds": service["timeouts"]["deploy_seconds"],
        "health_timeout_seconds": service["timeouts"]["health_seconds"],
        "previous_flag_ticks": service["previous_flag_ticks"],
    }


def compile_documents(release, team):
    services = sorted(release["services"], key=lambda value: value["slug"])
    services_document = {
        "schema_version": 1,
        "policy_version": release["policy_version"],
        "services": [{
            "slug": service["slug"],
            "base_commit": service["base_commit"],
            "bundle_sha256": service["bundle_sha256"],
            "factory_digest": service["factory_image"].rsplit("@", 1)[1],
            "allowed_paths": service["build"]["allowed_paths"],
            "maximum_context_bytes": service["build"]["maximum_context_bytes"],
            "memory_bytes": service["runtime"]["memory_bytes"],
            "cpu_millis": service["runtime"]["cpu_millis"],
            "pids": service["runtime"]["pids"],
            "build_timeout": f"{service['timeouts']['build_seconds']}s",
            "gate_timeout": f"{service['timeouts']['gate_seconds']}s",
            "promotion_timeout": f"{service['timeouts']['deploy_seconds']}s",
            "health_timeout": f"{service['timeouts']['health_seconds']}s",
            "previous_flag_ticks": service["previous_flag_ticks"],
        } for service in services],
    }
    executor_policy = {
        "schema_version": 2,
        "allowed_uid": team["allowed_uid"],
        "team_id": team["team_id"],
        "team_number": team["team_number"],
        "repository_path": team["repository_path"],
        "policy_version": release["policy_version"],
        "live_address": f"10.60.{team['team_number']}.2",
        "staging_address": f"10.60.{team['team_number']}.3",
        "proxy_socket": "/run/finals-service-proxy/control.sock",
        "commands": COMMANDS,
        "services": {service["slug"]: executor_service(service) for service in services},
    }
    volume_policy = {
        "schema_version": 1,
        "mount": "/srv/finals/service-data",
        "services": [{
            "slug": service["slug"],
            "port": service["port"],
            "uid": service["runtime"]["uid"],
            "quota": service["quota"],
            "generations": service["generations"],
        } for service in services],
    }
    return services_document, executor_policy, volume_policy, render_haproxy(services, team["team_number"])


def render_haproxy(services, team_number):
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
    for service in services:
        slug, port, backends = service["slug"], service["port"], service["backends"]
        name = slug.replace("-", "_")
        lines.extend([
            f"frontend live_{name}",
            "  mode tcp",
            f"  bind 10.60.{team_number}.2:{port}",
            f"  default_backend live_{name}",
            "",
            f"backend live_{name}",
            "  mode tcp",
            f"  server slot_a 127.0.0.1:{backends['live_a_port']} check disabled",
            f"  server slot_b 127.0.0.1:{backends['live_b_port']} check disabled",
            "",
            f"frontend staging_{name}",
            "  mode tcp",
            f"  bind 10.60.{team_number}.3:{port}",
            f"  default_backend staging_{name}",
            "",
            f"backend staging_{name}",
            "  mode tcp",
            f"  server gate 127.0.0.1:{backends['gate_port']} check disabled",
            "",
        ])
    return "\n".join(lines)


def atomic_write(path, content, mode):
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def write_outputs(output, documents):
    if output.exists() and (output.is_symlink() or not output.is_dir()):
        raise ReleaseError("output must be a real directory")
    if output.exists() and any(output.iterdir()):
        raise ReleaseError("output directory must be empty")
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(output, 0o700)
    names = ("services.json", "executor-policy.json", "volume-policy.json")
    for name, document in zip(names, documents[:3]):
        atomic_write(output / name, json.dumps(document, indent=2, sort_keys=True) + "\n", 0o600)
    atomic_write(output / "haproxy.cfg", documents[3], 0o600)


def main():
    if len(sys.argv) != 4:
        print(f"usage: {Path(sys.argv[0]).name} RELEASE TEAM OUTPUT", file=sys.stderr)
        return 2
    try:
        release = read_document(Path(sys.argv[1]), "release manifest")
        team = read_document(Path(sys.argv[2]), "team manifest")
        validate_release(release)
        validate_team(team)
        write_outputs(Path(sys.argv[3]), compile_documents(release, team))
    except ReleaseError as error:
        print(f"release compilation refused: {error}", file=sys.stderr)
        return 1
    print("compiled release policy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
