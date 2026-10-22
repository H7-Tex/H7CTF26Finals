#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


GIB = 1024 ** 3
ROLES = {
    "anvil": {"label": "anvil-data", "mount": "/srv/anvil", "minimum": 140 * GIB, "maximum": 160 * GIB},
    "repository": {"label": "gitea-data", "mount": "/srv/gitea", "minimum": 90 * GIB, "maximum": 110 * GIB},
    "mirror": {"label": "cache-data", "mount": "/srv/cache", "minimum": 290 * GIB, "maximum": 310 * GIB},
    "captures": {"label": "captures-data", "mount": "/srv/captures", "minimum": 490 * GIB, "maximum": 510 * GIB},
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
    if filesystem == "ext4" and label == profile["label"] and mountpoints in ([], [profile["mount"]]):
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
    return f"LABEL={profile['label']} {profile['mount']} ext4 defaults,nodev,nosuid 0 2"


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


def initialize(role):
    profile = ROLES[role]
    device, state = select_data_disk(lsblk(), role)
    if state == "blank":
        ensure_no_signatures(device)
        command(["mkfs.ext4", "-F", "-L", profile["label"], device])
    ensure_fstab(profile)
    Path(profile["mount"]).mkdir(parents=True, exist_ok=True, mode=0o750)
    mount_if_needed(profile["mount"])
    try:
        result = subprocess.run(
            ["findmnt", "--noheadings", "--output", "LABEL,FSTYPE,TARGET", "--target", profile["mount"]],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise VolumeError("fixed mount verification failed") from error
    if result.stdout.split() != [profile["label"], "ext4", profile["mount"]]:
        raise VolumeError("mounted filesystem does not match the fixed role")


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
