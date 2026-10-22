import importlib.util
import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "credential_sync.py"
SPEC = importlib.util.spec_from_file_location("hill_credentials", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def identifiers(offset):
    return [str(uuid.UUID(int=offset + index)) for index in range(15)]


def config_document(role="hill-01", challenge_id=None, team_ids=None):
    return {
        "schema_version": 1,
        "role": role,
        "slug": MODULE.HILLS[role][0],
        "hill_id": str(uuid.UUID(int=1)),
        "challenge_id": challenge_id or str(uuid.UUID(int=2)),
        "team_ids": team_ids or identifiers(100),
    }


def response_document(config, reset="a" * 48, token_prefix="a"):
    teams = []
    for index, team_id in enumerate(sorted(config.team_ids)):
        token = "hill_" + (token_prefix + f"{index:031x}")[-32:]
        teams.append({
            "team_id": team_id,
            "holder": MODULE.expected_holder(config.challenge_id, team_id),
            "bearer_token": token,
        })
    return {
        "protocol": "hill-v2-http",
        "challenge_id": config.challenge_id,
        "reset_token": reset,
        "teams": teams,
    }


class HillCredentialTests(unittest.TestCase):
    def setUp(self):
        document = config_document()
        self.config = MODULE.parse_config(
            json.dumps(document).encode(),
            json.dumps({"role": document["role"]}).encode(),
        )

    def install(self, root, document):
        root.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        root.parent.chmod(0o700)
        reset, teams = MODULE.credential_files(document, self.config)
        return MODULE.install_credentials(
            reset,
            teams,
            root,
            owner_uid=os.getuid(),
            owner_gid=os.getgid(),
        )

    def test_exact_response_becomes_only_the_two_controller_files(self):
        reset, teams = MODULE.credential_files(response_document(self.config), self.config)
        self.assertEqual(reset, b"a" * 48 + b"\n")
        decoded = json.loads(teams)
        self.assertEqual(len(decoded), 15)
        self.assertEqual(set(decoded.values()), {
            MODULE.expected_holder(self.config.challenge_id, team_id)
            for team_id in self.config.team_ids
        })

    def test_wrong_hill_team_holder_and_reset_are_rejected_without_echoing_secrets(self):
        cases = []
        wrong_hill = response_document(self.config)
        wrong_hill["challenge_id"] = str(uuid.UUID(int=999))
        cases.append(wrong_hill)
        wrong_team = response_document(self.config)
        wrong_team["teams"][0]["team_id"] = str(uuid.UUID(int=999))
        cases.append(wrong_team)
        wrong_holder = response_document(self.config)
        wrong_holder["teams"][0]["holder"] = "team-ffffffffffffffff"
        cases.append(wrong_holder)
        wrong_reset = response_document(self.config)
        wrong_reset["reset_token"] = "RESET_SECRET_MUST_NOT_BE_ECHOED"
        cases.append(wrong_reset)
        duplicate = response_document(self.config)
        duplicate["teams"][1]["bearer_token"] = duplicate["teams"][0]["bearer_token"]
        cases.append(duplicate)
        for document in cases:
            with self.subTest(document=document["challenge_id"]):
                with self.assertRaises(MODULE.CredentialError) as raised:
                    MODULE.credential_files(document, self.config)
                message = str(raised.exception)
                self.assertNotIn("RESET_SECRET", message)
                self.assertNotIn("hill_", message)

    def test_same_generation_is_idempotent_and_rotation_never_mixes_pairs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "run/finals-hill/credentials"
            first = response_document(self.config, reset="a" * 48, token_prefix="a")
            second = response_document(self.config, reset="b" * 48, token_prefix="b")
            self.assertTrue(self.install(root, first))
            initial_target = os.readlink(root / "current")
            self.assertFalse(self.install(root, first))
            self.assertEqual(os.readlink(root / "current"), initial_target)
            self.assertTrue(self.install(root, second))
            rotated_target = os.readlink(root / "current")
            self.assertNotEqual(rotated_target, initial_target)
            self.assertFalse((root / initial_target).exists())
            reset, teams = MODULE.credential_files(second, self.config)
            self.assertEqual((root / rotated_target / "hill_reset").read_bytes(), reset)
            self.assertEqual((root / rotated_target / "hill_teams").read_bytes(), teams)
            self.assertEqual({path.name for path in (root / rotated_target).iterdir()}, {"hill_reset", "hill_teams"})
            MODULE.check_current(self.config, root, os.getuid(), os.getgid())

    def test_local_tamper_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "run/finals-hill/credentials"
            self.install(root, response_document(self.config))
            target = root / os.readlink(root / "current") / "hill_teams"
            target.chmod(0o644)
            with self.assertRaisesRegex(MODULE.CredentialError, "unsafe metadata"):
                MODULE.check_current(self.config, root, os.getuid(), os.getgid())

    def test_config_requires_matching_role_and_exact_team_set(self):
        document = config_document()
        with self.assertRaisesRegex(MODULE.CredentialError, "fixed host role"):
            MODULE.parse_config(json.dumps(document).encode(), b'{"role":"hill-02"}')
        document["slug"] = "majority-rules"
        with self.assertRaisesRegex(MODULE.CredentialError, "fixed hill slot"):
            MODULE.parse_config(json.dumps(document).encode(), b'{"role":"hill-01"}')
        document["slug"] = "current-affairs"
        document["team_ids"] = document["team_ids"][:-1]
        with self.assertRaisesRegex(MODULE.CredentialError, "exactly 15"):
            MODULE.parse_config(json.dumps(document).encode(), b'{"role":"hill-01"}')

    def test_load_config_accepts_only_the_root_owned_public_role_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.json"
            role_path = root / "role"
            config_path.write_text(json.dumps(config_document()), encoding="utf-8")
            role_path.write_text('{"role":"hill-01"}\n', encoding="utf-8")
            config_path.chmod(0o600)
            role_path.chmod(0o644)
            loaded = MODULE.load_config(config_path, role_path, os.getuid(), os.getgid())
            self.assertEqual(loaded.slug, "current-affairs")
            role_path.chmod(0o666)
            with self.assertRaisesRegex(MODULE.CredentialError, "unsafe metadata"):
                MODULE.load_config(config_path, role_path, os.getuid(), os.getgid())

    def test_duplicate_json_fields_and_response_bodies_never_reach_errors(self):
        with self.assertRaisesRegex(MODULE.CredentialError, "duplicate"):
            MODULE.strict_json(b'{"reset_token":"DO_NOT_LOG","reset_token":"DO_NOT_LOG_2"}')

        class Response:
            status = 503

            def read(self, _):
                return b'{"reset_token":"DO_NOT_LOG_RESPONSE"}'

            def getheader(self, name, default=""):
                return {
                    "Content-Type": "application/json",
                    "Cache-Control": "no-store",
                }.get(name, default)

        class Connection:
            def __init__(self, *_args, **_kwargs):
                pass

            def request(self, *_args, **_kwargs):
                pass

            def getresponse(self):
                return Response()

            def close(self):
                pass

        original = MODULE.PrivateHTTPSConnection
        MODULE.PrivateHTTPSConnection = Connection
        try:
            with self.assertRaises(MODULE.CredentialError) as raised:
                MODULE.fetch_credentials(self.config, "DO_NOT_LOG_REQUEST_TOKEN" * 2)
        finally:
            MODULE.PrivateHTTPSConnection = original
        self.assertNotIn("DO_NOT_LOG", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
