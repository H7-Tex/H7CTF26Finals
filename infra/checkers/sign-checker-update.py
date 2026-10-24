#!/usr/bin/env python3
import fcntl
import hashlib
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

SLUG = "sign-me-in"
CANDIDATE = Path("/var/lib/finals-sign-update/candidate/checker")
ROLLBACK = Path("/var/lib/finals-sign-update/rollback/checker")
CURRENT_MANIFEST = Path("/etc/finals-platform/checkers/artifact-manifest.json")
CURRENT_ROOT = Path("/opt/finals-checkers")
CURRENT_ARCHIVE = CURRENT_ROOT / SLUG / "checker-image.tar"
RUNTIME = Path("/usr/local/libexec/checker-runtime/runtime.py")
DATA = Path("/var/lib/checker-runtime/data/sign-me-in/mongo")
LOCK = Path("/run/finals-sign-checker-update.lock")
STOP_OVERRIDE = Path(
    "/run/systemd/system/checker-runtime.service.d/finals-sign-update.conf"
)
MANIFEST_FIELDS = {
    "schema_version",
    "slug",
    "source_commit",
    "expected_manifest_sha256",
    "replacement_manifest_sha256",
    "expected_artifact",
    "replacement_artifact",
}
ARTIFACT_FIELDS = {"path", "sha256", "size", "executable", "image", "image_id"}


class UpdateError(Exception):
    pass


def digest_file(path):
    value = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def digest(value):
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def image_id(value):
    return isinstance(value, str) and value.startswith("sha256:") and digest(value[7:])


def commit(value):
    return (
        isinstance(value, str)
        and len(value) == 40
        and all(character in "0123456789abcdef" for character in value)
    )


def read_json(path, maximum=1024 * 1024):
    metadata = path.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or path.is_symlink()
        or metadata.st_size > maximum
    ):
        raise UpdateError(f"unsafe JSON file: {path.name}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise UpdateError(f"invalid JSON file: {path.name}") from error


def atomic_copy(path, source, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            with source.open("rb") as input_file:
                shutil.copyfileobj(input_file, output, 1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def atomic_text(path, value, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(value)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def secure_root_directory(path):
    metadata = path.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or path.is_symlink()
        or metadata.st_uid != 0
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise UpdateError(f"unsafe candidate directory: {path.name}")


def secure_root_file(path):
    metadata = path.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or path.is_symlink()
        or metadata.st_uid != 0
        or stat.S_IMODE(metadata.st_mode) != 0o600
    ):
        raise UpdateError(f"unsafe candidate file: {path.name}")


def artifact_record(value):
    return (
        isinstance(value, dict)
        and set(value) == ARTIFACT_FIELDS
        and value["path"] == "sign-me-in/checker-image.tar"
        and digest(value["sha256"])
        and type(value["size"]) is int
        and 1 <= value["size"] <= 2 * 1024 * 1024 * 1024
        and value["executable"] is False
        and isinstance(value["image"], str)
        and value["image"].startswith("finals/checkers/sign-me-in:")
        and not value["image"].endswith(":latest")
        and image_id(value["image_id"])
    )


def verify_image_archive(archive, reference):
    try:
        with tarfile.open(archive, "r") as source:
            members = source.getmembers()
            if len({member.name for member in members}) != len(members):
                raise UpdateError("checker image archive contains duplicate members")
            member = source.getmember("manifest.json")
            if not member.isfile() or member.size > 1024 * 1024:
                raise UpdateError("checker image archive manifest is unsafe")
            manifest = source.extractfile(member)
            if manifest is None:
                raise UpdateError("checker image archive manifest is unreadable")
            records = json.load(manifest)
    except (KeyError, TypeError, json.JSONDecodeError, tarfile.TarError) as error:
        raise UpdateError("checker image archive is invalid") from error
    if (
        not isinstance(records, list)
        or len(records) != 1
        or records[0].get("RepoTags") != [reference]
    ):
        raise UpdateError("checker image archive does not contain only the replacement")


def sign_service(document):
    services = document.get("services") if isinstance(document, dict) else None
    matches = [
        entry
        for entry in services or []
        if isinstance(entry, dict) and entry.get("slug") == SLUG
    ]
    if len(matches) != 1:
        raise UpdateError("checker manifest Sign entry is missing or duplicated")
    return matches[0]


def validate_manifest_delta(current, replacement):
    if not isinstance(current, dict) or not isinstance(replacement, dict):
        raise UpdateError("checker manifest is invalid")
    if set(current) != {"version", "database_image", "services"} or set(
        replacement
    ) != set(current):
        raise UpdateError("checker manifest schema changed")
    if (
        current["version"] != replacement["version"]
        or current["database_image"] != replacement["database_image"]
    ):
        raise UpdateError("checker runtime contract changed")
    current_services = current["services"]
    replacement_services = replacement["services"]
    if (
        not isinstance(current_services, list)
        or not isinstance(replacement_services, list)
        or len(current_services) != 6
        or len(replacement_services) != 6
    ):
        raise UpdateError("checker service inventory changed")
    for before, after in zip(current_services, replacement_services):
        if not isinstance(before, dict) or not isinstance(after, dict):
            raise UpdateError("checker service inventory is invalid")
        if before.get("slug") != after.get("slug"):
            raise UpdateError("checker service order changed")
        if before.get("slug") != SLUG:
            if before != after:
                raise UpdateError(
                    f"checker manifest changed unrelated service {before.get('slug')}"
                )
            continue
        before_public = {
            key: value for key, value in before.items() if key != "artifact"
        }
        after_public = {key: value for key, value in after.items() if key != "artifact"}
        if (
            before_public != after_public
            or not artifact_record(before.get("artifact"))
            or not artifact_record(after.get("artifact"))
            or before["artifact"] == after["artifact"]
        ):
            raise UpdateError("checker manifest changed the locked Sign contract")
    return sign_service(current)["artifact"], sign_service(replacement)["artifact"]


def load_update(root=CANDIDATE, require_root=True):
    if require_root:
        secure_root_directory(root)
        secure_root_directory(root / SLUG)
        secure_root_file(root / "update.json")
        secure_root_file(root / "artifact-manifest.json")
    update = read_json(root / "update.json")
    if (
        not isinstance(update, dict)
        or set(update) != MANIFEST_FIELDS
        or update["schema_version"] != 1
        or update["slug"] != SLUG
        or not commit(update["source_commit"])
        or not digest(update["expected_manifest_sha256"])
        or not digest(update["replacement_manifest_sha256"])
        or not artifact_record(update["expected_artifact"])
        or not artifact_record(update["replacement_artifact"])
    ):
        raise UpdateError("checker update manifest is invalid")
    if (
        update["replacement_artifact"]["image"]
        != f"finals/checkers/{SLUG}:{update['source_commit']}"
    ):
        raise UpdateError(
            "replacement checker reference does not match the source commit"
        )
    replacement_manifest = read_json(root / "artifact-manifest.json")
    if (
        digest_file(root / "artifact-manifest.json")
        != update["replacement_manifest_sha256"]
    ):
        raise UpdateError("replacement checker manifest digest mismatch")
    current_manifest = read_json(CURRENT_MANIFEST)
    if digest_file(CURRENT_MANIFEST) != update["expected_manifest_sha256"]:
        raise UpdateError(
            "current checker manifest does not match the CAS precondition"
        )
    before, after = validate_manifest_delta(current_manifest, replacement_manifest)
    if before != update["expected_artifact"] or after != update["replacement_artifact"]:
        raise UpdateError("checker update artifact records do not match the manifests")
    archive = root / "sign-me-in" / "checker-image.tar"
    metadata = archive.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or archive.is_symlink()
        or metadata.st_size != after["size"]
        or digest_file(archive) != after["sha256"]
        or (
            require_root
            and (metadata.st_uid != 0 or stat.S_IMODE(metadata.st_mode) != 0o600)
        )
    ):
        raise UpdateError("replacement checker archive verification failed")
    verify_image_archive(archive, after["image"])
    try:
        specification = importlib.util.spec_from_file_location(
            "finals_checker_runtime", RUNTIME
        )
        runtime = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(runtime)
        runtime.load_manifest(CURRENT_MANIFEST, CURRENT_ROOT, True, require_root)
        runtime.validate_manifest(replacement_manifest, CURRENT_ROOT, False, False)
    except Exception as error:
        raise UpdateError("checker runtime rejected the manifest contract") from error
    return update, current_manifest, replacement_manifest


def run(arguments, **kwargs):
    try:
        return subprocess.run(arguments, check=True, **kwargs)
    except (OSError, subprocess.SubprocessError) as error:
        raise UpdateError(f"command failed: {arguments[0]}") from error


def ready(manifest):
    for _ in range(30):
        try:
            with urllib.request.urlopen(
                "http://127.0.0.1:9160/readyz", timeout=3
            ) as response:
                if response.status == 200:
                    verify_runtime_images(manifest)
                    return
        except (OSError, UpdateError):
            pass
        time.sleep(1)
    raise UpdateError("checker runtime did not become ready")


def install_candidate(update):
    atomic_copy(CURRENT_ARCHIVE, CANDIDATE / "sign-me-in" / "checker-image.tar")
    atomic_copy(CURRENT_MANIFEST, CANDIDATE / "artifact-manifest.json")
    if (
        digest_file(CURRENT_ARCHIVE) != update["replacement_artifact"]["sha256"]
        or digest_file(CURRENT_MANIFEST) != update["replacement_manifest_sha256"]
    ):
        raise UpdateError("installed checker candidate failed read-back")


def save_rollback(update):
    if ROLLBACK.exists():
        raise UpdateError("checker rollback state already exists")
    ROLLBACK.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    staging = Path(tempfile.mkdtemp(prefix=".checker-rollback.", dir=ROLLBACK.parent))
    try:
        shutil.copy2(CURRENT_MANIFEST, staging / "artifact-manifest.json")
        service = staging / SLUG
        service.mkdir(mode=0o700)
        shutil.copy2(CURRENT_ARCHIVE, service / "checker-image.tar")
        (staging / "update.json").write_text(
            json.dumps(update, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        for path in (
            staging / "artifact-manifest.json",
            service / "checker-image.tar",
            staging / "update.json",
        ):
            path.chmod(0o600)
        staging.chmod(0o700)
        os.replace(staging, ROLLBACK)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def runtime_reload(manifest):
    run([str(RUNTIME), "validate-artifacts"])
    restart_supervisor(manifest)


def restart_supervisor(manifest):
    if STOP_OVERRIDE.exists():
        raise UpdateError("checker runtime stop override already exists")
    atomic_text(STOP_OVERRIDE, "[Service]\nExecStop=\n")
    try:
        run(["systemctl", "daemon-reload"])
        run(["systemctl", "restart", "checker-runtime.service"])
        ready(manifest)
    finally:
        STOP_OVERRIDE.unlink(missing_ok=True)
        try:
            STOP_OVERRIDE.parent.rmdir()
        except OSError:
            pass
        run(["systemctl", "daemon-reload"])


def verify_runtime_images(manifest):
    for service in manifest["services"]:
        artifact = service["artifact"]
        image = run(
            ["docker", "image", "inspect", "--format", "{{.Id}}", artifact["image"]],
            capture_output=True,
            text=True,
        ).stdout.strip()
        container = run(
            [
                "docker",
                "inspect",
                "--format",
                "{{.Image}} {{.State.Running}}",
                f"checker-{service['slug']}",
            ],
            capture_output=True,
            text=True,
        ).stdout.strip()
        if image != artifact["image_id"] or container != f"{artifact['image_id']} true":
            raise UpdateError(f"checker image read-back failed: {service['slug']}")


def runtime_inventory():
    inventory = {}
    for service in (
        "sign-me-in",
        "can-we-settle-this",
        "update-pending",
        "book-me-if-you-can",
        "ship-it",
        "terms-may-apply",
    ):
        for prefix in ("checker", "checker-db"):
            name = f"{prefix}-{service}"
            result = run(
                [
                    "docker",
                    "inspect",
                    "--format",
                    "{{.Id}} {{.Image}} {{.State.Running}}",
                    name,
                ],
                capture_output=True,
                text=True,
            ).stdout.strip()
            if not result.endswith(" true"):
                raise UpdateError(f"checker runtime component is not running: {name}")
            inventory[name] = result
    return inventory


def verify_only_sign_changed(before, after):
    if set(before) != set(after):
        raise UpdateError("checker runtime container inventory changed")
    for name in before:
        if name == "checker-sign-me-in":
            continue
        if before[name] != after[name]:
            raise UpdateError(f"unrelated checker runtime component changed: {name}")


def data_identity():
    result = {}
    for directory in sorted((DATA.parent.parent).glob("*/mongo")):
        if directory.is_symlink() or not directory.is_dir():
            raise UpdateError("checker database path is unsafe")
        result[directory.parent.name] = (
            directory.stat().st_dev,
            directory.stat().st_ino,
        )
    if len(result) != 6 or SLUG not in result:
        raise UpdateError("checker database inventory is incomplete")
    return result


def restore_rollback(allowed_manifests, stable_inventory):
    if digest_file(CURRENT_MANIFEST) not in allowed_manifests:
        raise UpdateError(
            "current checker manifest changed after candidate application"
        )
    atomic_copy(CURRENT_ARCHIVE, ROLLBACK / SLUG / "checker-image.tar")
    atomic_copy(CURRENT_MANIFEST, ROLLBACK / "artifact-manifest.json")
    runtime_reload(read_json(CURRENT_MANIFEST))
    verify_only_sign_changed(stable_inventory, runtime_inventory())


def apply_update(dry_run=False):
    if (
        os.geteuid() != 0
        or not RUNTIME.is_file()
        or not DATA.is_dir()
        or DATA.is_symlink()
    ):
        raise UpdateError("checker runtime state is incomplete")
    update, current, replacement = load_update()
    if (
        subprocess.run(
            ["systemctl", "is-active", "--quiet", "checker-runtime.service"],
            check=False,
        ).returncode
        != 0
    ):
        raise UpdateError("checker runtime is not active")
    identities = data_identity()
    verify_runtime_images(current)
    inventory = runtime_inventory()
    if dry_run:
        print("sign-checker-update=dry-run-green")
        return
    save_rollback(update)
    try:
        install_candidate(update)
        runtime_reload(replacement)
        verify_runtime_images(replacement)
        after = runtime_inventory()
        verify_only_sign_changed(inventory, after)
        if inventory["checker-sign-me-in"] == after["checker-sign-me-in"]:
            raise UpdateError("Sign checker container was not replaced")
        if data_identity() != identities:
            raise UpdateError("checker databases changed during update")
        print(
            f"sign-checker-update=applied image={update['replacement_artifact']['image_id']}"
        )
    except Exception:
        restore_rollback(
            {
                update["expected_manifest_sha256"],
                update["replacement_manifest_sha256"],
            },
            inventory,
        )
        raise


def rollback_update():
    if os.geteuid() != 0 or not ROLLBACK.is_dir():
        raise UpdateError("checker rollback state is unavailable")
    update = read_json(ROLLBACK / "update.json")
    identities = data_identity()
    inventory = runtime_inventory()
    restore_rollback({update["replacement_manifest_sha256"]}, inventory)
    previous = read_json(CURRENT_MANIFEST)
    verify_runtime_images(previous)
    if data_identity() != identities:
        raise UpdateError("checker databases changed during rollback")
    print(
        f"sign-checker-update=rolled-back image={update['expected_artifact']['image_id']}"
    )


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in {"apply", "dry-run", "rollback"}:
        print("usage: sign-checker-update.py {dry-run|apply|rollback}", file=sys.stderr)
        return 2
    try:
        LOCK.parent.mkdir(parents=True, exist_ok=True)
        with LOCK.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if sys.argv[1] == "rollback":
                rollback_update()
            else:
                apply_update(sys.argv[1] == "dry-run")
    except (UpdateError, OSError, KeyError, json.JSONDecodeError) as error:
        print(f"Sign checker update refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
