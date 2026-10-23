import copy
import hashlib
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "validate-evidence.py"
SPEC = importlib.util.spec_from_file_location("acceptance", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AcceptanceTests(unittest.TestCase):
    def fixture(self, directory, model="C"):
        root = Path(directory)
        image = "sha256:" + "1" * 64
        ad = [
            {
                "slot": slot,
                "slug": slug,
                "port": port,
                "stores": 2,
                "service_image": image,
                "checker_image": image,
            }
            for slot, (slug, port) in MODULE.AD.items()
        ]
        hills = [
            {
                "slot": slot,
                "slug": slug,
                "port": port,
                "doors": 5,
                "draw": 3,
                "locks_per_holder": 1,
                "images": [image] * component_count,
            }
            for slot, (slug, port, component_count) in MODULE.HILLS.items()
        ]
        services = sorted(slug for slug, _ in MODULE.AD.values())
        facts = {
            "inventory": {
                "ad_count": 6,
                "hill_count": 3,
                "immutable_images_verified": True,
            },
            "release-closed": {
                "admin_visibility": True,
                "player_visibility_closed": True,
                "unauthenticated_visibility_closed": True,
                "player_material_exports": 0,
            },
            "checker-reference-attack": {
                "services": services.copy(),
                "stores_per_service": 2,
                "previous_flag_ticks": 5,
                "reference_schema": "enowars-v2-exploit",
                "normalized_ingress": True,
                "anti_oracle": True,
                "reference_attack_nop_only": True,
                "reference_attack_audit_only": True,
                "reference_attack_excluded_from_sla": True,
            },
            "deployment-lifecycle": {
                "services_promoted": services.copy(),
                "services_manually_rolled_back": services.copy(),
                "automatic_rollback_observed": True,
                "destructive_recovery_separate": True,
                "events_reconciled": True,
                "source_sequences_unique": True,
                "failed_candidates_changed_live": 0,
                "rollback_data_snapshot_restores": 0,
            },
            "redaction": {
                "artifacts_scanned": 13,
                "raw_flags": 0,
                "private_keys": 0,
                "unmasked_tokens": 0,
                "checker_payloads": 0,
                "reference_attack_payloads": 0,
            },
            "backup-restore": {
                "targets": ["anvil-postgres", "deployment-state", "gitea"],
                "restored_to_new_target": True,
                "digest_verified": True,
                "source_preserved": True,
                "live_path_independent_of_gcp": True,
            },
            "gateway-failover": {
                "web_ip": "129.225.71.11",
                "vpn_ip": "140.245.253.126",
                "primary_to_standby": True,
                "standby_to_primary": True,
                "dns_unchanged": True,
                "tcp_443_verified": True,
                "udp_443_handshake_verified": True,
            },
            "one-team-load": {
                "teams": 1,
                "services": 6,
                "candidates": 6,
                "bounded": True,
                "cross_team_accesses": 0,
                "unaccounted_sequences": 0,
            },
            "fifteen-team-load": {
                "teams": 15,
                "services": 6,
                "candidates": 90,
                "factory_restores": 15,
                "bounded": True,
                "cross_team_accesses": 0,
                "unaccounted_sequences": 0,
            },
            "two-hundred-round-soak": {
                "rounds": 200,
                "round_errors": 0,
                "checker_errors": 0,
                "hill_controller_errors": 0,
                "unreconciled_deployments": 0,
            },
            "night-watch-boundaries": {
                "timezone": "Asia/Kolkata",
                "night_start": "00:00",
                "night_end": "06:00",
                "ad_continued": True,
                "active_hills_continued": True,
                "new_work_deferred": True,
                "crossing_round_capped": True,
                "cadence_resumed_at_0600": True,
            },
            "secret-isolation": {
                "file_secret_modes_verified": True,
                "rotation_verified": True,
                "teardown_verified": True,
                "cross_container_denied": True,
                "anvil_token_absent_from_challenges": True,
                "leaks": 0,
            },
            "player-journey": {
                "steps": [
                    "vpn",
                    "workbench",
                    "local-test",
                    "attack",
                    "flag-submit",
                    "patch",
                    "rejection",
                    "promotion",
                    "rollback",
                    "hill-claim",
                    "hill-lock",
                ],
                "individual_identity_attributed": True,
                "cross_team_denied": True,
            },
            "production-key-access": {
                "teams": 15,
                "username": "ubuntu",
                "access_enabled": True,
                "access_revoked": True,
                "old_keys_removed": True,
                "ed25519_keys_only": True,
                "fingerprints_unique": True,
                "team_key_attribution_verified": True,
                "organizer_breakglass_preserved": True,
                "password_authentication_disabled": True,
                "root_login_disabled": True,
            },
            "anvil-backup-restore": {
                "targets": ["anvil-postgres"],
                "restored_to_new_target": True,
                "digest_verified": True,
                "source_preserved": True,
                "live_path_independent_of_gcp": True,
                "login_verified": True,
                "game_state_verified": True,
            },
            "model-a-one-team-recovery": {
                "teams": 1,
                "services": 6,
                "production_reset_or_reimage_observed": True,
                "fixed_ip_preserved": True,
                "service_data_preserved": True,
                "access_reestablished": True,
                "services_healthy": True,
                "cross_team_accesses": 0,
            },
            "model-a-fifteen-team-isolation": {
                "teams": 15,
                "successful_own_team_ssh": 15,
                "production_ssh_port": 22,
                "cross_team_ssh_attempts": 210,
                "cross_team_ssh_successes": 0,
                "vpn_peer_attribution_verified": True,
                "organizer_management_isolated": True,
            },
            "model-a-player-journey": {
                "steps": [
                    "vpn",
                    "production-ssh",
                    "attack",
                    "flag-submit",
                    "patch",
                    "service-restart",
                    "checker-recovery",
                    "hill-claim",
                    "hill-lock",
                    "access-revocation",
                ],
                "individual_identity_attributed": True,
                "own_production_only": True,
                "cross_team_denied": True,
                "service_data_preserved": True,
            },
        }
        checks = []
        for index, label in enumerate(sorted(MODULE.REQUIRED_CHECKS[model])):
            artifact = root / f"{label}.log"
            artifact.write_text(f"{label} completed\n", encoding="utf-8")
            data = artifact.read_bytes()
            checks.append(
                {
                    "id": label,
                    "result": "green",
                    "exit_code": 0,
                    "started_at": "2026-10-23T00:00:00Z",
                    "ended_at": "2026-10-23T00:01:00Z",
                    "artifacts": [
                        {
                            "path": artifact.name,
                            "size": len(data),
                            "sha256": hashlib.sha256(data).hexdigest(),
                        }
                    ],
                    "facts": facts[label],
                }
            )
        return {
            "schema_version": 1,
            "model": model,
            "candidate": {
                "infrastructure_commit": "1" * 40,
                "anvil_commit": "2" * 40,
                "challenge_commit": "3" * 40,
            },
            "inventory": {"attack_defense": ad, "hills": hills},
            "checks": checks,
        }

    def validate(self, document, root):
        MODULE.validate(
            document, Path(root), now=datetime(2026, 10, 23, 1, tzinfo=timezone.utc)
        )

    def check(self, document, label):
        return next(item for item in document["checks"] if item["id"] == label)

    def rewrite_artifact(self, check, root, content):
        artifact = check["artifacts"][0]
        path = Path(root) / artifact["path"]
        path.write_bytes(content)
        artifact["size"] = len(content)
        artifact["sha256"] = hashlib.sha256(content).hexdigest()

    def test_complete_bundle_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            self.validate(self.fixture(directory), directory)

    def test_complete_model_a_bundle_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            self.validate(self.fixture(directory, "A"), directory)

    def test_profiles_are_exact_and_model_c_contract_is_unchanged(self):
        self.assertEqual(
            MODULE.REQUIRED_CHECKS["C"],
            {
                "inventory",
                "release-closed",
                "checker-reference-attack",
                "deployment-lifecycle",
                "redaction",
                "backup-restore",
                "gateway-failover",
                "one-team-load",
                "fifteen-team-load",
                "two-hundred-round-soak",
                "night-watch-boundaries",
                "secret-isolation",
                "player-journey",
            },
        )
        self.assertEqual(len(MODULE.REQUIRED_CHECKS["A"]), 13)

    def test_model_is_explicit_and_known(self):
        with tempfile.TemporaryDirectory() as directory:
            document = self.fixture(directory)
            document.pop("model")
            with self.assertRaisesRegex(MODULE.AcceptanceError, "model"):
                self.validate(document, directory)
            document["model"] = "B"
            with self.assertRaisesRegex(MODULE.AcceptanceError, "model"):
                self.validate(document, directory)

    def test_cross_profile_check_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            document = self.fixture(directory, "A")
            self.check(document, "production-key-access")["id"] = "deployment-lifecycle"
            with self.assertRaisesRegex(MODULE.AcceptanceError, "model A"):
                self.validate(document, directory)

    def test_model_a_requires_key_revocation(self):
        with tempfile.TemporaryDirectory() as directory:
            document = self.fixture(directory, "A")
            self.check(document, "production-key-access")["facts"]["access_revoked"] = (
                False
            )
            with self.assertRaisesRegex(MODULE.AcceptanceError, "access_revoked"):
                self.validate(document, directory)

    def test_model_a_rejects_cross_team_ssh(self):
        with tempfile.TemporaryDirectory() as directory:
            document = self.fixture(directory, "A")
            self.check(document, "model-a-fifteen-team-isolation")["facts"][
                "cross_team_ssh_successes"
            ] = 1
            with self.assertRaisesRegex(
                MODULE.AcceptanceError, "cross_team_ssh_successes"
            ):
                self.validate(document, directory)

    def test_model_a_requires_recovery_to_preserve_ip_and_data(self):
        with tempfile.TemporaryDirectory() as directory:
            document = self.fixture(directory, "A")
            facts = self.check(document, "model-a-one-team-recovery")["facts"]
            facts["fixed_ip_preserved"] = False
            with self.assertRaisesRegex(MODULE.AcceptanceError, "fixed_ip_preserved"):
                self.validate(document, directory)
            facts["fixed_ip_preserved"] = True
            facts["service_data_preserved"] = False
            with self.assertRaisesRegex(
                MODULE.AcceptanceError, "service_data_preserved"
            ):
                self.validate(document, directory)

    def test_model_a_restore_is_anvil_only(self):
        with tempfile.TemporaryDirectory() as directory:
            document = self.fixture(directory, "A")
            self.check(document, "anvil-backup-restore")["facts"]["targets"].append(
                "gitea"
            )
            with self.assertRaisesRegex(MODULE.AcceptanceError, "targets"):
                self.validate(document, directory)

    def test_inventory_drift_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            document = self.fixture(directory)
            document["inventory"]["attack_defense"][0]["stores"] = 3
            with self.assertRaisesRegex(MODULE.AcceptanceError, "stores"):
                self.validate(document, directory)

    def test_missing_check_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            document = self.fixture(directory)
            document["checks"].pop()
            with self.assertRaisesRegex(MODULE.AcceptanceError, "exactly 13"):
                self.validate(document, directory)

    def test_open_player_visibility_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            document = self.fixture(directory)
            self.check(document, "release-closed")["facts"][
                "player_visibility_closed"
            ] = False
            with self.assertRaisesRegex(
                MODULE.AcceptanceError, "player_visibility_closed"
            ):
                self.validate(document, directory)

    def test_incomplete_deployment_matrix_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            document = self.fixture(directory)
            self.check(document, "deployment-lifecycle")["facts"][
                "services_promoted"
            ].pop()
            with self.assertRaisesRegex(MODULE.AcceptanceError, "services_promoted"):
                self.validate(document, directory)

    def test_raw_flag_in_transcript_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            document = self.fixture(directory)
            check = self.check(document, "redaction")
            self.rewrite_artifact(
                check, directory, b"leak H7CTF{0123456789abcdef0123456789abcdef}\n"
            )
            with self.assertRaisesRegex(MODULE.AcceptanceError, "raw flag"):
                self.validate(document, directory)

    def test_unmasked_token_in_transcript_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            document = self.fixture(directory)
            check = self.check(document, "redaction")
            self.rewrite_artifact(
                check, directory, b'X-Team-Token: "' + b"a" * 64 + b'"\n'
            )
            with self.assertRaisesRegex(MODULE.AcceptanceError, "unmasked team token"):
                self.validate(document, directory)

    def test_reused_artifact_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            document = self.fixture(directory)
            document["checks"][1]["artifacts"] = copy.deepcopy(
                document["checks"][0]["artifacts"]
            )
            with self.assertRaisesRegex(MODULE.AcceptanceError, "reused"):
                self.validate(document, directory)

    def test_symlinked_artifact_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            document = self.fixture(directory)
            check = self.check(document, "redaction")
            artifact = check["artifacts"][0]
            path = Path(directory) / artifact["path"]
            target = Path(directory) / "real.log"
            path.replace(target)
            path.symlink_to(target)
            with self.assertRaisesRegex(
                MODULE.AcceptanceError, "regular file|symbolic link"
            ):
                self.validate(document, directory)

    def test_duplicate_json_keys_fail(self):
        with self.assertRaisesRegex(MODULE.AcceptanceError, "duplicate JSON key"):
            json.loads(
                '{"schema_version":1,"schema_version":1}',
                object_pairs_hook=MODULE.duplicate_safe_object,
            )


if __name__ == "__main__":
    unittest.main()
