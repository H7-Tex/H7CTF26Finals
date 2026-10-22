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


class VolumeSelectionTests(unittest.TestCase):
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

    def test_service_quota_layout_and_commands_are_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mount = root / "service-data"
            mount.mkdir()
            projects = root / "projects"
            projid = root / "projid"
            commands = []
            MODULE.configure_service_quotas(mount, projects, projid, commands.append)
            MODULE.configure_service_quotas(mount, projects, projid, commands.append)
            project_lines = projects.read_text(encoding="utf-8").splitlines()
            projid_lines = projid.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(project_lines), 6)
            self.assertEqual(len(projid_lines), 6)
            self.assertIn(f"7005:{mount / '7005'}", project_lines)
            self.assertIn("finals-7005:7005", projid_lines)
            for port in MODULE.SERVICE_QUOTAS:
                for generation in ("live", "gate", "recovery"):
                    self.assertTrue((mount / str(port) / generation).is_dir())
            self.assertEqual(len(commands), 24)
            self.assertIn(
                ["xfs_quota", "-x", "-c", "limit -p bhard=2147483648b ihard=131072 finals-7005", str(mount)],
                commands,
            )

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
