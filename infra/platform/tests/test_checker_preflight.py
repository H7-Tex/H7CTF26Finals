import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = (
    Path(__file__).parents[2]
    / "checkers/rootfs/usr/local/libexec/checker-runtime/runtime.py"
)
SPEC = importlib.util.spec_from_file_location("checker_runtime_contract", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CheckerPreflightTests(unittest.TestCase):
    def test_locked_six_service_contract(self):
        self.assertEqual(
            [service["slot"] for service in MODULE.EXPECTED],
            [f"AD{index}" for index in range(1, 7)],
        )
        self.assertEqual(
            [service["target_port"] for service in MODULE.EXPECTED],
            list(range(7001, 7007)),
        )
        self.assertEqual(
            [service["checker_port"] for service in MODULE.EXPECTED],
            list(range(9001, 9007)),
        )
        self.assertTrue(all(service["flag_stores"] == 2 for service in MODULE.EXPECTED))

    def test_database_image_is_digest_pinned(self):
        self.assertRegex(MODULE.DATABASE_IMAGE, r"^[a-z0-9._/-]+@sha256:[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
