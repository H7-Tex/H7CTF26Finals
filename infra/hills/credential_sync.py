#!/usr/bin/env python3
import fcntl
import hashlib
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import stat
import sys
import uuid
from pathlib import Path


ANVIL_HOST = "finals.h7tex.com"
ANVIL_ADDRESS = "10.60.200.10"
CONFIG_PATH = Path("/etc/finals-hill/config.json")
ROLE_PATH = Path("/etc/finals-platform/role")
TOKEN_PATH = Path("/etc/finals-hill/anvil.token")
CREDENTIAL_ROOT = Path("/run/finals-hill/credentials")
MAX_RESPONSE_BYTES = 32768
HILLS = {
    "hill-01": ("current-affairs", 7101),
    "hill-02": ("majority-rules", 7102),
    "hill-03": ("tag-youre-it", 7103),
}
RESET_TOKEN = re.compile(r"^[0-9a-f]{48}$")
BEARER_TOKEN = re.compile(r"^hill_[A-Za-z0-9_-]{32}$")
HOLDER = re.compile(r"^team-[0-9a-f]{16}$")
GENERATION = re.compile(r"^generations/generation-[0-9a-f]{32}$")


class CredentialError(Exception):
    pass


class Config:
    def __init__(self, role, slug, hill_id, challenge_id, team_ids):
        self.role = role
        self.slug = slug
        self.hill_id = hill_id
        self.challenge_id = challenge_id
        self.team_ids = frozenset(team_ids)


def canonical_uuid(value):
    if not isinstance(value, str):
        raise CredentialError("configuration contains an invalid identifier")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as error:
        raise CredentialError("configuration contains an invalid identifier") from error
    if str(parsed) != value:
        raise CredentialError("configuration contains a non-canonical identifier")
    return value


def strict_json(data):
    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise CredentialError("JSON contains duplicate fields")
            result[key] = value
        return result

    try:
        return json.loads(data, object_pairs_hook=object_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CredentialError("JSON is malformed") from error


def private_file(path, maximum, owner_uid=0, owner_gid=0):
    try:
        info = path.lstat()
    except OSError as error:
        raise CredentialError("required private file is unavailable") from error
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != owner_uid
        or info.st_gid != owner_gid
        or stat.S_IMODE(info.st_mode) & 0o077
        or info.st_size < 1
        or info.st_size > maximum
    ):
        raise CredentialError("required private file has unsafe metadata")
    try:
        return path.read_bytes()
    except OSError as error:
        raise CredentialError("required private file cannot be read") from error


def trusted_role_file(path, maximum, owner_uid=0, owner_gid=0):
    try:
        info = path.lstat()
    except OSError as error:
        raise CredentialError("fixed host role is unavailable") from error
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != owner_uid
        or info.st_gid != owner_gid
        or stat.S_IMODE(info.st_mode) != 0o644
        or info.st_size < 1
        or info.st_size > maximum
    ):
        raise CredentialError("fixed host role has unsafe metadata")
    try:
        return path.read_bytes()
    except OSError as error:
        raise CredentialError("fixed host role cannot be read") from error


def parse_config(data, role_data):
    document = strict_json(data)
    role_document = strict_json(role_data)
    if not isinstance(document, dict) or set(document) != {
        "schema_version", "role", "slug", "hill_id", "challenge_id", "team_ids"
    }:
        raise CredentialError("configuration fields are not exact")
    if not isinstance(role_document, dict) or set(role_document) != {"role"}:
        raise CredentialError("host role is invalid")
    role = document["role"]
    if document["schema_version"] != 1 or role not in HILLS or role_document["role"] != role:
        raise CredentialError("configuration does not match the fixed host role")
    slug = document["slug"]
    if slug != HILLS[role][0]:
        raise CredentialError("configuration does not match the fixed hill slot")
    hill_id = canonical_uuid(document["hill_id"])
    challenge_id = canonical_uuid(document["challenge_id"])
    team_ids = document["team_ids"]
    if not isinstance(team_ids, list) or len(team_ids) != 15:
        raise CredentialError("configuration must contain exactly 15 teams")
    canonical_teams = [canonical_uuid(team_id) for team_id in team_ids]
    if len(set(canonical_teams)) != len(canonical_teams):
        raise CredentialError("configuration contains duplicate teams")
    return Config(role, slug, hill_id, challenge_id, canonical_teams)


def load_config(config_path=CONFIG_PATH, role_path=ROLE_PATH, owner_uid=0, owner_gid=0):
    return parse_config(
        private_file(config_path, 65536, owner_uid, owner_gid),
        trusted_role_file(role_path, 256, owner_uid, owner_gid),
    )


def read_token(path=TOKEN_PATH, owner_uid=0, owner_gid=0):
    raw = private_file(path, 4096, owner_uid, owner_gid)
    try:
        value = raw.decode("ascii").strip()
    except UnicodeDecodeError as error:
        raise CredentialError("internal authentication is malformed") from error
    if not 32 <= len(value) <= 4096 or not re.fullmatch(r"[A-Za-z0-9_./:@+,=-]+", value):
        raise CredentialError("internal authentication is malformed")
    return value


class PrivateHTTPSConnection(http.client.HTTPSConnection):
    def connect(self):
        raw = socket.create_connection((ANVIL_ADDRESS, self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=ANVIL_HOST)
        except Exception:
            raw.close()
            raise
        peer = ipaddress.ip_address(self.sock.getpeername()[0])
        if peer != ipaddress.ip_address(ANVIL_ADDRESS):
            self.close()
            raise CredentialError("internal TLS peer is not the fixed private address")


def fetch_credentials(config, token):
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    connection = PrivateHTTPSConnection(ANVIL_HOST, 443, timeout=10, context=context)
    path = f"/api/v1/internal/arena/hills/{config.hill_id}/credentials"
    try:
        connection.request(
            "POST",
            path,
            body=b"",
            headers={
                "Authorization": "Bearer " + token,
                "Accept": "application/json",
                "Content-Length": "0",
            },
        )
        response = connection.getresponse()
        data = response.read(MAX_RESPONSE_BYTES + 1)
        media_type = response.getheader("Content-Type", "").split(";", 1)[0].strip().lower()
        cache_control = {value.strip().lower() for value in response.getheader("Cache-Control", "").split(",")}
        if response.status != 200:
            raise CredentialError(f"Anvil rejected credential synchronization with status {response.status}")
        if media_type != "application/json" or "no-store" not in cache_control or len(data) > MAX_RESPONSE_BYTES:
            raise CredentialError("Anvil returned an invalid bounded response")
        return strict_json(data)
    except CredentialError:
        raise
    except (OSError, ssl.SSLError, http.client.HTTPException) as error:
        raise CredentialError("private TLS credential synchronization failed") from error
    finally:
        connection.close()


def expected_holder(challenge_id, team_id):
    digest = hashlib.sha256(f"hill-v2:{challenge_id}:{team_id}".encode()).hexdigest()
    return "team-" + digest[:16]


def credential_files(document, config):
    if not isinstance(document, dict) or set(document) != {
        "protocol", "challenge_id", "reset_token", "teams"
    }:
        raise CredentialError("credential response fields are not exact")
    if document["protocol"] != "hill-v2-http" or document["challenge_id"] != config.challenge_id:
        raise CredentialError("credential response does not match the configured hill")
    reset = document["reset_token"]
    if not isinstance(reset, str) or not RESET_TOKEN.fullmatch(reset):
        raise CredentialError("credential response contains an invalid reset credential")
    teams = document["teams"]
    if not isinstance(teams, list) or len(teams) != len(config.team_ids):
        raise CredentialError("credential response does not match the commissioned team set")
    seen_teams = set()
    seen_holders = set()
    bearer_to_holder = {}
    for entry in teams:
        if not isinstance(entry, dict) or set(entry) != {"team_id", "holder", "bearer_token"}:
            raise CredentialError("credential response contains an invalid team entry")
        team_id = entry["team_id"]
        holder = entry["holder"]
        bearer = entry["bearer_token"]
        if (
            not isinstance(team_id, str)
            or team_id not in config.team_ids
            or team_id in seen_teams
            or not isinstance(holder, str)
            or not HOLDER.fullmatch(holder)
            or holder != expected_holder(config.challenge_id, team_id)
            or holder in seen_holders
            or not isinstance(bearer, str)
            or not BEARER_TOKEN.fullmatch(bearer)
            or bearer in bearer_to_holder
            or bearer == reset
        ):
            raise CredentialError("credential response contains mismatched team credentials")
        seen_teams.add(team_id)
        seen_holders.add(holder)
        bearer_to_holder[bearer] = holder
    if seen_teams != config.team_ids:
        raise CredentialError("credential response does not match the commissioned team set")
    reset_file = (reset + "\n").encode("ascii")
    teams_file = (json.dumps(bearer_to_holder, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
    return reset_file, teams_file


def ensure_directory(path, mode, owner_uid, owner_gid):
    try:
        info = path.lstat()
    except FileNotFoundError:
        path.mkdir(mode=mode)
        os.chown(path, owner_uid, owner_gid)
        info = path.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != owner_uid
        or info.st_gid != owner_gid
        or stat.S_IMODE(info.st_mode) != mode
    ):
        raise CredentialError("credential directory has unsafe metadata")


def read_generation(root, owner_uid, owner_gid):
    current = root / "current"
    try:
        target = os.readlink(current)
    except FileNotFoundError:
        return None, None
    except OSError as error:
        raise CredentialError("active credential generation is invalid") from error
    if not GENERATION.fullmatch(target):
        raise CredentialError("active credential generation is invalid")
    generation = root / target
    try:
        info = generation.lstat()
        names = {entry.name for entry in generation.iterdir()}
    except OSError as error:
        raise CredentialError("active credential generation is unavailable") from error
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != owner_uid
        or info.st_gid != owner_gid
        or stat.S_IMODE(info.st_mode) != 0o700
        or names != {"hill_reset", "hill_teams"}
    ):
        raise CredentialError("active credential generation has unsafe metadata")
    values = []
    for name in ("hill_reset", "hill_teams"):
        path = generation / name
        file_info = path.lstat()
        if (
            not stat.S_ISREG(file_info.st_mode)
            or file_info.st_uid != owner_uid
            or file_info.st_gid != owner_gid
            or stat.S_IMODE(file_info.st_mode) != 0o444
            or file_info.st_size < 1
            or file_info.st_size > MAX_RESPONSE_BYTES
        ):
            raise CredentialError("active credential file has unsafe metadata")
        values.append(path.read_bytes())
    return target, tuple(values)


def write_file(path, content, owner_uid, owner_gid):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o444)
    try:
        os.fchmod(descriptor, 0o444)
        os.fchown(descriptor, owner_uid, owner_gid)
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise


def fsync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def install_credentials(reset_file, teams_file, root=CREDENTIAL_ROOT, owner_uid=0, owner_gid=0):
    ensure_directory(root.parent, 0o700, owner_uid, owner_gid)
    ensure_directory(root, 0o700, owner_uid, owner_gid)
    generations = root / "generations"
    ensure_directory(generations, 0o700, owner_uid, owner_gid)
    lock_path = root.parent / "credentials.lock"
    lock_descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(lock_descriptor, 0o600)
        os.fchown(lock_descriptor, owner_uid, owner_gid)
        fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
        old_target, old_values = read_generation(root, owner_uid, owner_gid)
        if old_values == (reset_file, teams_file):
            return False
        name = "generation-" + uuid.uuid4().hex
        generation = generations / name
        generation.mkdir(mode=0o700)
        os.chown(generation, owner_uid, owner_gid)
        temporary = None
        try:
            write_file(generation / "hill_reset", reset_file, owner_uid, owner_gid)
            write_file(generation / "hill_teams", teams_file, owner_uid, owner_gid)
            fsync_directory(generation)
            temporary = root / (".current-" + uuid.uuid4().hex)
            os.symlink("generations/" + name, temporary)
            os.replace(temporary, root / "current")
            fsync_directory(root)
        except Exception:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            for path in (generation / "hill_reset", generation / "hill_teams"):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
            try:
                generation.rmdir()
            except OSError:
                pass
            raise
        if old_target and old_target != "generations/" + name:
            old = root / old_target
            for path in (old / "hill_reset", old / "hill_teams"):
                path.unlink(missing_ok=True)
            old.rmdir()
        return True
    finally:
        os.close(lock_descriptor)


def check_current(config, root=CREDENTIAL_ROOT, owner_uid=0, owner_gid=0):
    _, values = read_generation(root, owner_uid, owner_gid)
    if values is None:
        raise CredentialError("hill credentials are not installed")
    try:
        reset = values[0].decode("ascii").strip()
        teams = strict_json(values[1])
    except UnicodeDecodeError as error:
        raise CredentialError("installed hill credentials are malformed") from error
    expected_holders = {expected_holder(config.challenge_id, team_id) for team_id in config.team_ids}
    if (
        not RESET_TOKEN.fullmatch(reset)
        or not isinstance(teams, dict)
        or len(teams) != len(config.team_ids)
        or set(teams.values()) != expected_holders
        or any(not isinstance(token, str) or not BEARER_TOKEN.fullmatch(token) for token in teams)
    ):
        raise CredentialError("installed hill credentials do not match the commissioned hill")


def main(argv):
    if os.geteuid() != 0 or len(argv) != 2 or argv[1] not in {"sync", "check"}:
        print("usage: finals-hill-credentials {sync|check}", file=sys.stderr)
        return 2
    try:
        config = load_config()
        if argv[1] == "check":
            check_current(config)
            print("hill credentials are ready")
            return 0
        token = read_token()
        reset_file, teams_file = credential_files(fetch_credentials(config, token), config)
        changed = install_credentials(reset_file, teams_file)
        print("hill credentials synchronized" if changed else "hill credentials already current")
        return 0
    except CredentialError as error:
        print(f"hill credential operation failed: {error}", file=sys.stderr)
        return 1
    except Exception:
        print("hill credential operation failed: internal error", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
