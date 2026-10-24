import grp
import gzip
import hashlib
import io
import json
import os
import pwd
import subprocess
import tarfile
import tempfile
import textwrap
import unittest
from pathlib import Path

INFRA = Path(__file__).parents[2]
DEPLOYER = INFRA / "terraform/modules/oci-platform/scripts/deploy-anvil-artifact"
BUNDLE_BUILDER = INFRA / "deployment/build-anvil-deploy-bundle.py"
OLD_REVISION = "a" * 40
NEW_REVISION = "b" * 40


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_executable(path, content):
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
    path.chmod(0o755)


class AnvilDeployRuntimeTests(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.project = self.root / "project"
        self.fake_bin = self.root / "bin"
        self.var_tmp = self.root / "var-tmp"
        self.docker_root = self.root / "docker-root"
        for path in (self.project, self.fake_bin, self.var_tmp, self.docker_root):
            path.mkdir()
        self.env_file = self.root / "finals.env"
        self.unit = self.root / "anvil-finals.service"
        self.state = self.root / "docker-state.json"
        self.log = self.root / "calls.log"
        self.old_game = self.root / "old-game.yaml"
        self.new_game = self.root / "new-game.yaml"
        self.migrations = self.root / "migrations"
        self.migrations.mkdir()
        self.old_game.write_text("game: old\n", encoding="utf-8")
        self.new_game.write_text("game: new\n", encoding="utf-8")
        (self.migrations / "1_first.sql").write_text("SELECT 1;\n", encoding="utf-8")
        (self.migrations / "2_second.sql").write_text("SELECT 2;\n", encoding="utf-8")
        (self.project / "game.yaml").write_bytes(self.old_game.read_bytes())
        (self.project / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
        (self.project / "preflight.sh").write_text("fixture preflight\n", encoding="utf-8")
        self.unit.write_text("fixture unit\n", encoding="utf-8")
        self.migration_rows = self.root / "migration-rows"
        self.migration_rows.write_text(self._migration_rows(), encoding="utf-8")
        self._write_env(OLD_REVISION)
        self._write_state(OLD_REVISION)
        self._write_fakes()

    def tearDown(self):
        self.temporary.cleanup()

    def _migration_rows(self):
        rows = []
        for version, path in enumerate(sorted(self.migrations.glob("*.sql")), 1):
            rows.append(f"{version}|{path.name}|{sha256(path)}")
        return "\n".join(rows) + "\n"

    def _write_env(self, revision):
        self.env_file.write_text(f"ANVIL_IMAGE_REVISION={revision}\n", encoding="utf-8")
        self.env_file.chmod(0o600)

    def _write_state(self, revision):
        self.state.write_text(
            json.dumps(
                {
                    "tags": {
                        f"anvil-finals-api:{revision}": "sha256:api-old",
                        f"anvil-finals-web:{revision}": "sha256:web-old",
                    },
                    "containers": {"api": "sha256:api-old", "web": "sha256:web-old"},
                }
            ),
            encoding="utf-8",
        )

    def _write_fakes(self):
        write_executable(
            self.fake_bin / "docker",
            r'''
            #!/usr/bin/env python3
            import json
            import os
            import pathlib
            import sys

            state_path = pathlib.Path(os.environ["FAKE_DOCKER_STATE"])
            env_file = pathlib.Path(os.environ["FAKE_ENV_FILE"])
            target = os.environ["TARGET_REVISION"]
            args = sys.argv[1:]
            with pathlib.Path(os.environ["FAKE_CALL_LOG"]).open("a", encoding="utf-8") as output:
                output.write("docker " + " ".join(args) + "\n")
            state = json.loads(state_path.read_text(encoding="utf-8"))

            def save():
                state_path.write_text(json.dumps(state), encoding="utf-8")

            def revision():
                return next(
                    line.split("=", 1)[1]
                    for line in env_file.read_text(encoding="utf-8").splitlines()
                    if line.startswith("ANVIL_IMAGE_REVISION=")
                )

            if args[0] == "info":
                print(os.environ["FAKE_DOCKER_ROOT"])
                raise SystemExit(0)

            if args[0] == "load":
                source = args[args.index("--input") + 1]
                pathlib.Path(source).read_bytes()
                state["tags"][f"anvil-finals-api:{target}"] = "sha256:api-new"
                save()
                if os.environ.get("FAIL_PARTIAL_LOAD") == "1":
                    raise SystemExit(41)
                state["tags"][f"anvil-finals-web:{target}"] = "sha256:web-new"
                save()
                print(f"Loaded image: anvil-finals-api:{target}")
                print(f"Loaded image: anvil-finals-web:{target}")
                raise SystemExit(0)

            if args[:2] == ["image", "tag"]:
                state["tags"][args[3]] = args[2]
                save()
                raise SystemExit(0)

            if args[:2] == ["image", "inspect"]:
                formatted = "--format" in args
                tags = [arg for arg in args[2:] if arg != "--format" and not arg.startswith("{")]
                if any(tag not in state["tags"] for tag in tags):
                    raise SystemExit(1)
                if formatted:
                    print(state["tags"][tags[-1]])
                raise SystemExit(0)

            if args[0] == "inspect":
                print(state["containers"][args[-1].removesuffix("-container")])
                raise SystemExit(0)

            if args[0] == "compose":
                if "ps" in args:
                    print(args[-1] + "-container")
                    raise SystemExit(0)
                if "exec" in args:
                    sql = args[-1]
                    if "COUNT(*)" in sql:
                        print(2)
                    else:
                        rows = pathlib.Path(os.environ["FAKE_MIGRATION_ROWS"]).read_text(encoding="utf-8")
                        if os.environ.get("FAIL_POST_MIGRATION") == "1" and revision() == target:
                            rows = rows.replace("|", "|changed-", 1)
                        print(rows, end="")
                    raise SystemExit(0)
                if "up" in args:
                    current = revision()
                    state["containers"]["api"] = state["tags"][f"anvil-finals-api:{current}"]
                    state["containers"]["web"] = state["tags"][f"anvil-finals-web:{current}"]
                    save()
                    raise SystemExit(0)
            raise SystemExit(91)
            ''',
        )
        write_executable(
            self.fake_bin / "systemctl",
            r'''
            #!/usr/bin/env bash
            set -eu
            printf 'systemctl %s\n' "$*" >> "$FAKE_CALL_LOG"
            if [[ ${1:-} == show ]]; then printf '%s\n' success; fi
            ''',
        )
        write_executable(
            self.fake_bin / "curl",
            r'''
            #!/usr/bin/env python3
            import os
            import pathlib
            revision = next(
                line.split("=", 1)[1]
                for line in pathlib.Path(os.environ["FAKE_ENV_FILE"]).read_text().splitlines()
                if line.startswith("ANVIL_IMAGE_REVISION=")
            )
            print(
                "500"
                if os.environ.get("FAIL_FORWARD_HEALTH") == "1" and revision == os.environ["TARGET_REVISION"]
                else "200",
                end="",
            )
            ''',
        )
        write_executable(
            self.fake_bin / "preflight",
            r'''
            #!/usr/bin/env bash
            set -eu
            printf 'preflight\n' >> "$FAKE_CALL_LOG"
            ''',
        )
        write_executable(
            self.fake_bin / "install",
            r'''
            #!/usr/bin/env python3
            import os
            import pathlib
            import subprocess
            import sys
            args = sys.argv[1:]
            source, destination = args[-2:]
            if (
                os.environ.get("FAIL_ENV_RESTORE") == "1"
                and source.endswith("finals.env.previous")
                and pathlib.Path(destination) == pathlib.Path(os.environ["FAKE_ENV_FILE"])
            ):
                raise SystemExit(43)
            filtered = []
            index = 0
            while index < len(args):
                if args[index] in {"-o", "-g"}:
                    index += 2
                else:
                    filtered.append(args[index])
                    index += 1
            raise SystemExit(subprocess.run(["/usr/bin/install", *filtered]).returncode)
            ''',
        )

    def _images_archive(self, revision, path, *, valid=True):
        tag_revision = revision if valid else "c" * 40
        manifest = json.dumps(
            [
                {"Config": "api.json", "RepoTags": [f"anvil-finals-api:{tag_revision}"], "Layers": []},
                {"Config": "web.json", "RepoTags": [f"anvil-finals-web:{tag_revision}"], "Layers": []},
            ],
            separators=(",", ":"),
        ).encode()
        raw = io.BytesIO()
        with tarfile.open(fileobj=raw, mode="w", format=tarfile.USTAR_FORMAT) as archive:
            info = tarfile.TarInfo("manifest.json")
            info.size = len(manifest)
            info.mode = 0o600
            info.mtime = 0
            archive.addfile(info, io.BytesIO(manifest))
        with path.open("wb") as destination, gzip.GzipFile(
            fileobj=destination, mode="wb", compresslevel=1, mtime=0
        ) as compressed:
            compressed.write(raw.getvalue())

    def _build_bundle(self, revision, game, name="deploy.bundle"):
        images = self.root / f"images-{revision}.tar.gz"
        self._images_archive(revision, images)
        output = self.root / name
        result = subprocess.run(
            [
                "python3",
                str(BUNDLE_BUILDER),
                revision,
                str(images),
                str(game),
                str(self.migrations),
                str(output),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(json.loads(result.stdout)["sha256"], sha256(output))
        return output

    def _replace(self, source, old, new, count=1):
        self.assertEqual(source.count(old), count, old)
        return source.replace(old, new)

    def _sandbox_deployer(self):
        source = DEPLOYER.read_text(encoding="utf-8")
        bundle = self.var_tmp / "finals-anvil-deploy.bundle"
        source = self._replace(source, "bundle=/var/tmp/finals-anvil-deploy.bundle", f"bundle={bundle}")
        source = self._replace(source, "project=/opt/anvil/current/deployments/finals", f"project={self.project}")
        source = self._replace(source, "env_file=/etc/anvil/finals.env", f"env_file={self.env_file}")
        source = self._replace(
            source,
            "work=$(mktemp -d /var/tmp/finals-anvil-apply.XXXXXX)",
            f"work=$(mktemp -d {self.var_tmp / 'finals-anvil-apply.XXXXXX'})",
        )
        source = self._replace(source, "/etc/systemd/system/anvil-finals.service", str(self.unit))
        source = self._replace(source, "/usr/bin/docker", str(self.fake_bin / "docker"), count=18)
        source = self._replace(
            source,
            '"$project/preflight.sh" "$env_file"',
            f'"{self.fake_bin / "preflight"}" "$env_file"',
            count=2,
        )
        source = self._replace(source, "uncompressed_maximum=2147483648", "uncompressed_maximum=10485760")
        source = self._replace(source, "reserve=2147483648", "reserve=10485760")
        current_user = pwd.getpwuid(os.getuid()).pw_name
        current_group = grp.getgrgid(os.getgid()).gr_name
        source = self._replace(source, "root:root:600", f"{current_user}:{current_group}:600")
        hashes = {
            "2ca0a8155f7e30f822f66d1cf6776423bc5b93d00f2b46392f41ce1d37dfea29": sha256(self.project / "compose.yaml"),
            "b6f50acf91bf456ce6f56a120d474216d8250d24f06d21d4e90ff35f9ef7ce6a": sha256(self.project / "preflight.sh"),
            "4cf189d93e6a4b1bb24ade8370f24a892d207065b87d44175052bdce7d267159": sha256(self.unit),
        }
        for expected, fixture in hashes.items():
            source = self._replace(source, expected, fixture)
        path = self.root / "deploy-sandbox.sh"
        path.write_text(source, encoding="utf-8")
        path.chmod(0o700)
        return path, bundle

    def _run(self, revision=NEW_REVISION, game=None, **flags):
        game = game or self.new_game
        built = self._build_bundle(revision, game, f"{revision}.bundle")
        deployer, bundle = self._sandbox_deployer()
        bundle.write_bytes(built.read_bytes())
        bundle.chmod(0o600)
        environment = os.environ.copy()
        environment.update(
            {
                "PATH": f"{self.fake_bin}:{environment['PATH']}",
                "FAKE_DOCKER_STATE": str(self.state),
                "FAKE_DOCKER_ROOT": str(self.docker_root),
                "FAKE_CALL_LOG": str(self.log),
                "FAKE_ENV_FILE": str(self.env_file),
                "FAKE_MIGRATION_ROWS": str(self.migration_rows),
                "TARGET_REVISION": revision,
            }
        )
        environment.update({name: "1" if value else "0" for name, value in flags.items()})
        return subprocess.run(
            [
                "bash",
                str(deployer),
                revision,
                str(bundle.stat().st_size),
                sha256(bundle),
                sha256(game),
            ],
            env=environment,
            capture_output=True,
            check=False,
            text=True,
            timeout=20,
        )

    def _state_value(self, *keys):
        value = json.loads(self.state.read_text(encoding="utf-8"))
        for key in keys:
            value = value[key]
        return value

    def test_bundle_builder_is_deterministic_and_rejects_wrong_tags(self):
        first = self._build_bundle(NEW_REVISION, self.new_game, "first.bundle")
        second = self._build_bundle(NEW_REVISION, self.new_game, "second.bundle")
        self.assertEqual(first.read_bytes(), second.read_bytes())

        images = self.root / "wrong-images.tar.gz"
        self._images_archive(NEW_REVISION, images, valid=False)
        output = self.root / "wrong.bundle"
        result = subprocess.run(
            [
                "python3",
                str(BUNDLE_BUILDER),
                NEW_REVISION,
                str(images),
                str(self.new_game),
                str(self.migrations),
                str(output),
            ],
            capture_output=True,
            check=False,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not contain exactly the reviewed Anvil tags", result.stderr)
        self.assertFalse(output.exists())

    def test_success_installs_target_and_reports_complete(self):
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"anvil-deploy-revision={NEW_REVISION}", result.stdout)
        self.assertIn("anvil-deploy=complete", result.stdout)
        self.assertNotIn("anvil-deploy-rollback=", result.stderr)
        self.assertEqual(self.env_file.read_text(), f"ANVIL_IMAGE_REVISION={NEW_REVISION}\n")
        self.assertEqual((self.project / "game.yaml").read_bytes(), self.new_game.read_bytes())
        self.assertEqual(self._state_value("containers", "api"), "sha256:api-new")
        self.assertEqual(self._state_value("containers", "web"), "sha256:web-new")

    def test_failed_forward_health_restores_previous_release(self):
        result = self._run(FAIL_FORWARD_HEALTH=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("anvil-deploy-rollback=complete", result.stderr)
        self.assertNotIn("anvil-deploy-rollback=failed", result.stderr)
        self.assertEqual(self.env_file.read_text(), f"ANVIL_IMAGE_REVISION={OLD_REVISION}\n")
        self.assertEqual((self.project / "game.yaml").read_bytes(), self.old_game.read_bytes())
        self.assertEqual(self._state_value("containers", "api"), "sha256:api-old")
        self.assertEqual(self._state_value("containers", "web"), "sha256:web-old")

    def test_rollback_is_armed_before_same_revision_docker_load(self):
        result = self._run(revision=OLD_REVISION, game=self.old_game, FAIL_PARTIAL_LOAD=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("anvil-deploy-rollback=complete", result.stderr)
        self.assertEqual(self._state_value("tags", f"anvil-finals-api:{OLD_REVISION}"), "sha256:api-old")
        self.assertEqual(self._state_value("tags", f"anvil-finals-web:{OLD_REVISION}"), "sha256:web-old")

    def test_restore_failure_cannot_emit_rollback_complete(self):
        result = self._run(FAIL_POST_MIGRATION=True, FAIL_ENV_RESTORE=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("anvil-deploy-rollback=failed", result.stderr)
        self.assertNotIn("anvil-deploy-rollback=complete", result.stderr)


if __name__ == "__main__":
    unittest.main()
