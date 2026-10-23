import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "validate-challenge-contract.py"
SPEC = importlib.util.spec_from_file_location("challenge_contract", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
PLATFORM_ROOT = Path(__file__).parents[3]


def write(path, content="x\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class ChallengeContractTests(unittest.TestCase):
    def fixture(self, directory):
        root = Path(directory)
        checker = json.loads((PLATFORM_ROOT / "infra/checkers/artifact-manifest.example.json").read_text())
        release = json.loads((PLATFORM_ROOT / "infra/deployment/release.template.json").read_text())
        release_by_slot = {service["slot"]: service for service in release["services"]}
        for expected in checker["services"]:
            service = release_by_slot[expected["slot"]]
            challenge = root / "services" / expected["slug"]
            for allowed in service["build"]["allowed_paths"]:
                if allowed.endswith("/"):
                    write(challenge / allowed / "source.txt")
                else:
                    write(challenge / allowed)
            write(challenge / "player/README.md")
            write(challenge / "player/client.py")
            variants = []
            for index in range(4):
                reference = f"validation/attacks/v{index}.py"
                correct = f"validation/patches/v{index}.patch"
                wrong = f"validation/patches/v{index}-wrong.patch"
                for path in (reference, correct, wrong):
                    write(challenge / path)
                variants.append({
                    "id": f"v{index}",
                    "store": index % 2,
                    "reference": reference,
                    "correct_patch": correct,
                    "wrong_patches": [wrong],
                })
            manifest = {
                "schema_version": 2,
                "kind": "attack-defense-service",
                "slot": expected["slot"],
                "name": expected["name"],
                "slug": expected["slug"],
                "endpoint": {"protocol": service["protocol"], "port": expected["target_port"]},
                "stores": [{"index": 0}, {"index": 1}],
                "checker": {
                    "protocol": "enowars-v2-http",
                    "noise_variants": expected["noise_variants"],
                    "havoc_variants": expected["havoc_variants"],
                    "timeout_ms": expected["timeout_ms"],
                },
                "patch": {"allow": service["build"]["allowed_paths"]},
                "player": {"include": service["build"]["allowed_paths"] + ["player/README.md", "player/client.py"]},
                "runtime": {
                    "state_paths": ["/data"],
                    "outbound_network": False,
                    "user": service["runtime"]["uid"],
                    "resources": {
                        "cpus": service["runtime"]["cpu_millis"] / 1000,
                        "memory_mb": service["runtime"]["memory_bytes"] // (1024 * 1024),
                        "pids": service["runtime"]["pids"],
                        "storage_mb": service["quota"]["bytes"] // (1024 * 1024),
                    },
                },
                "variants": variants,
            }
            (challenge / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return root, checker, release

    def test_six_service_contract_matches_and_quota_drift_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root, checker, release = self.fixture(directory)
            MODULE.validate_ad(root, checker, release)
            path = root / "services/sign-me-in/manifest.json"
            document = json.loads(path.read_text())
            document["runtime"]["resources"]["storage_mb"] += 1
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(MODULE.ContractError, "storage quota"):
                MODULE.validate_ad(root, checker, release)

    def test_direct_private_player_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write(root / "validation/attack.py")
            with self.assertRaisesRegex(MODULE.ContractError, "private path"):
                MODULE.validate_player_export(root, ["validation/attack.py"], "fixture")

    def test_nested_player_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write(root / "outside/secret.txt")
            (root / "service").mkdir()
            (root / "service/link").symlink_to(root / "outside", target_is_directory=True)
            with self.assertRaisesRegex(MODULE.ContractError, "symbolic link"):
                MODULE.validate_player_export(root, ["service/"], "fixture")

    def test_secret_sources_preserve_file_targets(self):
        service = {"secrets": [
            {"source": "hill_reset", "target": "/run/secrets/hill_reset"},
            {"source": "hill_teams", "target": "/run/secrets/hill_teams"},
        ]}
        self.assertEqual(MODULE.secret_sources(service), {
            "hill_reset": "/run/secrets/hill_reset",
            "hill_teams": "/run/secrets/hill_teams",
        })


if __name__ == "__main__":
    unittest.main()
