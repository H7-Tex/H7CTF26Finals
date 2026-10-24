import hashlib
import importlib.util
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "sign_checker_update", ROOT / "sign-checker-update.py"
)
UPDATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(UPDATE)
RUNTIME_PATH = ROOT / "rootfs/usr/local/libexec/checker-runtime/runtime.py"
RUNTIME_SPEC = importlib.util.spec_from_file_location(
    "sign_update_runtime", RUNTIME_PATH
)
RUNTIME = importlib.util.module_from_spec(RUNTIME_SPEC)
RUNTIME_SPEC.loader.exec_module(RUNTIME)


def image_id(index):
    return "sha256:" + f"{index:064x}"


def sha(value):
    return hashlib.sha256(value).hexdigest()


def docker_archive(path, reference):
    content = json.dumps(
        [{"Config": "config.json", "RepoTags": [reference], "Layers": []}]
    ).encode()
    with tarfile.open(path, "w") as output:
        member = tarfile.TarInfo("manifest.json")
        member.size = len(content)
        output.addfile(member, io.BytesIO(content))
    return path.read_bytes()


def manifest(root):
    artifacts = root / "artifacts"
    services = []
    for index, expected in enumerate(RUNTIME.EXPECTED, 1):
        content = f"checker {expected['slug']}".encode()
        archive = artifacts / expected["slug"] / "checker-image.tar"
        archive.parent.mkdir(parents=True)
        archive.write_bytes(content)
        archive.chmod(0o600)
        services.append(
            {
                **expected,
                "artifact": {
                    "path": f"{expected['slug']}/checker-image.tar",
                    "sha256": sha(content),
                    "size": len(content),
                    "executable": False,
                    "image": f"finals/checkers/{expected['slug']}:r1",
                    "image_id": image_id(index),
                },
            }
        )
    document = {
        "version": 2,
        "database_image": RUNTIME.DATABASE_IMAGE,
        "services": services,
    }
    path = root / "manifest.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    path.chmod(0o600)
    return path, artifacts, document


class SignCheckerUpdateTests(unittest.TestCase):
    def test_ready_waits_for_the_replacement_container_image(self):
        manifest = {"services": []}
        response = mock.MagicMock()
        response.__enter__.return_value.status = 200
        with (
            mock.patch.object(UPDATE.urllib.request, "urlopen", return_value=response),
            mock.patch.object(
                UPDATE,
                "verify_runtime_images",
                side_effect=[UPDATE.UpdateError("old image"), None],
            ) as verify,
            mock.patch.object(UPDATE.time, "sleep") as sleep,
        ):
            UPDATE.ready(manifest)
        self.assertEqual(verify.call_count, 2)
        sleep.assert_called_once_with(1)

    def test_runtime_reload_validates_before_restarting_the_supervisor(self):
        manifest = {"services": []}
        with (
            mock.patch.object(UPDATE, "run") as command,
            mock.patch.object(UPDATE, "restart_supervisor") as restart,
        ):
            UPDATE.runtime_reload(manifest)
        self.assertEqual(
            [call.args[0] for call in command.call_args_list],
            [[str(UPDATE.RUNTIME), "validate-artifacts"]],
        )
        restart.assert_called_once_with(manifest)

    def test_supervisor_restart_suppresses_exec_stop_and_removes_the_override(self):
        with tempfile.TemporaryDirectory() as directory:
            override = Path(directory) / "unit.d/sign-update.conf"
            with (
                mock.patch.object(UPDATE, "STOP_OVERRIDE", override),
                mock.patch.object(UPDATE, "run") as command,
                mock.patch.object(UPDATE, "ready") as ready,
            ):
                UPDATE.restart_supervisor({"services": []})
            self.assertEqual(
                [call.args[0] for call in command.call_args_list],
                [
                    ["systemctl", "daemon-reload"],
                    ["systemctl", "restart", "checker-runtime.service"],
                    ["systemctl", "daemon-reload"],
                ],
            )
            ready.assert_called_once_with({"services": []})
            self.assertFalse(override.exists())

    def test_runtime_delta_allows_only_the_sign_checker_container(self):
        before = {
            "checker-sign-me-in": "old",
            "checker-db-sign-me-in": "database",
            "checker-ship-it": "ship",
        }
        after = {**before, "checker-sign-me-in": "new"}
        UPDATE.verify_only_sign_changed(before, after)
        after["checker-ship-it"] = "changed"
        with self.assertRaisesRegex(UPDATE.UpdateError, "unrelated"):
            UPDATE.verify_only_sign_changed(before, after)

    def test_delta_rejects_an_unrelated_service_change(self):
        with tempfile.TemporaryDirectory() as directory:
            _, _, current = manifest(Path(directory))
            replacement = json.loads(json.dumps(current))
            replacement["services"][0]["artifact"]["image"] = (
                "finals/checkers/sign-me-in:r2"
            )
            replacement["services"][0]["artifact"]["image_id"] = image_id(20)
            replacement["services"][0]["artifact"]["sha256"] = "a" * 64
            replacement["services"][1]["artifact"]["image"] = (
                "finals/checkers/can-we-settle-this:r2"
            )
            with self.assertRaisesRegex(UPDATE.UpdateError, "unrelated service"):
                UPDATE.validate_manifest_delta(current, replacement)

    def test_delta_rejects_a_non_object_service(self):
        with tempfile.TemporaryDirectory() as directory:
            _, _, current = manifest(Path(directory))
            replacement = json.loads(json.dumps(current))
            replacement["services"][0] = "sign-me-in"
            with self.assertRaisesRegex(UPDATE.UpdateError, "inventory is invalid"):
                UPDATE.validate_manifest_delta(current, replacement)

    def test_dry_run_accepts_only_the_sign_manifest_delta_without_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current_path, artifacts, current = manifest(root)
            replacement = json.loads(json.dumps(current))
            new_archive = docker_archive(
                root / "new-checker.tar",
                "finals/checkers/sign-me-in:" + "c" * 40,
            )
            sign = replacement["services"][0]["artifact"]
            sign.update(
                {
                    "sha256": sha(new_archive),
                    "size": len(new_archive),
                    "image": "finals/checkers/sign-me-in:" + "c" * 40,
                    "image_id": image_id(20),
                }
            )
            candidate = root / "candidate"
            (candidate / "sign-me-in").mkdir(parents=True)
            (candidate / "sign-me-in/checker-image.tar").write_bytes(new_archive)
            replacement_path = candidate / "artifact-manifest.json"
            replacement_path.write_text(json.dumps(replacement), encoding="utf-8")
            expected_sha = sha(current_path.read_bytes())
            replacement_sha = sha(replacement_path.read_bytes())
            update = {
                "schema_version": 1,
                "slug": "sign-me-in",
                "source_commit": "c" * 40,
                "expected_manifest_sha256": expected_sha,
                "replacement_manifest_sha256": replacement_sha,
                "expected_artifact": current["services"][0]["artifact"],
                "replacement_artifact": replacement["services"][0]["artifact"],
            }
            (candidate / "update.json").write_text(json.dumps(update), encoding="utf-8")
            data = root / "data/sign-me-in/mongo"
            for service in RUNTIME.EXPECTED:
                (root / "data" / service["slug"] / "mongo").mkdir(parents=True)
            before = current_path.read_bytes()
            values = {
                "CANDIDATE": candidate,
                "ROLLBACK": root / "rollback",
                "CURRENT_MANIFEST": current_path,
                "CURRENT_ROOT": artifacts,
                "CURRENT_ARCHIVE": artifacts / "sign-me-in/checker-image.tar",
                "RUNTIME": RUNTIME_PATH,
                "DATA": data,
            }
            real_load_update = UPDATE.load_update
            with (
                mock.patch.multiple(UPDATE, **values),
                mock.patch.object(UPDATE.os, "geteuid", return_value=0),
                mock.patch.object(
                    UPDATE.subprocess,
                    "run",
                    return_value=SimpleNamespace(returncode=0),
                ),
                mock.patch.object(
                    UPDATE,
                    "load_update",
                    side_effect=lambda: real_load_update(candidate, False),
                ),
                mock.patch.object(UPDATE, "verify_runtime_images"),
                mock.patch.object(UPDATE, "runtime_inventory", return_value={}),
                mock.patch("sys.stdout", new_callable=io.StringIO) as output,
            ):
                UPDATE.apply_update(dry_run=True)
                self.assertEqual(
                    output.getvalue(), "sign-checker-update=dry-run-green\n"
                )
            self.assertEqual(current_path.read_bytes(), before)
            self.assertFalse((root / "rollback").exists())


if __name__ == "__main__":
    unittest.main()
