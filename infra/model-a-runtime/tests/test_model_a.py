import importlib.util
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
CHALLENGE = Path(
    os.environ.get("CHALLENGE_REPO", ROOT.parents[2] / "H7CTF26Finals-challenges")
)
SPEC = importlib.util.spec_from_file_location("model_a", ROOT / "model_a.py")
MODEL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODEL)
sys.modules["model_a"] = MODEL
PREPARE_LOADER = SourceFileLoader(
    "model_a_prepare",
    str(ROOT / "prepare-release.py"),
)
PREPARE_SPEC = importlib.util.spec_from_loader("model_a_prepare", PREPARE_LOADER)
PREPARE = importlib.util.module_from_spec(PREPARE_SPEC)
PREPARE_LOADER.exec_module(PREPARE)
INSTALLER_LOADER = SourceFileLoader(
    "model_a_installer",
    str(ROOT / "rootfs/usr/local/sbin/finals-model-a-install"),
)
INSTALLER_SPEC = importlib.util.spec_from_loader("model_a_installer", INSTALLER_LOADER)
INSTALLER = importlib.util.module_from_spec(INSTALLER_SPEC)
INSTALLER_LOADER.exec_module(INSTALLER)
CONTROL_LOADER = SourceFileLoader(
    "model_a_control",
    str(ROOT / "rootfs/usr/local/sbin/finals-model-a-control"),
)
CONTROL_SPEC = importlib.util.spec_from_loader("model_a_control", CONTROL_LOADER)
CONTROL = importlib.util.module_from_spec(CONTROL_SPEC)
CONTROL_LOADER.exec_module(CONTROL)


class ModelATest(unittest.TestCase):
    @unittest.skipUnless(CHALLENGE.is_dir(), "challenge repository is not packaged")
    def test_contract_matches_challenge_manifests(self):
        self.assertEqual(
            subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=CHALLENGE,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip(),
            MODEL.SOURCE_COMMIT,
        )
        for service in MODEL.SERVICES:
            manifest = json.loads(
                (CHALLENGE / "services" / service["slug"] / "manifest.json").read_text()
            )
            runtime = manifest["runtime"]
            self.assertEqual(manifest["endpoint"]["port"], service["port"])
            self.assertEqual(runtime["user"], service["uid"])
            self.assertEqual(runtime["resources"]["cpus"], service["cpus"])
            self.assertEqual(
                runtime["resources"]["memory_mb"], int(service["memory"][:-1])
            )
            self.assertEqual(runtime["resources"]["pids"], service["pids"])
            self.assertEqual(
                runtime["resources"]["storage_mb"] * 1024 * 1024,
                service["storage_bytes"],
            )
            self.assertEqual(
                runtime["secret_paths"], [f"/data/{service['secret_name']}"]
            )
            self.assertFalse(runtime["outbound_network"])

    def test_compose_matches_audited_service_boundary(self):
        for service in MODEL.SERVICES:
            image = "sha256:" + "1" * 64
            compose = MODEL.compose_document(service, image)
            self.assertEqual(set(compose["services"]), {"service"})
            runtime = compose["services"]["service"]
            self.assertEqual(runtime["image"], "${H7_IMAGE:-" + image + "}")
            self.assertEqual(
                runtime["build"],
                {"context": service["build_context"], "network": "none"},
            )
            self.assertEqual(
                runtime["ports"],
                [f"127.0.0.1:{service['port'] + 10000}:{service['port']}"],
            )
            self.assertEqual(
                runtime["volumes"],
                [f"/srv/finals/service-data/{service['port']}/live:/data"],
            )
            self.assertTrue(runtime["read_only"])
            self.assertEqual(runtime["cap_drop"], ["ALL"])
            self.assertEqual(runtime["security_opt"], ["no-new-privileges:true"])
            self.assertTrue(compose["networks"]["target"]["internal"])
            self.assertEqual(
                compose["networks"]["target"]["ipam"]["config"],
                [{"subnet": service["subnet"]}],
            )
            encoded = json.dumps(compose)
            self.assertNotIn("checker", encoded)
            self.assertNotIn("mongo", encoded)
            self.assertNotIn("privileged", encoded)

    def test_proxy_is_l4_only(self):
        config = MODEL.proxy_config(7)
        for service in MODEL.SERVICES:
            self.assertIn(f"bind 10.60.7.2:{service['port']}", config)
            self.assertIn(
                f"server model_a 127.0.0.1:{service['port'] + 10000} check", config
            )
        self.assertNotIn("send-proxy", config)
        self.assertNotIn("http-request", config)
        self.assertNotIn("forwarded", config.lower())
        self.assertIn("bind 10.60.16.2:7001", MODEL.proxy_config(16))
        with self.assertRaises(MODEL.ModelAError):
            MODEL.proxy_config(17)

    @unittest.skipUnless(CHALLENGE.is_dir(), "challenge repository is not packaged")
    def test_player_exports_are_exact_and_private(self):
        with tempfile.TemporaryDirectory() as directory:
            for service in MODEL.SERVICES:
                destination = Path(directory) / service["slug"]
                subprocess.run(
                    [
                        "python3",
                        "tools/export_player_bundle.py",
                        service["slug"],
                        str(destination),
                    ],
                    cwd=CHALLENGE,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                MODEL.verify_player_bundle(destination, service["slug"])
                paths = {
                    path.relative_to(destination).as_posix()
                    for path in destination.rglob("*")
                }
                self.assertFalse(
                    any("checker" in path or "validation" in path for path in paths)
                )

    def test_base_images_are_the_frozen_set(self):
        expected = {
            "python@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f",
            "golang@sha256:972b4110ba0f47539a975c31e52c64765e1ff19f2d74469ae4a595c6676e80a5",
            "debian@sha256:6ebd97fa83deb272194a2cf015b3d26a4d538e9ad3a7a79d544c8af5b0a01443",
            "gcc@sha256:9ca91b05c7b07d2979f16413e8b2cd6ec8a7c80ffca4121ccab0aeba33f90460",
            "alpine@sha256:d406446bc05b82480756ce8f1287964d28768c23955fa9480d2a74a2eae7a654",
            "mcr.microsoft.com/dotnet/sdk@sha256:747cbade5bfd918a175ac32f8f1d931edec2c7d0d5397a3de72eaef1ac1f66d2",
            "mcr.microsoft.com/dotnet/aspnet@sha256:8af87eba5e7cdafb1514d7388be287365da97c132509e84dfe252ffd552398ca",
        }
        self.assertEqual(set(MODEL.BASE_IMAGES), expected)

    def test_release_build_disables_nondeterministic_provenance(self):
        source = (ROOT / "prepare-release.py").read_text()
        self.assertIn('"--provenance=false"', source)

    def test_image_archive_normalization_is_deterministic(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / name for name in ("first.tar", "second.tar")]
            for index, path in enumerate(paths):
                with tarfile.open(path, "w") as archive:
                    for name in (("a", "b"), ("b", "a"))[index]:
                        content = name.encode()
                        info = tarfile.TarInfo(name)
                        info.size = len(content)
                        info.uid = index + 1
                        info.gid = index + 2
                        info.uname = f"user{index}"
                        info.gname = f"group{index}"
                        info.mtime = index + 3
                        archive.addfile(info, io.BytesIO(content))
                PREPARE.normalize_image_archive(path)
            self.assertEqual(paths[0].read_bytes(), paths[1].read_bytes())

    def test_service_subnets_are_fixed_and_disjoint(self):
        self.assertEqual(
            [service["subnet"] for service in MODEL.SERVICES],
            [
                "172.31.60.0/28",
                "172.31.60.16/28",
                "172.31.60.32/28",
                "172.31.60.48/28",
                "172.31.60.64/28",
                "172.31.60.80/28",
            ],
        )

    def test_installer_accepts_nop_team_16(self):
        with (
            patch.object(INSTALLER.os, "geteuid", return_value=0),
            patch.object(
                INSTALLER.sys,
                "argv",
                ["finals-model-a-install", "/release", "16", "a" * 64],
            ),
            patch.object(INSTALLER, "install") as install,
        ):
            self.assertEqual(INSTALLER.main(), 0)
            install.assert_called_once_with(Path("/release"), 16, "a" * 64)
        with (
            patch.object(INSTALLER.os, "geteuid", return_value=0),
            patch.object(
                INSTALLER.sys,
                "argv",
                ["finals-model-a-install", "/release", "17", "a" * 64],
            ),
            patch.object(INSTALLER, "install") as install,
        ):
            self.assertEqual(INSTALLER.main(), 2)
            install.assert_not_called()

    def test_instance_secret_is_private_and_preserved(self):
        for template in MODEL.SERVICES:
            service = dict(template)
            service["uid"] = os.getuid()
            with tempfile.TemporaryDirectory() as directory:
                data = Path(directory)
                INSTALLER.ensure_instance_secret(data, service)
                secret = data / service["secret_name"]
                original = secret.read_bytes()
                expected_size = 64 if service["secret_format"] == "hex" else 32
                self.assertEqual(len(original), expected_size)
                self.assertEqual(secret.stat().st_mode & 0o777, 0o600)
                INSTALLER.ensure_instance_secret(data, service)
                self.assertEqual(secret.read_bytes(), original)
                secret.chmod(0o644)
                with self.assertRaises(MODEL.ModelAError):
                    INSTALLER.ensure_instance_secret(data, service)

    def test_reset_preserves_installed_editable_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            work_root = root / "work"
            factory_root = root / "state/factory"
            slug = "sign-me-in"
            current = work_root / slug
            factory = factory_root / slug
            for tree, value in ((current, "edited"), (factory, "factory")):
                (tree / "service").mkdir(parents=True)
                (tree / "player").mkdir()
                (tree / "compose.yaml").write_text("services: {}\n")
                (tree / "BUNDLE.json").write_text("{}\n")
                (tree / "service/app.py").write_text(value)
            owner = (current / "service").stat()
            with (
                patch.object(CONTROL, "WORK_ROOT", work_root),
                patch.object(CONTROL, "STATE_ROOT", root / "state"),
            ):
                CONTROL.replace_from_factory(slug)
            restored = work_root / slug / "service"
            self.assertEqual((restored / "app.py").read_text(), "factory")
            self.assertEqual(restored.stat().st_uid, owner.st_uid)
            self.assertEqual(restored.stat().st_gid, owner.st_gid)


if __name__ == "__main__":
    unittest.main()
