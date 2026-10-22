#!/usr/bin/env python3
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path


GIB = 1024 ** 3
ROLES = {
    "anvil": {"label": "anvil-data", "mount": "/srv/anvil", "minimum": 140 * GIB, "maximum": 160 * GIB, "filesystem": "ext4", "options": "defaults,nodev,nosuid"},
    "repository": {"label": "gitea-data", "mount": "/srv/gitea", "minimum": 90 * GIB, "maximum": 110 * GIB, "filesystem": "ext4", "options": "defaults,nodev,nosuid"},
    "mirror": {"label": "cache-data", "mount": "/srv/cache", "minimum": 290 * GIB, "maximum": 310 * GIB, "filesystem": "ext4", "options": "defaults,nodev,nosuid"},
    "captures": {"label": "captures-data", "mount": "/srv/captures", "minimum": 490 * GIB, "maximum": 510 * GIB, "filesystem": "ext4", "options": "defaults,nodev,nosuid"},
    "production": {"label": "service-data", "mount": "/srv/finals/service-data", "minimum": 40 * GIB, "maximum": 60 * GIB, "filesystem": "xfs", "options": "defaults,nodev,nosuid,prjquota"},
}

SERVICE_QUOTAS = {
    7001: {"bytes": 1024 * 1024 ** 2, "inodes": 65536},
    7002: {"bytes": 1024 * 1024 ** 2, "inodes": 65536},
    7003: {"bytes": 512 * 1024 ** 2, "inodes": 32768},
    7004: {"bytes": 1024 * 1024 ** 2, "inodes": 65536},
    7005: {"bytes": 2048 * 1024 ** 2, "inodes": 131072},
    7006: {"bytes": 1024 * 1024 ** 2, "inodes": 65536},
}


class VolumeError(Exception):
    pass


def descendants(device):
    yield device
    for child in device.get("children") or []:
        yield from descendants(child)


def root_disk(devices):
    roots = []
    for device in devices:
        if any("/" in (node.get("mountpoints") or []) for node in descendants(device)):
            roots.append(device.get("path"))
    if len(roots) != 1:
        raise VolumeError("could not identify exactly one root disk")
    return roots[0]


def select_data_disk(document, role):
    devices = document.get("blockdevices") if isinstance(document, dict) else None
    if not isinstance(devices, list):
        raise VolumeError("lsblk output is malformed")
    root = root_disk(devices)
    whole_disks = [device for device in devices if device.get("type") == "disk" and device.get("path") != root]
    if len(whole_disks) != 1:
        raise VolumeError("expected exactly one non-root whole disk")
    disk = whole_disks[0]
    size = disk.get("size")
    profile = ROLES[role]
    if not isinstance(size, int) or not profile["minimum"] <= size <= profile["maximum"]:
        raise VolumeError("data disk size is outside the fixed role range")
    if disk.get("children"):
        raise VolumeError("data disk already contains partitions")
    filesystem = disk.get("fstype")
    label = disk.get("label")
    mountpoints = [value for value in disk.get("mountpoints") or [] if value]
    if filesystem is None and label is None and not mountpoints:
        return disk["path"], "blank"
    if filesystem == profile["filesystem"] and label == profile["label"] and mountpoints in ([], [profile["mount"]]):
        return disk["path"], "initialized"
    raise VolumeError("data disk has an unexpected filesystem, label or mount")


def lsblk():
    try:
        result = subprocess.run(
            ["lsblk", "--json", "--bytes", "--output", "PATH,TYPE,SIZE,FSTYPE,LABEL,MOUNTPOINTS"],
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        raise VolumeError("cannot inspect block devices") from error


def fstab_entry(profile):
    return f"LABEL={profile['label']} {profile['mount']} {profile['filesystem']} {profile['options']} 0 2"


def ensure_fstab(profile, path=Path("/etc/fstab")):
    entry = fstab_entry(profile)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    conflicting = [line for line in lines if line and not line.lstrip().startswith("#") and profile["mount"] in line.split()]
    if conflicting and conflicting != [entry]:
        raise VolumeError("fstab contains a conflicting fixed mount")
    if conflicting:
        return
    descriptor, temporary = tempfile.mkstemp(prefix=".fstab.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            for line in lines:
                output.write(f"{line}\n")
            output.write(f"{entry}\n")
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def command(arguments):
    try:
        subprocess.run(arguments, check=True, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as error:
        raise VolumeError(f"command failed: {arguments[0]}") from error


def ensure_no_signatures(device):
    try:
        result = subprocess.run(
            ["wipefs", "--json", device],
            check=True,
            capture_output=True,
            text=True,
        )
        document = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        raise VolumeError("cannot inspect data disk signatures") from error
    if not isinstance(document, dict) or set(document) != {"signatures"}:
        raise VolumeError("wipefs output is malformed")
    signatures = document["signatures"]
    if signatures not in (None, []):
        raise VolumeError("blank data disk contains an unexpected signature")


def mount_if_needed(path, is_mount=os.path.ismount, runner=command):
    if is_mount(path):
        return False
    runner(["mount", path])
    return True


def ensure_mappings(path, desired):
    if path.is_symlink() or (path.exists() and not stat.S_ISREG(path.stat().st_mode)):
        raise VolumeError(f"{path} is not a regular mapping file")
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    existing = {}
    reverse = {}
    for line in lines:
        if not line or line.lstrip().startswith("#"):
            continue
        parts = line.split(":", 1)
        if len(parts) != 2 or not all(parts):
            raise VolumeError(f"{path} contains a malformed mapping")
        key, value = parts
        if key in existing and existing[key] != value:
            raise VolumeError(f"{path} contains a conflicting mapping")
        if value in reverse and reverse[value] != key:
            raise VolumeError(f"{path} contains a conflicting mapping")
        existing[key] = value
        reverse[value] = key
    for key, value in desired.items():
        if key in existing and existing[key] != value:
            raise VolumeError(f"{path} contains a conflicting mapping")
        if value in reverse and reverse[value] != key:
            raise VolumeError(f"{path} contains a conflicting mapping")
    missing = [(key, value) for key, value in desired.items() if key not in existing]
    if not missing:
        return
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            for line in lines:
                output.write(f"{line}\n")
            for key, value in missing:
                output.write(f"{key}:{value}\n")
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def configure_service_quotas(
    mount=Path("/srv/finals/service-data"),
    projects_path=Path("/etc/projects"),
    projid_path=Path("/etc/projid"),
    runner=command,
):
    project_paths = {}
    project_ids = {}
    for port in SERVICE_QUOTAS:
        name = f"finals-{port}"
        project_paths[str(port)] = str(mount / str(port))
        project_ids[name] = str(port)
    ensure_mappings(projects_path, project_paths)
    ensure_mappings(projid_path, project_ids)
    for port, quota in SERVICE_QUOTAS.items():
        name = f"finals-{port}"
        root = mount / str(port)
        root.mkdir(parents=True, exist_ok=True, mode=0o750)
        if root.is_symlink() or not stat.S_ISDIR(root.stat().st_mode):
            raise VolumeError(f"{root} is not a fixed service directory")
        for generation in ("live", "gate", "recovery"):
            path = root / generation
            path.mkdir(exist_ok=True, mode=0o750)
            if path.is_symlink() or not stat.S_ISDIR(path.stat().st_mode):
                raise VolumeError(f"{path} is not a fixed generation directory")
        runner(["xfs_quota", "-x", "-c", f"project -s {name}", str(mount)])
        runner([
            "xfs_quota",
            "-x",
            "-c",
            f"limit -p bhard={quota['bytes']}b ihard={quota['inodes']} {name}",
            str(mount),
        ])


def initialize(role):
    profile = ROLES[role]
    device, state = select_data_disk(lsblk(), role)
    if state == "blank":
        ensure_no_signatures(device)
        if profile["filesystem"] == "xfs":
            command(["mkfs.xfs", "-f", "-L", profile["label"], device])
        else:
            command(["mkfs.ext4", "-F", "-L", profile["label"], device])
    ensure_fstab(profile)
    Path(profile["mount"]).mkdir(parents=True, exist_ok=True, mode=0o750)
    mount_if_needed(profile["mount"])
    try:
        result = subprocess.run(
            ["findmnt", "--noheadings", "--output", "LABEL,FSTYPE,TARGET,OPTIONS", "--target", profile["mount"]],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise VolumeError("fixed mount verification failed") from error
    fields = result.stdout.split()
    if len(fields) != 4 or fields[:3] != [profile["label"], profile["filesystem"], profile["mount"]]:
        raise VolumeError("mounted filesystem does not match the fixed role")
    if role == "production":
        options = set(fields[3].split(","))
        if not ({"prjquota", "pquota"} & options):
            raise VolumeError("production data volume is missing project quota enforcement")
        configure_service_quotas()


def main():
    if os.geteuid() != 0 or len(sys.argv) != 2 or sys.argv[1] not in ROLES:
        print(f"usage: {Path(sys.argv[0]).name} {{{'|'.join(ROLES)}}}", file=sys.stderr)
        return 2
    try:
        initialize(sys.argv[1])
    except VolumeError as error:
        print(f"volume initialization refused: {error}", file=sys.stderr)
        return 1
    print(f"fixed {sys.argv[1]} volume is mounted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
