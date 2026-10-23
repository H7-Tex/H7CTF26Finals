import importlib.util
import json
import subprocess
import tempfile
import unittest
from unittest import mock
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "initialize-volume.py"
SPEC = importlib.util.spec_from_file_location("initialize_volume", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def disk(path, size, *, root=False, fstype=None, label=None, children=None):
    value = {
        "path": path,
        "type": "disk",
        "size": size,
        "fstype": fstype,
        "label": label,
        "mountpoints": [],
    }
    if root:
        value["children"] = [{
            "path": f"{path}1",
            "type": "part",
            "size": size,
            "fstype": "ext4",
            "label": None,
            "mountpoints": ["/"],
        }]
    elif children is not None:
        value["children"] = children
    return value


def volume_policy(mount):
    services = []
    quota_by_port = {
        7001: (1073741824, 65536),
        7002: (1073741824, 65536),
        7003: (536870912, 32768),
        7004: (1073741824, 65536),
        7005: (2147483648, 131072),
        7006: (1073741824, 65536),
    }
    slugs = ("sign-me-in", "can-we-settle-this", "update-pending", "book-me-if-you-can", "ship-it", "terms-may-apply")
    for index, (port, quota) in enumerate(quota_by_port.items()):
        services.append({
            "slug": slugs[index],
            "port": port,
            "uid": 10001 + index,
            "quota": {"bytes": quota[0], "inodes": quota[1]},
            "generations": {
                name: {
                    "path": str(mount / str(port) / name),
                    "project_name": f"finals-{port}-{name}",
                    "project_id": port + offset,
                }
                for name, offset in (("live", 0), ("gate", 10000), ("recovery", 20000))
            },
        })
    return {"schema_version": 1, "mount": str(mount), "services": services}


class VolumeSelectionTests(unittest.TestCase):
    def test_lsblk_requests_name_to_preserve_parent_child_topology(self):
        result = subprocess.CompletedProcess(
            ["lsblk"],
            0,
            json.dumps({"blockdevices": []}),
            "",
        )
        with mock.patch.object(MODULE.subprocess, "run", return_value=result) as runner:
            self.assertEqual(MODULE.lsblk(), {"blockdevices": []})
        self.assertEqual(
            runner.call_args.args[0],
            ["lsblk", "--json", "--bytes", "--output", "NAME,PATH,TYPE,SIZE,FSTYPE,LABEL,MOUNTPOINTS"],
        )

    def test_selects_only_blank_non_root_disk_in_role_range(self):
        document = {"blockdevices": [
            disk("/dev/sda", 50 * MODULE.GIB, root=True),
            disk("/dev/sdb", 100 * MODULE.GIB),
        ]}
        self.assertEqual(MODULE.select_data_disk(document, "repository"), ("/dev/sdb", "blank"))

    def test_rejects_root_disk_when_no_data_disk_exists(self):
        document = {"blockdevices": [disk("/dev/sda", 100 * MODULE.GIB, root=True)]}
        with self.assertRaisesRegex(MODULE.VolumeError, "non-root"):
            MODULE.select_data_disk(document, "repository")

    def test_rejects_ambiguous_or_unknown_disk(self):
        root = disk("/dev/sda", 50 * MODULE.GIB, root=True)
        with self.assertRaisesRegex(MODULE.VolumeError, "exactly one"):
            MODULE.select_data_disk({"blockdevices": [root, disk("/dev/sdb", 100 * MODULE.GIB), disk("/dev/sdc", 100 * MODULE.GIB)]}, "repository")
        with self.assertRaisesRegex(MODULE.VolumeError, "unexpected"):
            MODULE.select_data_disk({"blockdevices": [root, disk("/dev/sdb", 100 * MODULE.GIB, fstype="xfs", label="unknown")]}, "repository")

    def test_accepts_only_exact_idempotent_state(self):
        document = {"blockdevices": [
            disk("/dev/sda", 50 * MODULE.GIB, root=True),
            disk("/dev/sdb", 300 * MODULE.GIB, fstype="ext4", label="cache-data"),
        ]}
        self.assertEqual(MODULE.select_data_disk(document, "mirror"), ("/dev/sdb", "initialized"))
        with self.assertRaises(MODULE.VolumeError):
            MODULE.select_data_disk(document, "repository")

    def test_accepts_only_fixed_xfs_production_disk(self):
        root = disk("/dev/sda", 50 * MODULE.GIB, root=True)
        production = disk("/dev/sdb", 50 * MODULE.GIB, fstype="xfs", label="service-data")
        self.assertEqual(MODULE.select_data_disk({"blockdevices": [root, production]}, "production"), ("/dev/sdb", "initialized"))
        production["fstype"] = "ext4"
        with self.assertRaisesRegex(MODULE.VolumeError, "unexpected"):
            MODULE.select_data_disk({"blockdevices": [root, production]}, "production")

    def test_production_fstab_enables_project_quotas(self):
        self.assertEqual(
            MODULE.fstab_entry(MODULE.ROLES["production"]),
            "LABEL=service-data /srv/finals/service-data xfs defaults,nodev,nosuid,prjquota 0 2",
        )

    def test_hidden_disk_signature_is_rejected_before_format(self):
        result = subprocess.CompletedProcess(
            ["wipefs", "--json", "/dev/sdb"],
            0,
            json.dumps({"signatures": [{"type": "gpt", "offset": "0x200"}]}),
            "",
        )
        with mock.patch.object(MODULE.subprocess, "run", return_value=result):
            with self.assertRaisesRegex(MODULE.VolumeError, "unexpected signature"):
                MODULE.ensure_no_signatures("/dev/sdb")

    def test_only_explicitly_empty_signature_inventory_is_accepted(self):
        result = subprocess.CompletedProcess(
            ["wipefs", "--json", "/dev/sdb"],
            0,
            json.dumps({"signatures": None}),
            "",
        )
        with mock.patch.object(MODULE.subprocess, "run", return_value=result):
            MODULE.ensure_no_signatures("/dev/sdb")

    def test_already_mounted_volume_is_not_mounted_twice(self):
        commands = []
        self.assertFalse(MODULE.mount_if_needed("/srv/cache", is_mount=lambda _: True, runner=commands.append))
        self.assertEqual(commands, [])
        self.assertTrue(MODULE.mount_if_needed("/srv/cache", is_mount=lambda _: False, runner=commands.append))
        self.assertEqual(commands, [["mount", "/srv/cache"]])

    def test_anvil_layout_is_fixed_and_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            mount = Path(directory)
            ownership = []
            change_owner = lambda path, uid, gid: ownership.append((path.name, uid, gid))
            MODULE.ensure_anvil_layout(mount, change_owner)
            MODULE.ensure_anvil_layout(mount, change_owner)
            for name, (mode, _, _) in MODULE.ANVIL_LAYOUT.items():
                path = mount / name
                self.assertTrue(path.is_dir())
                self.assertEqual(path.stat().st_mode & 0o777, mode)
            self.assertEqual(ownership, [
                ("postgres", 70, 70),
                ("storage", 0, 0),
                ("backups", 0, 0),
            ] * 2)

    def test_anvil_layout_rejects_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            mount = Path(directory)
            target = mount / "target"
            target.mkdir()
            (mount / "postgres").symlink_to(target)
            with self.assertRaisesRegex(MODULE.VolumeError, "not a fixed Anvil directory"):
                MODULE.ensure_anvil_layout(mount, lambda *_: None)

    def test_service_quota_layout_and_commands_are_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mount = root / "service-data"
            mount.mkdir()
            projects = root / "projects"
            projid = root / "projid"
            commands = []
            ownership = []
            policy = volume_policy(mount)
            MODULE.configure_service_quotas(policy, mount, projects, projid, commands.append, lambda path, uid, gid: ownership.append((path, uid, gid)))
            MODULE.configure_service_quotas(policy, mount, projects, projid, commands.append, lambda path, uid, gid: ownership.append((path, uid, gid)))
            project_lines = projects.read_text(encoding="utf-8").splitlines()
            projid_lines = projid.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(project_lines), 18)
            self.assertEqual(len(projid_lines), 18)
            self.assertIn(f"7005:{mount / '7005' / 'live'}", project_lines)
            self.assertIn(f"17005:{mount / '7005' / 'gate'}", project_lines)
            self.assertIn(f"27005:{mount / '7005' / 'recovery'}", project_lines)
            self.assertIn("finals-7005-live:7005", projid_lines)
            self.assertIn("finals-7005-gate:17005", projid_lines)
            self.assertIn("finals-7005-recovery:27005", projid_lines)
            for port in range(7001, 7007):
                for generation in ("live", "gate", "recovery"):
                    self.assertTrue((mount / str(port) / generation).is_dir())
            self.assertEqual(len(commands), 72)
            self.assertEqual(len(ownership), 36)
            self.assertIn(
                ["xfs_quota", "-x", "-c", "limit -p bhard=2147483648b ihard=131072 finals-7005-recovery", str(mount)],
                commands,
            )

    def test_volume_policy_is_private_strict_and_generation_isolated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "policy.json"
            policy = volume_policy(Path("/srv/finals/service-data"))
            path.write_text(json.dumps(policy), encoding="utf-8")
            path.chmod(0o600)
            self.assertEqual(MODULE.load_volume_policy(path), policy)
            policy["services"][0]["generations"]["gate"] = policy["services"][0]["generations"]["live"]
            path.write_text(json.dumps(policy), encoding="utf-8")
            with self.assertRaisesRegex(MODULE.VolumeError, "non-fixed"):
                MODULE.load_volume_policy(path)
            path.chmod(0o666)
            with self.assertRaisesRegex(MODULE.VolumeError, "private"):
                MODULE.load_volume_policy(path)

    def test_conflicting_project_mapping_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "projects"
            path.write_text("7001:/unrelated\n", encoding="utf-8")
            with self.assertRaisesRegex(MODULE.VolumeError, "conflicting"):
                MODULE.ensure_mappings(path, {"7001": "/srv/finals/service-data/7001"})

    def test_mapping_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.write_text("", encoding="utf-8")
            path = root / "projects"
            path.symlink_to(target)
            with self.assertRaisesRegex(MODULE.VolumeError, "regular"):
                MODULE.ensure_mappings(path, {"7001": "/srv/finals/service-data/7001"})


if __name__ == "__main__":
    unittest.main()
