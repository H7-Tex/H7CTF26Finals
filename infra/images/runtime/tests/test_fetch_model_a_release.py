#!/usr/bin/env python3
import hashlib
import http.server
import importlib.machinery
import importlib.util
import json
import tempfile
import threading
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "fetch-model-a-release"
LOADER = importlib.machinery.SourceFileLoader("fetch_model_a_release", str(SCRIPT))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
MODULE = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(MODULE)

PAR = "https://objectstorage.ap-hyderabad-1.oraclecloud.com/p/AbC%2Fx+y=_-z/n/axilpw1vvpzo/b/finals-model-a/o/"


def sha(data):
    return hashlib.sha256(data).hexdigest()


class FetchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "served").mkdir()
        self.payload = b"model a archive bytes" * 1000
        (self.root / "served" / "blob").write_bytes(self.payload)
        directory = str(self.root / "served")

        class Quiet(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=directory, **kwargs)

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Quiet)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/blob"
        MODULE.time.sleep = lambda _: None

    def tearDown(self):
        self.server.shutdown()
        self.temporary.cleanup()

    def test_verified_download_lands_atomically(self):
        target = self.root / "out"
        MODULE.fetch(self.url, target, sha(self.payload), len(self.payload))
        self.assertEqual(target.read_bytes(), self.payload)
        self.assertFalse(target.with_name("out.partial").exists())
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_tampered_or_wrong_size_object_is_rejected(self):
        for digest, size in ((sha(b"other"), len(self.payload)), (sha(self.payload), len(self.payload) - 1)):
            target = self.root / "bad"
            with self.assertRaises(SystemExit):
                MODULE.fetch(self.url, target, digest, size)
            self.assertFalse(target.exists())
            self.assertFalse(target.with_name("bad.partial").exists())

    def manifest(self, **changes):
        objects = {name: {"sha256": "a" * 64, "size": 10} for name in MODULE.OBJECTS}
        document = {"base_url": PAR, "release_sha256": "a" * 64, "objects": objects}
        document.update(changes)
        path = self.root / "manifest.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def test_manifest_accepts_the_pinned_shape_and_encoded_par(self):
        self.assertEqual(MODULE.load(self.manifest())["base_url"], PAR)

    def test_manifest_rejects_drift(self):
        bad = [
            {"base_url": "https://example.com/p/x/n/y/b/z/o/"},
            {"base_url": PAR.removesuffix("/")},
            {"release_sha256": "b" * 64},
            {"objects": {"release.json": {"sha256": "a" * 64, "size": 10}}},
            {"extra": 1},
        ]
        for change in bad:
            with self.assertRaises(SystemExit, msg=change):
                MODULE.load(self.manifest(**change))


if __name__ == "__main__":
    unittest.main()
