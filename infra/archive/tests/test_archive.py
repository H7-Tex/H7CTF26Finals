import base64
import hashlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
import urllib.error
import urllib.parse
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "finals-archive.py"
SPEC = importlib.util.spec_from_file_location("finals_archive", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ArchiveTests(unittest.TestCase):
    def test_token_exchange_uses_mtls_chain_and_provider_audience(self):
        original_identity = MODULE.identity_context
        original_request = MODULE.request_json
        context = object()
        captured = {}

        def request(url, **kwargs):
            captured["url"] = url
            captured.update(kwargs)
            return {"access_token": "a" * 64, "token_type": "Bearer", "expires_in": 3600}

        MODULE.identity_context = lambda _: ("instance", context, '["leaf","intermediate"]')
        MODULE.request_json = request
        try:
            self.assertEqual(MODULE.access_token(Path("/unused")), "a" * 64)
        finally:
            MODULE.identity_context = original_identity
            MODULE.request_json = original_request
        body = json.loads(captured["data"])
        self.assertEqual(captured["url"], "https://sts.mtls.googleapis.com/v1/token")
        self.assertIs(captured["context"], context)
        self.assertEqual(body["audience"], MODULE.AUDIENCE)
        self.assertEqual(body["subject_token_type"], "urn:ietf:params:oauth:token-type:mtls")
        self.assertEqual(body["subject_token"], '["leaf","intermediate"]')

    def test_role_matrix_keeps_cloud_archive_off_the_scoring_path(self):
        original = MODULE.Path
        marker = type("Marker", (), {"is_file": lambda self: True, "read_text": lambda self, **_: "enabled\n"})()
        MODULE.Path = lambda _: marker
        try:
            MODULE.authorize("platform", "upload", "database")
            MODULE.authorize("platform", "upload", "scores")
            MODULE.authorize("repository", "upload", "gitea")
            MODULE.authorize("gateway", "upload", "pcaps")
            MODULE.authorize("operations", "verify", "database")
            MODULE.authorize("operations", "download", "pcaps")
            with self.assertRaises(MODULE.ArchiveError):
                MODULE.authorize("platform", "upload", "gitea")
            with self.assertRaises(MODULE.ArchiveError):
                MODULE.authorize("operations", "upload", "database")
        finally:
            MODULE.Path = original

    def test_every_action_requires_explicit_post_event_egress(self):
        original = MODULE.Path
        marker = type("Marker", (), {"is_file": lambda self: False})()
        MODULE.Path = lambda _: marker
        try:
            for action, role in (("upload", "platform"), ("verify", "operations"), ("download", "operations")):
                with self.assertRaisesRegex(MODULE.ArchiveError, "not enabled"):
                    MODULE.authorize(role, action, "database")
        finally:
            MODULE.Path = original

    def test_source_must_be_private_root_owned_and_inside_fixed_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "root"
            root.mkdir()
            source = root / "archive.bin"
            source.write_bytes(b"archive")
            source.chmod(0o600)
            resolved, info = MODULE.source_file(
                "platform", "database", source, {"platform": {"database": root}}, owner_uid=os.getuid()
            )
            self.assertEqual(resolved, source)
            self.assertEqual(info.st_size, 7)
            source.chmod(0o620)
            with self.assertRaisesRegex(MODULE.ArchiveError, "not writable"):
                MODULE.source_file(
                    "platform", "database", source, {"platform": {"database": root}}, owner_uid=os.getuid()
                )
            outside = Path(directory) / "outside"
            outside.write_bytes(b"archive")
            with self.assertRaisesRegex(MODULE.ArchiveError, "outside"):
                MODULE.source_file(
                    "platform", "database", outside, {"platform": {"database": root}}, owner_uid=os.getuid()
                )

    def test_remote_metadata_is_bound_to_bucket_name_hash_size_and_md5(self):
        digest = "a" * 64
        document = {
            "bucket": MODULE.BUCKETS["database"],
            "name": MODULE.object_name(digest),
            "generation": "123",
            "size": "7",
            "md5Hash": "abc=",
            "metadata": {"sha256": digest},
        }
        self.assertEqual(MODULE.validate_metadata(document, "database", digest, size=7, md5="abc="), document)
        changed = json.loads(json.dumps(document))
        changed["metadata"]["sha256"] = "b" * 64
        with self.assertRaisesRegex(MODULE.ArchiveError, "immutable identity"):
            MODULE.validate_metadata(changed, "database", digest)

    def test_upload_is_content_addressed_create_only_and_streamed(self):
        original_source = MODULE.source_file
        original_urlopen = MODULE.urllib.request.urlopen
        original_request = MODULE.request_json
        captured = {}

        class Initiated:
            headers = {"Location": "https://storage.googleapis.com/resumable-session"}

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "archive.bin"
            source.write_bytes(b"archive-stream")
            before = source.stat()
            digest, md5 = MODULE.file_identity(source)
            expected = {
                "bucket": MODULE.BUCKETS["database"],
                "name": MODULE.object_name(digest),
                "generation": "123",
                "size": str(before.st_size),
                "md5Hash": md5,
                "metadata": {"sha256": digest},
            }

            def urlopen(request, **_):
                query = urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query)
                captured["precondition"] = query.get("ifGenerationMatch")
                captured["metadata"] = json.loads(request.data)
                return Initiated()

            def request_json(url, **kwargs):
                captured["upload_url"] = url
                captured["headers"] = kwargs["headers"]
                captured["bytes"] = kwargs["data"].read()
                return expected

            MODULE.source_file = lambda *_, **__: (source, before)
            MODULE.urllib.request.urlopen = urlopen
            MODULE.request_json = request_json
            try:
                self.assertEqual(MODULE.upload("token", "platform", "database", str(source)), expected)
            finally:
                MODULE.source_file = original_source
                MODULE.urllib.request.urlopen = original_urlopen
                MODULE.request_json = original_request

        self.assertEqual(captured["precondition"], ["0"])
        self.assertEqual(captured["metadata"], {"name": MODULE.object_name(digest), "metadata": {"sha256": digest}})
        self.assertEqual(captured["upload_url"], "https://storage.googleapis.com/resumable-session")
        self.assertEqual(captured["headers"]["X-Goog-Hash"], f"md5={md5}")
        self.assertEqual(captured["bytes"], b"archive-stream")

    def test_existing_content_address_is_verified_after_precondition_failure(self):
        original_source = MODULE.source_file
        original_urlopen = MODULE.urllib.request.urlopen
        original_metadata = MODULE.remote_metadata
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "archive.bin"
            source.write_bytes(b"existing-archive")
            before = source.stat()
            digest, md5 = MODULE.file_identity(source)
            expected = {
                "bucket": MODULE.BUCKETS["database"],
                "name": MODULE.object_name(digest),
                "generation": "456",
                "size": str(before.st_size),
                "md5Hash": md5,
                "metadata": {"sha256": digest},
            }
            MODULE.source_file = lambda *_, **__: (source, before)
            MODULE.urllib.request.urlopen = lambda *_, **__: (_ for _ in ()).throw(
                urllib.error.HTTPError("https://storage.googleapis.com", 412, "exists", {}, None)
            )
            MODULE.remote_metadata = lambda *_: expected
            try:
                self.assertEqual(MODULE.upload("token", "platform", "database", str(source)), expected)
            finally:
                MODULE.source_file = original_source
                MODULE.urllib.request.urlopen = original_urlopen
                MODULE.remote_metadata = original_metadata

    def test_download_verifies_both_hashes_and_exact_generation(self):
        original_metadata = MODULE.remote_metadata
        original_restore = MODULE.restore_path
        original_request = MODULE.request
        content = b"recovery-archive"
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "restore.bin"
            digest = hashlib.sha256(content).hexdigest()
            md5 = base64.b64encode(hashlib.md5(content, usedforsecurity=False).digest()).decode("ascii")
            metadata = {
                "bucket": MODULE.BUCKETS["database"],
                "name": MODULE.object_name(digest),
                "generation": "789",
                "size": str(len(content)),
                "md5Hash": md5,
                "metadata": {"sha256": digest},
            }
            stream = io.BytesIO(content)
            captured = {}

            def request(url, **_):
                captured["url"] = url
                return stream

            MODULE.remote_metadata = lambda *_: metadata
            MODULE.restore_path = lambda *_: destination
            MODULE.request = request
            try:
                self.assertEqual(MODULE.download("token", "database", digest, str(destination)), destination)
            finally:
                MODULE.remote_metadata = original_metadata
                MODULE.restore_path = original_restore
                MODULE.request = original_request
            self.assertEqual(destination.read_bytes(), content)
            self.assertEqual(urllib.parse.parse_qs(urllib.parse.urlsplit(captured["url"]).query)["generation"], ["789"])

    def test_gateway_egress_is_post_event_fail_closed(self):
        source = (MODULE_PATH.parent / "finals-archive-egress").read_text(encoding="utf-8")
        self.assertIn('event-router-addresses standby', source)
        self.assertIn('ip address replace 10.60.250.101/24 dev "$interface"', source)
        self.assertIn("nft flush set inet event_router archive_https_ports", source)
        self.assertIn("nft flush set inet event_router archive_imds_ports", source)
        self.assertIn("trap 'rollback_enable; exit 1' ERR INT TERM", source)
        self.assertNotIn("archive_https_ports '{ 80 }'", source)

    def test_receipts_are_idempotent_and_conflicts_fail_closed(self):
        digest = "c" * 64
        metadata = {
            "bucket": MODULE.BUCKETS["scores"],
            "name": MODULE.object_name(digest),
            "generation": "456",
            "size": "9",
            "md5Hash": "xyz=",
            "metadata": {"sha256": digest},
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = MODULE.write_receipt("scores", digest, metadata, root)
            second = MODULE.write_receipt("scores", digest, metadata, root)
            self.assertEqual(first, second)
            self.assertEqual(first.stat().st_mode & 0o777, 0o600)
            document = json.loads(first.read_text())
            self.assertEqual(document["generation"], "456")
            first.write_text("{}\n")
            with self.assertRaisesRegex(MODULE.ArchiveError, "conflicts"):
                MODULE.write_receipt("scores", digest, metadata, root)

    def test_restore_never_overwrites_or_escapes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "restore"
            root.mkdir()
            target = root / "database.bin"
            self.assertEqual(MODULE.restore_path(target, root), target)
            target.write_bytes(b"existing")
            with self.assertRaisesRegex(MODULE.ArchiveError, "exists"):
                MODULE.restore_path(target, root)
            outside = Path(directory) / "outside.bin"
            with self.assertRaisesRegex(MODULE.ArchiveError, "outside"):
                MODULE.restore_path(outside, root)


if __name__ == "__main__":
    unittest.main()
