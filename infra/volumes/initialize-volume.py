#!/usr/bin/env python3
import json
import os
import re
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

VOLUME_POLICY = Path("/etc/finals-release/volume-policy.json")


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


def duplicate_safe_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise VolumeError(f"volume policy repeats {key!r}")
        result[key] = value
    return result


def exact(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise VolumeError(f"volume policy has invalid {label}")


def load_volume_policy(path=VOLUME_POLICY):
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o022 or info.st_size > 1024 * 1024:
            raise VolumeError("volume policy must be a private regular file owned by the initializer")
        policy = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=duplicate_safe_object)
    except VolumeError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise VolumeError("cannot read the volume policy") from error
    exact(policy, {"schema_version", "mount", "services"}, "document")
    if policy["schema_version"] != 1 or policy["mount"] != ROLES["production"]["mount"]:
        raise VolumeError("volume policy has an invalid identity")
    services = policy["services"]
    if not isinstance(services, list) or len(services) != 6:
        raise VolumeError("volume policy must contain six services")
    seen_slugs, seen_ports, seen_uids, seen_ids, seen_names, seen_paths = set(), set(), set(), set(), set(), set()
    quota_bytes = 0
    quota_inodes = 0
    for service in services:
        exact(service, {"slug", "port", "uid", "quota", "generations"}, "service")
        slug, port, uid = service["slug"], service["port"], service["uid"]
        if not isinstance(slug, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
            raise VolumeError("volume policy has an invalid service slug")
        if isinstance(port, bool) or not isinstance(port, int) or port not in range(7001, 7007):
            raise VolumeError(f"volume policy has an invalid port for {slug}")
        if isinstance(uid, bool) or not isinstance(uid, int) or not 10000 <= uid <= 65535:
            raise VolumeError(f"volume policy has an invalid UID for {slug}")
        if slug in seen_slugs or port in seen_ports or uid in seen_uids:
            raise VolumeError("volume policy repeats a service identity")
        seen_slugs.add(slug)
        seen_ports.add(port)
        seen_uids.add(uid)
        quota = service["quota"]
        exact(quota, {"bytes", "inodes"}, f"quota for {slug}")
        if any(isinstance(quota[name], bool) or not isinstance(quota[name], int) for name in ("bytes", "inodes")):
            raise VolumeError(f"volume policy has a malformed quota for {slug}")
        if not 64 * 1024 * 1024 <= quota["bytes"] <= 4 * GIB or not 1024 <= quota["inodes"] <= 262144:
            raise VolumeError(f"volume policy has an unsafe quota for {slug}")
        quota_bytes += quota["bytes"] * 3
        quota_inodes += quota["inodes"] * 3
        generations = service["generations"]
        exact(generations, {"live", "gate", "recovery"}, f"generations for {slug}")
        for name, offset in (("live", 0), ("gate", 10000), ("recovery", 20000)):
            generation = generations[name]
            exact(generation, {"path", "project_name", "project_id"}, f"{name} generation for {slug}")
            expected = {
                "path": f"{policy['mount']}/{port}/{name}",
                "project_name": f"finals-{port}-{name}",
                "project_id": port + offset,
            }
            if generation != expected:
                raise VolumeError(f"volume policy has a non-fixed {name} generation for {slug}")
            if generation["project_id"] in seen_ids or generation["project_name"] in seen_names or generation["path"] in seen_paths:
                raise VolumeError("volume policy repeats a project identity")
            seen_ids.add(generation["project_id"])
            seen_names.add(generation["project_name"])
            seen_paths.add(generation["path"])
    if seen_ports != set(range(7001, 7007)):
        raise VolumeError("volume policy has incomplete service ports")
    if quota_bytes > 32 * GIB or quota_inodes > 2_000_000:
        raise VolumeError("volume policy exceeds the production volume reserve")
    return policy


def configure_service_quotas(
    policy,
    mount=Path("/srv/finals/service-data"),
    projects_path=Path("/etc/projects"),
    projid_path=Path("/etc/projid"),
    runner=command,
    chowner=os.chown,
):
    if policy["mount"] != str(mount):
        raise VolumeError("volume policy does not match the mounted production volume")
    project_paths = {}
    project_ids = {}
    for service in policy["services"]:
        for generation in service["generations"].values():
            project_paths[str(generation["project_id"])] = generation["path"]
            project_ids[generation["project_name"]] = str(generation["project_id"])
    ensure_mappings(projects_path, project_paths)
    ensure_mappings(projid_path, project_ids)
    for service in policy["services"]:
        port, quota = service["port"], service["quota"]
        root = mount / str(port)
        root.mkdir(parents=True, exist_ok=True, mode=0o750)
        if root.is_symlink() or not stat.S_ISDIR(root.stat().st_mode):
            raise VolumeError(f"{root} is not a fixed service directory")
        os.chmod(root, 0o750)
        for generation in service["generations"].values():
            name = generation["project_name"]
            path = Path(generation["path"])
            path.mkdir(exist_ok=True, mode=0o750)
            if path.is_symlink() or not stat.S_ISDIR(path.stat().st_mode):
                raise VolumeError(f"{path} is not a fixed generation directory")
            os.chmod(path, 0o750)
            chowner(path, service["uid"], service["uid"])
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
        configure_service_quotas(load_volume_policy())


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
