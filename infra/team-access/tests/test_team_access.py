import base64
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "team-access.py"
SPEC = importlib.util.spec_from_file_location("team_access", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def public_key(seed, comment="key"):
    blob = b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20" + bytes([seed]) * 32
    return f"ssh-ed25519 {base64.b64encode(blob).decode()} {comment}"


def manifest():
    return {
        "schema_version": 1,
        "change_id": "ticket-100",
        "teams": [
            {
                "team": f"team-{number:02d}",
                "participants": [{"participant_id": f"player-{number:02d}", "public_key": public_key(number)}],
            }
            for number in range(1, 16)
        ],
        "spare_assignment": None,
    }


class CompileTests(unittest.TestCase):
    def compile(self, document):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        source = root / "manifest.json"
        organizer = root / "organizer.pub"
        output = root / "output"
        source.write_text(json.dumps(document), encoding="utf-8")
        organizer.write_text(public_key(100, "organizer") + "\n", encoding="utf-8")
        MODULE.compile_manifest(source, organizer, output)
        return temporary, output

    def test_complete_manifest_builds_exact_terraform_map_and_payloads(self):
        _, output = self.compile(manifest())
        variables = json.loads((output / "team-workbench-ssh-authorized-keys.auto.tfvars.json").read_text())
        self.assertEqual(set(variables["team_workbench_ssh_authorized_keys"]), {f"team-{number:02d}" for number in range(1, 16)})
        self.assertEqual(len(list((output / "payloads").glob("*.json"))), 16)
        audit = json.loads((output / "fingerprints.json").read_text())
        self.assertEqual(len(audit["participants"]), 15)
        self.assertNotIn("public_key", json.dumps(audit))

    def test_malformed_key_is_rejected(self):
        document = manifest()
        document["teams"][0]["participants"][0]["public_key"] = "ssh-rsa invalid"
        with self.assertRaisesRegex(MODULE.AccessError, "Ed25519"):
            self.compile(document)

    def test_duplicate_key_across_teams_is_rejected(self):
        document = manifest()
        document["teams"][1]["participants"][0]["public_key"] = document["teams"][0]["participants"][0]["public_key"]
        with self.assertRaisesRegex(MODULE.AccessError, "fingerprint is repeated"):
            self.compile(document)

    def test_participant_key_matching_organizer_is_rejected(self):
        document = manifest()
        document["teams"][0]["participants"][0]["public_key"] = public_key(100)
        with self.assertRaisesRegex(MODULE.AccessError, "fingerprint is repeated"):
            self.compile(document)

    def test_duplicate_organizer_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "organizers.pub"
            path.write_text(public_key(100) + "\n" + public_key(100) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(MODULE.AccessError, "fingerprint is repeated"):
                MODULE.organizer_keys(path)

    def test_missing_team_is_rejected(self):
        document = manifest()
        document["teams"].pop()
        with self.assertRaisesRegex(MODULE.AccessError, "all 15 teams"):
            self.compile(document)

    def test_last_minute_replacement_changes_only_one_team(self):
        _, before = self.compile(manifest())
        document = manifest()
        document["change_id"] = "ticket-101"
        document["teams"][4]["participants"][0]["public_key"] = public_key(50)
        _, after = self.compile(document)
        old = json.loads((before / "team-workbench-ssh-authorized-keys.auto.tfvars.json").read_text())["team_workbench_ssh_authorized_keys"]
        new = json.loads((after / "team-workbench-ssh-authorized-keys.auto.tfvars.json").read_text())["team_workbench_ssh_authorized_keys"]
        changed = {team for team in old if old[team] != new[team]}
        self.assertEqual(changed, {"team-05"})
        self.assertNotIn(old["team-05"].split()[1], new["team-05"])


class ReconcileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.owner = (os.getuid(), os.getgid())
        self.authorized = self.root / "home/ubuntu/.ssh/authorized_keys"
        self.authorized.parent.mkdir(parents=True)
        self.organizer = MODULE.parse_key(public_key(100), "organizer-1")
        self.old = {"participant_id": "old", **MODULE.parse_key(public_key(1), "old@team-01")}
        self.authorized.write_text(self.organizer["authorized_key"] + "\n" + self.old["authorized_key"] + "\n")

    def tearDown(self):
        self.temporary.cleanup()

    def payload(self, change, host="workbench-01", assignment="team-01", key=None):
        keys = [] if key is None and assignment is None else [key or self.old]
        return MODULE.payload(change, host, assignment, [self.organizer], keys)

    def test_apply_pins_organizer_and_replacement_removes_old_key(self):
        self.assertTrue(MODULE.apply_payload(self.payload("ticket-1"), self.root, "workbench01", self.owner))
        replacement = {"participant_id": "new", **MODULE.parse_key(public_key(2), "new@team-01")}
        self.assertTrue(MODULE.apply_payload(self.payload("ticket-2", key=replacement), self.root, "workbench01", self.owner))
        content = self.authorized.read_text()
        self.assertIn(self.organizer["authorized_key"], content)
        self.assertIn(replacement["authorized_key"], content)
        self.assertNotIn(self.old["authorized_key"], content)
        self.assertEqual(self.authorized.stat().st_mode & 0o777, 0o600)

    def test_changed_organizer_is_rejected_after_pin(self):
        MODULE.apply_payload(self.payload("ticket-1"), self.root, "workbench01", self.owner)
        changed = self.payload("ticket-2")
        changed["organizer_keys"] = [MODULE.parse_key(public_key(101), "organizer-1")]
        with self.assertRaisesRegex(MODULE.AccessError, "cannot be changed"):
            MODULE.apply_payload(changed, self.root, "workbench01", self.owner)

    def test_fixed_workbench_cannot_be_reassigned(self):
        changed = self.payload("ticket-1", assignment="team-02")
        changed["team_keys"] = [{"participant_id": "old", **MODULE.parse_key(public_key(1), "old@team-02")}]
        with self.assertRaisesRegex(MODULE.AccessError, "cannot change"):
            MODULE.apply_payload(changed, self.root, "workbench01", self.owner)

    def test_spare_reassignment_and_rollback_are_reversible(self):
        assigned_key = {"participant_id": "old", **MODULE.parse_key(public_key(1), "old@team-01")}
        assigned = self.payload("ticket-1", "spare-workbench", "team-01", assigned_key)
        MODULE.apply_payload(assigned, self.root, "spareworkbench", self.owner)
        unassigned = self.payload("ticket-2", "spare-workbench", None)
        MODULE.apply_payload(unassigned, self.root, "spareworkbench", self.owner)
        self.assertNotIn(assigned_key["authorized_key"], self.authorized.read_text())
        restored = MODULE.rollback(self.root, "spareworkbench", self.owner)
        self.assertEqual(restored["assignment"], "team-01")
        self.assertIn(assigned_key["authorized_key"], self.authorized.read_text())
        self.assertIn(self.organizer["authorized_key"], self.authorized.read_text())

    def test_unassigned_spare_rejects_team_keys(self):
        document = self.payload("ticket-1", "spare-workbench", None)
        document["team_keys"] = [self.old]
        with self.assertRaisesRegex(MODULE.AccessError, "must not contain"):
            MODULE.apply_payload(document, self.root, "spareworkbench", self.owner)


if __name__ == "__main__":
    unittest.main()
