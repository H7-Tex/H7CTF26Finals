#!/usr/bin/env python3
import argparse
import base64
import binascii
import hashlib
import json
import os
import pwd
import re
import sys
import tempfile
from pathlib import Path

TEAM = re.compile(r"team-(0[1-9]|1[0-5])")
PARTICIPANT = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
CHANGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}")
HOSTS = {f"workbench-{number:02d}": f"team-{number:02d}" for number in range(1, 16)}
HOSTS.update({"admin-workbench": None, "spare-workbench": "spare"})


class AccessError(Exception):
    pass


def duplicate_safe_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise AccessError(f"JSON repeats {key!r}")
        result[key] = value
    return result


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=duplicate_safe_object)
    except AccessError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise AccessError(f"cannot read JSON: {path}") from error


def exact(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise AccessError(f"{label} must contain exactly {', '.join(keys)}")


def parse_key(value, comment):
    if not isinstance(value, str) or "\r" in value or "\n" in value:
        raise AccessError("public key must be one line")
    fields = value.strip().split(maxsplit=2)
    if len(fields) < 2 or fields[0] != "ssh-ed25519":
        raise AccessError("only option-free Ed25519 public keys are accepted")
    try:
        blob = base64.b64decode(fields[1], validate=True)
    except (ValueError, binascii.Error) as error:
        raise AccessError("Ed25519 public key is malformed") from error
    expected = b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20"
    if len(blob) != 51 or not blob.startswith(expected):
        raise AccessError("Ed25519 public key has an invalid wire encoding")
    fingerprint = base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")
    return {
        "fingerprint": f"SHA256:{fingerprint}",
        "authorized_key": f"ssh-ed25519 {fields[1]} {comment}",
    }


def organizer_keys(path):
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise AccessError("cannot read organizer public keys") from error
    values = [line for line in lines if line.strip() and not line.lstrip().startswith("#")]
    if not values:
        raise AccessError("at least one organizer public key is required")
    keys = [parse_key(value, f"organizer-{index}") for index, value in enumerate(values, 1)]
    fingerprints = [key["fingerprint"] for key in keys]
    if len(fingerprints) != len(set(fingerprints)):
        raise AccessError("organizer public key fingerprint is repeated")
    return keys


def validate_manifest(document, organizers):
    exact(document, ("schema_version", "change_id", "teams", "spare_assignment"), "manifest")
    if document["schema_version"] != 1:
        raise AccessError("manifest schema_version must be 1")
    if not isinstance(document["change_id"], str) or not CHANGE.fullmatch(document["change_id"]):
        raise AccessError("change_id is malformed")
    if not isinstance(document["teams"], list):
        raise AccessError("teams must be a list")
    teams = {}
    participants = set()
    fingerprints = {item["fingerprint"] for item in organizers}
    for row in document["teams"]:
        exact(row, ("team", "participants"), "team")
        team = row["team"]
        if not isinstance(team, str) or not TEAM.fullmatch(team) or team in teams:
            raise AccessError("team identity is invalid or repeated")
        if not isinstance(row["participants"], list) or not row["participants"]:
            raise AccessError(f"{team} must contain at least one participant key")
        keys = []
        for participant in row["participants"]:
            exact(participant, ("participant_id", "public_key"), "participant")
            participant_id = participant["participant_id"]
            if not isinstance(participant_id, str) or not PARTICIPANT.fullmatch(participant_id):
                raise AccessError("participant_id is malformed")
            if participant_id in participants:
                raise AccessError(f"participant_id is repeated: {participant_id}")
            participants.add(participant_id)
            key = parse_key(participant["public_key"], f"{participant_id}@{team}")
            if key["fingerprint"] in fingerprints:
                raise AccessError(f"public key fingerprint is repeated: {key['fingerprint']}")
            fingerprints.add(key["fingerprint"])
            keys.append({"participant_id": participant_id, **key})
        teams[team] = keys
    expected = {f"team-{number:02d}" for number in range(1, 16)}
    if set(teams) != expected:
        missing = ", ".join(sorted(expected - set(teams))) or "none"
        extra = ", ".join(sorted(set(teams) - expected)) or "none"
        raise AccessError(f"manifest must contain all 15 teams; missing={missing}; extra={extra}")
    spare = document["spare_assignment"]
    if spare is not None and (not isinstance(spare, str) or not TEAM.fullmatch(spare)):
        raise AccessError("spare_assignment must be null or one team identity")
    return teams


def payload(change_id, host, assignment, organizers, keys):
    return {
        "schema_version": 1,
        "change_id": change_id,
        "host": host,
        "assignment": assignment,
        "organizer_keys": organizers,
        "team_keys": keys,
    }


def atomic_write(path, content, mode=0o600, owner=None):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, mode)
        if owner is not None:
            os.fchown(descriptor, *owner)
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def compile_manifest(manifest_path, organizer_path, output_dir):
    organizers = organizer_keys(organizer_path)
    document = read_json(manifest_path)
    teams = validate_manifest(document, organizers)
    output = Path(output_dir)
    if output.exists() and any(output.iterdir()):
        raise AccessError("output directory must be absent or empty")
    (output / "payloads").mkdir(parents=True, mode=0o700)
    values = {
        team: "\n".join(key["authorized_key"] for key in keys)
        for team, keys in sorted(teams.items())
    }
    tfvars = {"team_workbench_ssh_authorized_keys": values}
    atomic_write(output / "team-workbench-ssh-authorized-keys.auto.tfvars.json", (json.dumps(tfvars, sort_keys=True, indent=2) + "\n").encode())
    inventory = []
    for team, keys in sorted(teams.items()):
        host = f"workbench-{team.removeprefix('team-')}"
        item = payload(document["change_id"], host, team, organizers, keys)
        atomic_write(output / "payloads" / f"{host}.json", (json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n").encode())
        inventory.extend({"team": team, "participant_id": key["participant_id"], "fingerprint": key["fingerprint"]} for key in keys)
    # model a: the same keys for the team's production box, organizer first. the
    # operator prepends "production-NN apply" and the box's verified host-key line.
    for team, keys in sorted(teams.items()):
        lines = authorized_content(organizers, keys)
        atomic_write(output / "payloads" / f"production-{team.removeprefix('team-')}.authorized_keys", lines)
    spare = document["spare_assignment"]
    spare_keys = teams[spare] if spare else []
    item = payload(document["change_id"], "spare-workbench", spare, organizers, spare_keys)
    atomic_write(output / "payloads" / "spare-workbench.json", (json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n").encode())
    audit = {"schema_version": 1, "change_id": document["change_id"], "spare_assignment": spare, "participants": inventory}
    atomic_write(output / "fingerprints.json", (json.dumps(audit, sort_keys=True, indent=2) + "\n").encode())
    return output


def validated_payload(document, hostname):
    exact(document, ("schema_version", "change_id", "host", "assignment", "organizer_keys", "team_keys"), "payload")
    if document["schema_version"] != 1 or not isinstance(document["change_id"], str) or not CHANGE.fullmatch(document["change_id"]):
        raise AccessError("payload identity is invalid")
    host = document["host"]
    if host not in HOSTS or hostname != host.replace("-", ""):
        raise AccessError("payload host does not match this workbench")
    assignment = document["assignment"]
    expected = HOSTS[host]
    if expected == "spare":
        if assignment is not None and (not isinstance(assignment, str) or not TEAM.fullmatch(assignment)):
            raise AccessError("spare assignment is invalid")
    elif assignment != expected:
        raise AccessError("fixed workbench assignment cannot change")
    if not isinstance(document["organizer_keys"], list) or not document["organizer_keys"]:
        raise AccessError("payload has no organizer keys")
    if not isinstance(document["team_keys"], list) or (assignment is not None and not document["team_keys"]):
        raise AccessError("assigned workbench has no team keys")
    if assignment is None and document["team_keys"]:
        raise AccessError("unassigned workbench must not contain team keys")
    seen = set()
    organizers = []
    for index, item in enumerate(document["organizer_keys"], 1):
        exact(item, ("fingerprint", "authorized_key"), "organizer key")
        key = parse_key(item["authorized_key"], f"organizer-{index}")
        if item != key or key["fingerprint"] in seen:
            raise AccessError("organizer key is non-canonical or repeated")
        seen.add(key["fingerprint"])
        organizers.append(key)
    team_keys = []
    participant_ids = set()
    for item in document["team_keys"]:
        exact(item, ("participant_id", "fingerprint", "authorized_key"), "team key")
        participant_id = item["participant_id"]
        if not isinstance(participant_id, str) or not PARTICIPANT.fullmatch(participant_id) or participant_id in participant_ids:
            raise AccessError("team participant identity is invalid or repeated")
        participant_ids.add(participant_id)
        key = parse_key(item["authorized_key"], f"{participant_id}@{assignment}")
        if item != {"participant_id": participant_id, **key} or key["fingerprint"] in seen:
            raise AccessError("team key is non-canonical or repeated")
        seen.add(key["fingerprint"])
        team_keys.append(item)
    return {**document, "organizer_keys": organizers, "team_keys": team_keys}


def root_paths(root):
    root = Path(root)
    return {
        "authorized": root / "home/ubuntu/.ssh/authorized_keys",
        "state": root / "var/lib/finals-team-access/current.json",
        "previous": root / "var/lib/finals-team-access/previous.json",
        "organizers": root / "etc/finals-team-access/organizer_keys.json",
    }


def authorized_content(organizers, team_keys):
    lines = [item["authorized_key"] for item in organizers]
    lines.extend(item["authorized_key"] for item in team_keys)
    return ("\n".join(lines) + "\n").encode()


def apply_payload(document, root="/", hostname=None, owner=None):
    hostname = hostname or os.uname().nodename.split(".", 1)[0]
    document = validated_payload(document, hostname)
    paths = root_paths(root)
    if owner is None:
        entry = pwd.getpwnam("ubuntu")
        owner = (entry.pw_uid, entry.pw_gid)
    pinned = paths["organizers"]
    organizers_json = (json.dumps(document["organizer_keys"], sort_keys=True, separators=(",", ":")) + "\n").encode()
    if pinned.exists():
        if pinned.read_bytes() != organizers_json:
            raise AccessError("organizer break-glass keys cannot be changed by team reconciliation")
    else:
        existing = paths["authorized"].read_text(encoding="utf-8").splitlines() if paths["authorized"].exists() else []
        required = {item["authorized_key"].split(maxsplit=2)[1] for item in document["organizer_keys"]}
        present = {line.split(maxsplit=2)[1] for line in existing if line.startswith("ssh-ed25519 ") and len(line.split(maxsplit=2)) >= 2}
        if not required <= present:
            raise AccessError("initial organizer keys are not present in authorized_keys")
        atomic_write(pinned, organizers_json)
    state_content = (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if paths["state"].exists() and paths["state"].read_bytes() == state_content:
        return False
    if paths["state"].exists():
        atomic_write(paths["previous"], paths["state"].read_bytes())
    atomic_write(paths["authorized"], authorized_content(document["organizer_keys"], document["team_keys"]), owner=owner)
    os.chmod(paths["authorized"].parent, 0o700)
    os.chown(paths["authorized"].parent, *owner)
    atomic_write(paths["state"], state_content)
    return True


def rollback(root="/", hostname=None, owner=None):
    paths = root_paths(root)
    if not paths["previous"].is_file() or not paths["state"].is_file() or not paths["organizers"].is_file():
        raise AccessError("no complete previous access state exists")
    previous = json.loads(paths["previous"].read_text(encoding="utf-8"), object_pairs_hook=duplicate_safe_object)
    hostname = hostname or os.uname().nodename.split(".", 1)[0]
    previous = validated_payload(previous, hostname)
    pinned = json.loads(paths["organizers"].read_text(encoding="utf-8"), object_pairs_hook=duplicate_safe_object)
    if previous["organizer_keys"] != pinned:
        raise AccessError("previous state does not preserve organizer break-glass keys")
    current = paths["state"].read_bytes()
    if owner is None:
        entry = pwd.getpwnam("ubuntu")
        owner = (entry.pw_uid, entry.pw_gid)
    atomic_write(paths["authorized"], authorized_content(pinned, previous["team_keys"]), owner=owner)
    atomic_write(paths["state"], paths["previous"].read_bytes())
    atomic_write(paths["previous"], current)
    return previous


def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    compile_parser = subparsers.add_parser("compile")
    compile_parser.add_argument("--manifest", required=True)
    compile_parser.add_argument("--organizer-keys", required=True)
    compile_parser.add_argument("--output", required=True)
    subparsers.add_parser("apply")
    subparsers.add_parser("rollback")
    args = parser.parse_args()
    try:
        if args.command == "compile":
            output = compile_manifest(args.manifest, args.organizer_keys, args.output)
            print(output)
        elif args.command == "apply":
            document = json.load(sys.stdin, object_pairs_hook=duplicate_safe_object)
            changed = apply_payload(document)
            print(f"team access {'updated' if changed else 'unchanged'}: {document['change_id']} {document['host']}")
        else:
            document = rollback()
            print(f"team access rolled back: {document['change_id']} {document['host']}")
    except (AccessError, OSError, UnicodeError, json.JSONDecodeError) as error:
        print(f"team access refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
