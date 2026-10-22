import hashlib
import importlib.machinery
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "rootfs/usr/local/libexec/finals-platform/checker-preflight"
LOADER = importlib.machinery.SourceFileLoader("checker_preflight", str(MODULE_PATH))
SPEC = importlib.util.spec_from_loader("checker_preflight", LOADER)
MODULE = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(MODULE)


class CheckerPreflightTests(unittest.TestCase):
    def test_exact_artifact_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / "artifacts/service/checker"
            artifact.parent.mkdir(parents=True)
            artifact.write_bytes(b"checker")
            artifact.chmod(0o755)
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({
                "version": 1,
                "artifacts": [{
                    "path": "service/checker",
                    "sha256": hashlib.sha256(b"checker").hexdigest(),
                    "size": 7,
                    "executable": True,
                }],
            }), encoding="utf-8")
            MODULE.validate(manifest, root / "artifacts")

    def test_path_escape_and_digest_change_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({
                "version": 1,
                "artifacts": [{
                    "path": "../checker",
                    "sha256": "0" * 64,
                    "size": 1,
                    "executable": False,
                }],
            }), encoding="utf-8")
            with self.assertRaises(SystemExit):
                MODULE.validate(manifest, root / "artifacts")


if __name__ == "__main__":
    unittest.main()
