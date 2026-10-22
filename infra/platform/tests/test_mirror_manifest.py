import hashlib
import importlib.machinery
import importlib.util
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "rootfs/usr/local/sbin/finals-mirror-manifest"
LOADER = importlib.machinery.SourceFileLoader("mirror_manifest", str(MODULE_PATH))
SPEC = importlib.util.spec_from_loader("mirror_manifest", LOADER)
MODULE = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(MODULE)


class MirrorManifestTests(unittest.TestCase):
    def test_builds_exact_inventory_for_all_cache_classes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for cache_class in MODULE.CLASSES:
                artifact = root / cache_class / "artifact"
                artifact.parent.mkdir()
                artifact.write_bytes(cache_class.encode())
            result = MODULE.build(root)
            self.assertEqual(result["version"], 1)
            self.assertEqual(len(result["files"]), 4)
            for entry in result["files"]:
                content = entry["path"].split("/", 1)[0].encode()
                self.assertEqual(entry["sha256"], hashlib.sha256(content).hexdigest())

    def test_rejects_empty_class_and_symbolic_link(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for cache_class in MODULE.CLASSES:
                (root / cache_class).mkdir()
            with self.assertRaises(SystemExit):
                MODULE.build(root)
            target = root / "target"
            target.write_text("x", encoding="utf-8")
            (root / "apt/link").symlink_to(target)
            with self.assertRaises(SystemExit):
                MODULE.build(root)


if __name__ == "__main__":
    unittest.main()
