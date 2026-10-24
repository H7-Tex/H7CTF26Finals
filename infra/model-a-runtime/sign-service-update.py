#!/usr/bin/env python3
import fcntl
import hashlib
import json
import os
import pwd
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

SLUG = "sign-me-in"
CANDIDATE = Path("/var/lib/finals-sign-update/candidate/service")
ROLLBACK = Path("/var/lib/finals-sign-update/rollback/service")
STATE_ROOT = Path("/var/lib/finals-model-a")
WORKSPACE = Path("/opt/finals/services/sign-me-in")
FACTORY = STATE_ROOT / "factory" / SLUG
ACTIVE = STATE_ROOT / "active" / SLUG
RELEASE = STATE_ROOT / "release.json"
DATA = Path("/srv/finals/service-data/7001/live")
LOCK = Path("/run/finals-sign-service-update.lock")
MANIFEST_FIELDS = {
    "schema_version",
    "slug",
    "source_commit",
    "expected",
    "replacement",
    "artifacts",
}
RECORD_FIELDS = {"factory_reference", "factory_image_id", "bundle_sha256"}
ARTIFACT_FIELDS = {"path", "sha256", "bytes"}


class UpdateError(Exception):
    pass


def digest_file(path):
    value = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


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


def atomic_json(path, document, mode=0o600):
    atomic_text(path, json.dumps(document, indent=2, sort_keys=True) + "\n", mode)


def regular_root_file(path, expected_size, expected_digest):
    metadata = path.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or path.is_symlink()
        or metadata.st_uid != 0
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_size != expected_size
        or digest_file(path) != expected_digest
    ):
        raise UpdateError(f"artifact verification failed: {path.name}")


def secure_root_directory(path):
    metadata = path.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or path.is_symlink()
        or metadata.st_uid != 0
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise UpdateError(f"unsafe candidate directory: {path.name}")


def image_id(value):
    return (
        isinstance(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def digest(value):
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def commit(value):
    return (
        isinstance(value, str)
        and len(value) == 40
        and all(character in "0123456789abcdef" for character in value)
    )


def validate_record(value):
    return (
        isinstance(value, dict)
        and set(value) == RECORD_FIELDS
        and isinstance(value["factory_reference"], str)
        and value["factory_reference"].startswith("finals/model-a/sign-me-in:")
        and not value["factory_reference"].endswith(":latest")
        and image_id(value["factory_image_id"])
        and digest(value["bundle_sha256"])
    )


def load_update(root=CANDIDATE, require_root=True):
    if require_root:
        secure_root_directory(root)
        regular_root_file(
            root / "update.json",
            (root / "update.json").stat().st_size,
            digest_file(root / "update.json"),
        )
    document = read_json(root / "update.json")
    if (
        not isinstance(document, dict)
        or set(document) != MANIFEST_FIELDS
        or document["schema_version"] != 1
        or document["slug"] != SLUG
        or not commit(document["source_commit"])
        or not validate_record(document["expected"])
        or not validate_record(document["replacement"])
        or document["expected"] == document["replacement"]
    ):
        raise UpdateError("service update manifest is invalid")
    if (
        document["replacement"]["factory_reference"]
        != f"finals/model-a/{SLUG}:{document['source_commit']}"
    ):
        raise UpdateError(
            "replacement service reference does not match the source commit"
        )
    artifacts = document["artifacts"]
    if not isinstance(artifacts, dict) or set(artifacts) != {"image", "bundle"}:
        raise UpdateError("service artifact inventory is invalid")
    expected_paths = {"image": "service-image.tar", "bundle": "player-bundle.tar"}
    for name, expected_path in expected_paths.items():
        record = artifacts[name]
        if (
            not isinstance(record, dict)
            or set(record) != ARTIFACT_FIELDS
            or record["path"] != expected_path
            or not digest(record["sha256"])
            or type(record["bytes"]) is not int
            or record["bytes"] < 1
            or record["bytes"] > 2 * 1024 * 1024 * 1024
        ):
            raise UpdateError(f"service {name} artifact record is invalid")
        path = root / expected_path
        if require_root:
            regular_root_file(path, record["bytes"], record["sha256"])
        elif (
            path.stat().st_size != record["bytes"]
            or digest_file(path) != record["sha256"]
        ):
            raise UpdateError(f"service {name} artifact verification failed")
    verify_image_archive(
        root / "service-image.tar", document["replacement"]["factory_reference"]
    )
    return document


def safe_extract_bundle(archive, destination):
    allowed = {"BUNDLE.json", "compose.yaml", "player", "service"}
    with tarfile.open(archive, "r") as source:
        members = source.getmembers()
        if (
            len(members) > 10000
            or sum(member.size for member in members) > 1024 * 1024 * 1024
        ):
            raise UpdateError("player bundle exceeds the extraction limit")
        if len({member.name for member in members}) != len(members):
            raise UpdateError("player bundle contains duplicate members")
        for member in members:
            relative = PurePosixPath(member.name)
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or not relative.parts
                or relative.parts[0] not in allowed
                or not (member.isdir() or member.isreg())
            ):
                raise UpdateError("player bundle contains an unsafe member")
        for member in members:
            relative = PurePosixPath(member.name)
            target = destination.joinpath(*relative.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                target.chmod(0o755)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            handle = source.extractfile(member)
            if handle is None:
                raise UpdateError("player bundle member is unreadable")
            with target.open("xb") as output:
                shutil.copyfileobj(handle, output)
            target.chmod(0o755 if member.mode & 0o111 else 0o644)
    if (
        not (destination / "service").is_dir()
        or not (destination / "BUNDLE.json").is_file()
        or not (destination / "compose.yaml").is_file()
    ):
        raise UpdateError("player bundle is incomplete")


def verify_image_archive(archive, reference):
    try:
        with tarfile.open(archive, "r") as source:
            members = source.getmembers()
            if len({member.name for member in members}) != len(members):
                raise UpdateError("service image archive contains duplicate members")
            member = source.getmember("manifest.json")
            if not member.isfile() or member.size > 1024 * 1024:
                raise UpdateError("service image archive manifest is unsafe")
            manifest = source.extractfile(member)
            if manifest is None:
                raise UpdateError("service image archive manifest is unreadable")
            records = json.load(manifest)
    except (KeyError, TypeError, json.JSONDecodeError, tarfile.TarError) as error:
        raise UpdateError("service image archive is invalid") from error
    if (
        not isinstance(records, list)
        or len(records) != 1
        or records[0].get("RepoTags") != [reference]
    ):
        raise UpdateError("service image archive does not contain only the replacement")


def release_record(document):
    services = document.get("services") if isinstance(document, dict) else None
    if not isinstance(services, list):
        raise UpdateError("installed release is invalid")
    matches = [
        record
        for record in services
        if isinstance(record, dict) and record.get("slug") == SLUG
    ]
    if len(matches) != 1:
        raise UpdateError("installed Sign release record is missing or duplicated")
    return matches[0]


def compare_record(record, expected):
    return all(record.get(name) == expected[name] for name in RECORD_FIELDS)


def run(arguments, **kwargs):
    try:
        return subprocess.run(arguments, check=True, **kwargs)
    except (OSError, subprocess.SubprocessError) as error:
        raise UpdateError(f"command failed: {arguments[0]}") from error


def docker_image(reference):
    result = run(
        ["docker", "image", "inspect", "--format", "{{.Id}}", reference],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def compose(root, image, *arguments):
    environment = dict(os.environ)
    environment["H7_IMAGE"] = image
    run(
        [
            "docker",
            "compose",
            "--project-directory",
            str(root),
            "-f",
            str(root / "compose.yaml"),
            *arguments,
        ],
        env=environment,
    )


def verify_bundle(root, expected_bundle, expected_image):
    model_root = Path("/usr/local/lib/finals-model-a")
    if model_root.is_dir():
        sys.path.insert(0, str(model_root))
    else:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from model_a import SERVICE_BY_SLUG, compose_document, verify_player_bundle
    except (ImportError, OSError) as error:
        raise UpdateError("Model A validator is unavailable") from error
    try:
        verify_player_bundle(root, SLUG)
    except Exception as error:
        raise UpdateError("player bundle validation failed") from error
    if digest_file(root / "BUNDLE.json") != expected_bundle:
        raise UpdateError("player bundle digest mismatch")
    compose = read_json(root / "compose.yaml")
    if compose != compose_document(SERVICE_BY_SLUG[SLUG], expected_image):
        raise UpdateError("player compose is not pinned to the replacement image")


def chown_workspace(root):
    account = pwd.getpwnam("ubuntu")
    root.chmod(0o755)
    for name in ("service", "player"):
        path = root / name
        if not path.exists():
            continue
        for item in (path, *path.rglob("*")):
            if item.is_symlink():
                raise UpdateError("player bundle contains a symbolic link")
            os.chown(item, account.pw_uid, account.pw_gid)
    (root / "compose.yaml").chmod(0o644)
    (root / "BUNDLE.json").chmod(0o444)


def validate_tree(root):
    for item in (root, *root.rglob("*")):
        metadata = item.lstat()
        if item.is_symlink() or not (
            stat.S_ISDIR(metadata.st_mode) or stat.S_ISREG(metadata.st_mode)
        ):
            raise UpdateError("installed Sign source tree is unsafe")


def prepare_tree(source, parent, name, factory=False):
    staged = Path(tempfile.mkdtemp(prefix=f".{name}.", dir=parent))
    shutil.rmtree(staged)
    shutil.copytree(source, staged, symlinks=True)
    validate_tree(staged)
    if factory:
        staged.chmod(0o700)
    else:
        chown_workspace(staged)
    return staged


def swap_tree(staged, destination):
    previous = destination.with_name(f".{destination.name}.previous.{os.getpid()}")
    if previous.exists():
        raise UpdateError("stale service swap path exists")
    os.replace(destination, previous)
    try:
        os.replace(staged, destination)
    except Exception:
        os.replace(previous, destination)
        raise
    shutil.rmtree(previous)


def save_rollback(update):
    if ROLLBACK.exists():
        raise UpdateError("Sign rollback state already exists")
    ROLLBACK.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    staging = Path(tempfile.mkdtemp(prefix=".service-rollback.", dir=ROLLBACK.parent))
    try:
        shutil.copytree(WORKSPACE, staging / "workspace", symlinks=True)
        shutil.copytree(FACTORY, staging / "factory", symlinks=True)
        validate_tree(staging / "workspace")
        validate_tree(staging / "factory")
        shutil.copy2(RELEASE, staging / "release.json")
        shutil.copy2(ACTIVE, staging / "active")
        atomic_json(staging / "update.json", update)
        os.chmod(staging, 0o700)
        os.replace(staging, ROLLBACK)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def container_status(expected_image):
    result = run(
        [
            "docker",
            "compose",
            "--project-directory",
            str(WORKSPACE),
            "-f",
            str(WORKSPACE / "compose.yaml"),
            "ps",
            "--quiet",
            "service",
        ],
        capture_output=True,
        text=True,
    )
    identifier = result.stdout.strip()
    if not identifier:
        raise UpdateError("Sign service container is absent")
    inspected = run(["docker", "inspect", identifier], capture_output=True, text=True)
    try:
        document = json.loads(inspected.stdout)[0]
        mounts = document["Mounts"]
        health = document["State"]["Health"]["Status"]
    except (IndexError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise UpdateError("Sign service container inspection is invalid") from error
    if document.get("Image") != expected_image or health != "healthy":
        raise UpdateError("Sign service did not reach the expected healthy image")
    matches = [
        item
        for item in mounts
        if item.get("Destination") == "/data" and item.get("Type") == "bind"
    ]
    if len(matches) != 1 or Path(matches[0].get("Source", "")) != DATA:
        raise UpdateError("Sign service durable data mount changed")


def restore_rollback(allowed_active):
    update = read_json(ROLLBACK / "update.json")
    old = update["expected"]["factory_image_id"]
    current = ACTIVE.read_text(encoding="utf-8").strip()
    if current not in allowed_active:
        raise UpdateError("active Sign image changed after candidate application")
    workspace = prepare_tree(ROLLBACK / "workspace", WORKSPACE.parent, SLUG)
    factory = prepare_tree(ROLLBACK / "factory", FACTORY.parent, SLUG, True)
    swap_tree(workspace, WORKSPACE)
    swap_tree(factory, FACTORY)
    atomic_text(RELEASE, (ROLLBACK / "release.json").read_text(encoding="utf-8"), 0o600)
    atomic_text(ACTIVE, old + "\n", 0o600)
    compose(
        WORKSPACE, old, "up", "--detach", "--wait", "--wait-timeout", "90", "service"
    )
    container_status(old)
    return old


def validate_host(update):
    if os.geteuid() != 0:
        raise UpdateError("service update requires root")
    if (
        not (STATE_ROOT / "firstboot.done").is_file()
        or not DATA.is_dir()
        or DATA.is_symlink()
    ):
        raise UpdateError("production Model A state is incomplete")
    active = ACTIVE.read_text(encoding="utf-8").strip()
    if active != update["expected"]["factory_image_id"]:
        raise UpdateError("active Sign image does not match the CAS precondition")
    release = read_json(RELEASE)
    model_root = Path("/usr/local/lib/finals-model-a")
    sys.path.insert(
        0, str(model_root if model_root.is_dir() else Path(__file__).resolve().parent)
    )
    try:
        from model_a import volume_policy_document

        volume_policy_document(release)
    except Exception as error:
        raise UpdateError("installed release manifest is invalid") from error
    if not compare_record(release_record(release), update["expected"]):
        raise UpdateError(
            "installed Sign release record does not match the CAS precondition"
        )
    if (
        WORKSPACE.is_symlink()
        or FACTORY.is_symlink()
        or not WORKSPACE.is_dir()
        or not FACTORY.is_dir()
    ):
        raise UpdateError("installed Sign source trees are unsafe")
    validate_tree(WORKSPACE)
    validate_tree(FACTORY)
    if (
        docker_image(update["expected"]["factory_reference"])
        != update["expected"]["factory_image_id"]
    ):
        raise UpdateError(
            "installed Sign factory image does not match the CAS precondition"
        )
    container_status(update["expected"]["factory_image_id"])
    return release


def apply_update(dry_run=False):
    update = load_update()
    release = validate_host(update)
    data_identity = (DATA.stat().st_dev, DATA.stat().st_ino)
    extraction = Path(tempfile.mkdtemp(prefix=".sign-candidate.", dir=WORKSPACE.parent))
    rollback_saved = False
    try:
        safe_extract_bundle(CANDIDATE / "player-bundle.tar", extraction)
        verify_bundle(
            extraction,
            update["replacement"]["bundle_sha256"],
            update["replacement"]["factory_image_id"],
        )
        if dry_run:
            print("sign-service-update=dry-run-green")
            return
        save_rollback(update)
        rollback_saved = True
        run(
            ["docker", "image", "load", "--input", str(CANDIDATE / "service-image.tar")]
        )
        if (
            docker_image(update["replacement"]["factory_reference"])
            != update["replacement"]["factory_image_id"]
        ):
            raise UpdateError(
                "loaded Sign service image ID does not match the candidate"
            )
        workspace = prepare_tree(extraction, WORKSPACE.parent, SLUG)
        factory = prepare_tree(extraction, FACTORY.parent, SLUG, True)
        swap_tree(workspace, WORKSPACE)
        swap_tree(factory, FACTORY)
        for name in RECORD_FIELDS:
            release_record(release)[name] = update["replacement"][name]
        atomic_json(RELEASE, release)
        atomic_text(ACTIVE, update["replacement"]["factory_image_id"] + "\n", 0o600)
        compose(
            WORKSPACE,
            update["replacement"]["factory_image_id"],
            "up",
            "--detach",
            "--wait",
            "--wait-timeout",
            "90",
            "service",
        )
        container_status(update["replacement"]["factory_image_id"])
        if (DATA.stat().st_dev, DATA.stat().st_ino) != data_identity:
            raise UpdateError("durable Sign data directory changed during update")
        print(
            f"sign-service-update=applied image={update['replacement']['factory_image_id']}"
        )
    except Exception:
        if rollback_saved and ACTIVE.exists():
            restore_rollback(
                {
                    update["expected"]["factory_image_id"],
                    update["replacement"]["factory_image_id"],
                }
            )
        raise
    finally:
        shutil.rmtree(extraction, ignore_errors=True)


def rollback_update():
    if os.geteuid() != 0 or not ROLLBACK.is_dir():
        raise UpdateError("Sign rollback state is unavailable")
    update = read_json(ROLLBACK / "update.json")
    data_identity = (DATA.stat().st_dev, DATA.stat().st_ino)
    old = restore_rollback({update["replacement"]["factory_image_id"]})
    if (DATA.stat().st_dev, DATA.stat().st_ino) != data_identity:
        raise UpdateError("durable Sign data directory changed during rollback")
    print(f"sign-service-update=rolled-back image={old}")


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in {"apply", "dry-run", "rollback"}:
        print("usage: sign-service-update.py {dry-run|apply|rollback}", file=sys.stderr)
        return 2
    try:
        LOCK.parent.mkdir(parents=True, exist_ok=True)
        with LOCK.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if sys.argv[1] == "rollback":
                rollback_update()
            else:
                apply_update(sys.argv[1] == "dry-run")
    except (UpdateError, OSError, KeyError, pwd.error, tarfile.TarError) as error:
        print(f"Sign service update refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
