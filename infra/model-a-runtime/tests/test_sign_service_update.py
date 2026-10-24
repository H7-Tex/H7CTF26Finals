import hashlib
import importlib.util
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "sign_service_update", ROOT / "sign-service-update.py"
)
UPDATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(UPDATE)
MODEL_SPEC = importlib.util.spec_from_file_location(
    "sign_update_model_a", ROOT / "model_a.py"
)
MODEL = importlib.util.module_from_spec(MODEL_SPEC)
MODEL_SPEC.loader.exec_module(MODEL)


def sha(value):
    return hashlib.sha256(value).hexdigest()


def record(index, bundle):
    return {
        "factory_reference": f"finals/model-a/sign-me-in:r{index}",
        "factory_image_id": "sha256:" + f"{index:064x}",
        "bundle_sha256": bundle,
    }


def bundle(root, image):
    source = root / "source"
    (source / "service").mkdir(parents=True)
    (source / "player").mkdir()
    (source / "service/app.py").write_text("print('service')\n", encoding="utf-8")
    (source / "player/client.py").write_text("print('client')\n", encoding="utf-8")
    files = {
        "player/client.py": sha((source / "player/client.py").read_bytes()),
        "service/app.py": sha((source / "service/app.py").read_bytes()),
    }
    (source / "BUNDLE.json").write_text(
        json.dumps({"schema_version": 1, "slug": "sign-me-in", "files": files}),
        encoding="utf-8",
    )
    (source / "compose.yaml").write_text(
        json.dumps(MODEL.compose_document(MODEL.SERVICE_BY_SLUG["sign-me-in"], image)),
        encoding="utf-8",
    )
    archive = root / "player-bundle.tar"
    with tarfile.open(archive, "w") as output:
        for path in sorted(source.rglob("*")):
            output.add(path, arcname=path.relative_to(source), recursive=False)
    return archive, sha((source / "BUNDLE.json").read_bytes())


class SignServiceUpdateTests(unittest.TestCase):
    def test_installed_tree_rejects_symbolic_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source").mkdir()
            (root / "source/link").symlink_to("/etc/passwd")
            with self.assertRaisesRegex(UPDATE.UpdateError, "source tree is unsafe"):
                UPDATE.validate_tree(root / "source")

    def test_image_archive_rejects_multiple_references(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "image.tar"
            content = json.dumps(
                [
                    {
                        "Config": "config.json",
                        "RepoTags": ["finals/model-a/sign-me-in:one", "unrelated:two"],
                        "Layers": [],
                    }
                ]
            ).encode()
            with tarfile.open(archive, "w") as output:
                member = tarfile.TarInfo("manifest.json")
                member.size = len(content)
                output.addfile(member, io.BytesIO(content))
            with self.assertRaisesRegex(UPDATE.UpdateError, "only the replacement"):
                UPDATE.verify_image_archive(archive, "finals/model-a/sign-me-in:one")

    def test_bundle_extraction_rejects_symbolic_links(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "unsafe.tar"
            with tarfile.open(archive, "w") as output:
                member = tarfile.TarInfo("service/link")
                member.type = tarfile.SYMTYPE
                member.linkname = "/etc/passwd"
                output.addfile(member)
            with self.assertRaisesRegex(UPDATE.UpdateError, "unsafe member"):
                UPDATE.safe_extract_bundle(archive, Path(directory) / "out")

    def test_dry_run_validates_without_mutating_installed_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state"
            workspace = root / "services/sign-me-in"
            factory = state / "factory/sign-me-in"
            active = state / "active/sign-me-in"
            data = root / "data"
            candidate = root / "candidate"
            for path in (workspace, factory, active.parent, data, candidate):
                path.mkdir(parents=True, exist_ok=True)
            (state / "firstboot.done").write_text("done\n", encoding="utf-8")
            (workspace / "kept").write_text("workspace\n", encoding="utf-8")
            (factory / "kept").write_text("factory\n", encoding="utf-8")
            old_bundle = "a" * 64
            old = record(1, old_bundle)
            image = record(2, "b" * 64)["factory_image_id"]
            archive, bundle_digest = bundle(root, image)
            replacement = record(2, bundle_digest)
            replacement["factory_reference"] = "finals/model-a/sign-me-in:" + "c" * 40
            image_archive = candidate / "service-image.tar"
            image_archive.write_bytes(b"image")
            target_bundle = candidate / "player-bundle.tar"
            target_bundle.write_bytes(archive.read_bytes())
            update = {
                "schema_version": 1,
                "slug": "sign-me-in",
                "source_commit": "c" * 40,
                "expected": old,
                "replacement": replacement,
                "artifacts": {
                    "image": {
                        "path": "service-image.tar",
                        "sha256": sha(image_archive.read_bytes()),
                        "bytes": image_archive.stat().st_size,
                    },
                    "bundle": {
                        "path": "player-bundle.tar",
                        "sha256": sha(target_bundle.read_bytes()),
                        "bytes": target_bundle.stat().st_size,
                    },
                },
            }
            (candidate / "update.json").write_text(json.dumps(update), encoding="utf-8")
            active.write_text(old["factory_image_id"] + "\n", encoding="utf-8")
            services = []
            for index, contract in enumerate(MODEL.SERVICES, 1):
                factory_record = (
                    old
                    if contract["slug"] == "sign-me-in"
                    else record(index + 10, f"{index:064x}")
                )
                services.append(
                    {
                        "slug": contract["slug"],
                        "port": contract["port"],
                        "uid": contract["uid"],
                        **factory_record,
                        "storage_bytes": contract["storage_bytes"],
                        "storage_inodes": contract["storage_inodes"],
                    }
                )
            release = state / "release.json"
            release.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "source_commit": MODEL.SOURCE_COMMIT,
                        "services": services,
                        "base_images": [],
                        "archives": {},
                    }
                ),
                encoding="utf-8",
            )
            before = {
                "active": active.read_bytes(),
                "release": release.read_bytes(),
                "workspace": (workspace / "kept").read_bytes(),
                "factory": (factory / "kept").read_bytes(),
            }
            values = {
                "CANDIDATE": candidate,
                "ROLLBACK": root / "rollback",
                "STATE_ROOT": state,
                "WORKSPACE": workspace,
                "FACTORY": factory,
                "ACTIVE": active,
                "RELEASE": release,
                "DATA": data,
            }
            with (
                mock.patch.multiple(UPDATE, **values),
                mock.patch.object(UPDATE.os, "geteuid", return_value=0),
                mock.patch.object(UPDATE, "load_update", return_value=update),
                mock.patch.object(
                    UPDATE,
                    "docker_image",
                    return_value=old["factory_image_id"],
                ),
                mock.patch.object(UPDATE, "container_status"),
                mock.patch("sys.stdout", new_callable=io.StringIO) as output,
            ):
                UPDATE.apply_update(dry_run=True)
                self.assertEqual(
                    output.getvalue(), "sign-service-update=dry-run-green\n"
                )
            self.assertEqual(active.read_bytes(), before["active"])
            self.assertEqual(release.read_bytes(), before["release"])
            self.assertEqual((workspace / "kept").read_bytes(), before["workspace"])
            self.assertEqual((factory / "kept").read_bytes(), before["factory"])
            self.assertFalse((root / "rollback").exists())


if __name__ == "__main__":
    unittest.main()
