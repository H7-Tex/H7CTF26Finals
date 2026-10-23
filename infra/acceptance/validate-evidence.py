#!/usr/bin/env python3
import argparse
import hashlib
import json
import re
import stat
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath


class AcceptanceError(Exception):
    pass


AD = {
    "AD1": ("sign-me-in", 7001),
    "AD2": ("can-we-settle-this", 7002),
    "AD3": ("update-pending", 7003),
    "AD4": ("book-me-if-you-can", 7004),
    "AD5": ("ship-it", 7005),
    "AD6": ("terms-may-apply", 7006),
}
HILLS = {
    "HILL1": ("current-affairs", 7101, 1),
    "HILL2": ("majority-rules", 7102, 2),
    "HILL3": ("tag-youre-it", 7103, 1),
}
REQUIRED_CHECKS = {
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
}
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")
IMAGE = re.compile(r"sha256:[0-9a-f]{64}\Z")
FLAG = re.compile(rb"H7CTF\{[0-9a-f]{32}\}")
PRIVATE_KEY = re.compile(
    rb"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----|(?:^|\n)PrivateKey\s*=", re.MULTILINE
)
UNMASKED_TOKEN = re.compile(
    rb'(?i)(?:"(?:team_)?token"|x-team-token)\s*[:=]\s*"?[0-9a-f]{64}(?!\.\.\.)'
)


def duplicate_safe_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise AcceptanceError(f"duplicate JSON key {key!r}")
        value[key] = item
    return value


def load_json(path):
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > 4 * 1024 * 1024:
            raise AcceptanceError(
                "evidence manifest must be a regular file no larger than 4 MiB"
            )
        return json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=duplicate_safe_object
        )
    except AcceptanceError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise AcceptanceError(f"cannot read evidence manifest: {error}") from error


def exact(value, expected, label):
    if value != expected:
        raise AcceptanceError(f"{label} must be {expected!r}")


def true(facts, key, label):
    exact(facts.get(key), True, f"{label}.{key}")


def zero(facts, key, label):
    exact(facts.get(key), 0, f"{label}.{key}")


def digest(value, pattern, label):
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise AcceptanceError(f"{label} is not an immutable digest")


def parse_time(value, label):
    if not isinstance(value, str) or not value.endswith("Z"):
        raise AcceptanceError(f"{label} is not UTC RFC3339")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise AcceptanceError(f"{label} is not UTC RFC3339") from error


def validate_inventory(inventory):
    ad = inventory.get("attack_defense") if isinstance(inventory, dict) else None
    hills = inventory.get("hills") if isinstance(inventory, dict) else None
    if not isinstance(ad, list) or len(ad) != 6:
        raise AcceptanceError("inventory must contain exactly six AD services")
    if not isinstance(hills, list) or len(hills) != 3:
        raise AcceptanceError("inventory must contain exactly three Hills")
    seen = set()
    for service in ad:
        if (
            not isinstance(service, dict)
            or service.get("slot") not in AD
            or service["slot"] in seen
        ):
            raise AcceptanceError("AD inventory contains an invalid or duplicate slot")
        seen.add(service["slot"])
        slug, port = AD[service["slot"]]
        exact(service.get("slug"), slug, f"{service['slot']} slug")
        exact(service.get("port"), port, f"{service['slot']} port")
        exact(service.get("stores"), 2, f"{service['slot']} stores")
        digest(service.get("service_image"), IMAGE, f"{service['slot']} service image")
        digest(service.get("checker_image"), IMAGE, f"{service['slot']} checker image")
    exact(seen, set(AD), "AD slots")
    seen.clear()
    for hill in hills:
        if (
            not isinstance(hill, dict)
            or hill.get("slot") not in HILLS
            or hill["slot"] in seen
        ):
            raise AcceptanceError(
                "Hill inventory contains an invalid or duplicate slot"
            )
        seen.add(hill["slot"])
        slug, port, component_count = HILLS[hill["slot"]]
        exact(hill.get("slug"), slug, f"{hill['slot']} slug")
        exact(hill.get("port"), port, f"{hill['slot']} port")
        exact(hill.get("doors"), 5, f"{hill['slot']} doors")
        exact(hill.get("draw"), 3, f"{hill['slot']} draw")
        exact(hill.get("locks_per_holder"), 1, f"{hill['slot']} locks")
        components = hill.get("images")
        if not isinstance(components, list) or len(components) != component_count:
            raise AcceptanceError(
                f"{hill['slot']} image count must be {component_count}"
            )
        for index, image in enumerate(components):
            digest(image, IMAGE, f"{hill['slot']} image {index}")
    exact(seen, set(HILLS), "Hill slots")


def validate_artifact(root, artifact, used_paths):
    if not isinstance(artifact, dict):
        raise AcceptanceError("check artifact is not an object")
    relative = artifact.get("path")
    if (
        not isinstance(relative, str)
        or not relative
        or relative.startswith("/")
        or "\\" in relative
    ):
        raise AcceptanceError("artifact path is not a relative POSIX path")
    pure = PurePosixPath(relative)
    if str(pure) != relative or ".." in pure.parts:
        raise AcceptanceError(f"artifact path {relative!r} is not normalized")
    path = root / relative
    try:
        resolved_root = root.resolve(strict=True)
        resolved = path.resolve(strict=True)
        info = path.lstat()
    except OSError as error:
        raise AcceptanceError(f"artifact {relative!r} is absent") from error
    if (
        resolved_root not in resolved.parents
        or not stat.S_ISREG(info.st_mode)
        or path.is_symlink()
        or info.st_size == 0
        or info.st_size > 128 * 1024 * 1024
    ):
        raise AcceptanceError(
            f"artifact {relative!r} must be a non-empty regular file no larger than 128 MiB"
        )
    current = root
    for part in pure.parts:
        current /= part
        if current.is_symlink():
            raise AcceptanceError(f"artifact {relative!r} contains a symbolic link")
    if relative in used_paths:
        raise AcceptanceError(f"artifact {relative!r} is reused across checks")
    used_paths.add(relative)
    exact(artifact.get("size"), info.st_size, f"artifact {relative!r} size")
    expected = artifact.get("sha256")
    digest(expected, SHA256, f"artifact {relative!r} SHA-256")
    data = path.read_bytes()
    exact(hashlib.sha256(data).hexdigest(), expected, f"artifact {relative!r} SHA-256")
    if FLAG.search(data):
        raise AcceptanceError(f"artifact {relative!r} contains a raw flag")
    if PRIVATE_KEY.search(data):
        raise AcceptanceError(f"artifact {relative!r} contains private-key material")
    if UNMASKED_TOKEN.search(data):
        raise AcceptanceError(f"artifact {relative!r} contains an unmasked team token")


def validate_common_check(root, check, used_paths, now):
    label = check.get("id", "check") if isinstance(check, dict) else "check"
    if not isinstance(check, dict):
        raise AcceptanceError("check is not an object")
    exact(check.get("result"), "green", f"{label} result")
    exact(check.get("exit_code"), 0, f"{label} exit code")
    started = parse_time(check.get("started_at"), f"{label} started_at")
    ended = parse_time(check.get("ended_at"), f"{label} ended_at")
    if (
        ended < started
        or ended - started > timedelta(hours=48)
        or ended > now + timedelta(minutes=5)
    ):
        raise AcceptanceError(f"{label} timestamps are not a credible bounded run")
    artifacts = check.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise AcceptanceError(f"{label} has no attached artifact")
    for artifact in artifacts:
        validate_artifact(root, artifact, used_paths)
    facts = check.get("facts")
    if not isinstance(facts, dict):
        raise AcceptanceError(f"{label} facts are absent")
    return facts


def validate_check(label, facts):
    services = sorted(slug for slug, _ in AD.values())
    if label == "inventory":
        exact(facts.get("ad_count"), 6, "inventory.ad_count")
        exact(facts.get("hill_count"), 3, "inventory.hill_count")
        true(facts, "immutable_images_verified", label)
    elif label == "release-closed":
        true(facts, "admin_visibility", label)
        true(facts, "player_visibility_closed", label)
        true(facts, "unauthenticated_visibility_closed", label)
        exact(
            facts.get("player_material_exports"), 0, f"{label}.player_material_exports"
        )
    elif label == "checker-reference-attack":
        exact(sorted(facts.get("services", [])), services, f"{label}.services")
        exact(facts.get("stores_per_service"), 2, f"{label}.stores_per_service")
        exact(facts.get("previous_flag_ticks"), 5, f"{label}.previous_flag_ticks")
        exact(
            facts.get("reference_schema"),
            "enowars-v2-exploit",
            f"{label}.reference_schema",
        )
        for key in (
            "normalized_ingress",
            "anti_oracle",
            "reference_attack_nop_only",
            "reference_attack_audit_only",
            "reference_attack_excluded_from_sla",
        ):
            true(facts, key, label)
    elif label == "deployment-lifecycle":
        exact(
            sorted(facts.get("services_promoted", [])),
            services,
            f"{label}.services_promoted",
        )
        exact(
            sorted(facts.get("services_manually_rolled_back", [])),
            services,
            f"{label}.services_manually_rolled_back",
        )
        for key in (
            "automatic_rollback_observed",
            "destructive_recovery_separate",
            "events_reconciled",
            "source_sequences_unique",
        ):
            true(facts, key, label)
        zero(facts, "failed_candidates_changed_live", label)
        zero(facts, "rollback_data_snapshot_restores", label)
    elif label == "redaction":
        if (
            not isinstance(facts.get("artifacts_scanned"), int)
            or facts["artifacts_scanned"] < 1
        ):
            raise AcceptanceError("redaction.artifacts_scanned must be positive")
        for key in (
            "raw_flags",
            "private_keys",
            "unmasked_tokens",
            "checker_payloads",
            "reference_attack_payloads",
        ):
            zero(facts, key, label)
    elif label == "backup-restore":
        exact(
            sorted(facts.get("targets", [])),
            ["anvil-postgres", "deployment-state", "gitea"],
            f"{label}.targets",
        )
        for key in (
            "restored_to_new_target",
            "digest_verified",
            "source_preserved",
            "live_path_independent_of_gcp",
        ):
            true(facts, key, label)
    elif label == "gateway-failover":
        exact(facts.get("web_ip"), "129.225.71.11", f"{label}.web_ip")
        exact(facts.get("vpn_ip"), "140.245.253.126", f"{label}.vpn_ip")
        for key in (
            "primary_to_standby",
            "standby_to_primary",
            "dns_unchanged",
            "tcp_443_verified",
            "udp_443_handshake_verified",
        ):
            true(facts, key, label)
    elif label == "one-team-load":
        exact(facts.get("teams"), 1, f"{label}.teams")
        exact(facts.get("services"), 6, f"{label}.services")
        exact(facts.get("candidates"), 6, f"{label}.candidates")
        true(facts, "bounded", label)
        zero(facts, "cross_team_accesses", label)
        zero(facts, "unaccounted_sequences", label)
    elif label == "fifteen-team-load":
        exact(facts.get("teams"), 15, f"{label}.teams")
        exact(facts.get("services"), 6, f"{label}.services")
        exact(facts.get("candidates"), 90, f"{label}.candidates")
        exact(facts.get("factory_restores"), 15, f"{label}.factory_restores")
        true(facts, "bounded", label)
        zero(facts, "cross_team_accesses", label)
        zero(facts, "unaccounted_sequences", label)
    elif label == "two-hundred-round-soak":
        if not isinstance(facts.get("rounds"), int) or facts["rounds"] < 200:
            raise AcceptanceError("two-hundred-round-soak.rounds must be at least 200")
        for key in (
            "round_errors",
            "checker_errors",
            "hill_controller_errors",
            "unreconciled_deployments",
        ):
            zero(facts, key, label)
    elif label == "night-watch-boundaries":
        exact(facts.get("timezone"), "Asia/Kolkata", f"{label}.timezone")
        exact(facts.get("night_start"), "00:00", f"{label}.night_start")
        exact(facts.get("night_end"), "06:00", f"{label}.night_end")
        for key in (
            "ad_continued",
            "active_hills_continued",
            "new_work_deferred",
            "crossing_round_capped",
            "cadence_resumed_at_0600",
        ):
            true(facts, key, label)
    elif label == "secret-isolation":
        for key in (
            "file_secret_modes_verified",
            "rotation_verified",
            "teardown_verified",
            "cross_container_denied",
            "anvil_token_absent_from_challenges",
        ):
            true(facts, key, label)
        zero(facts, "leaks", label)
    elif label == "player-journey":
        expected = [
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
        ]
        exact(facts.get("steps"), expected, f"{label}.steps")
        true(facts, "individual_identity_attributed", label)
        true(facts, "cross_team_denied", label)
    else:
        raise AcceptanceError(f"unknown acceptance check {label!r}")


def validate(document, root, now=None):
    if not isinstance(document, dict):
        raise AcceptanceError("evidence manifest is not an object")
    exact(document.get("schema_version"), 1, "schema_version")
    candidate = document.get("candidate")
    if not isinstance(candidate, dict):
        raise AcceptanceError("candidate is absent")
    for key in ("infrastructure_commit", "anvil_commit", "challenge_commit"):
        digest(candidate.get(key), COMMIT, f"candidate.{key}")
    validate_inventory(document.get("inventory"))
    checks = document.get("checks")
    if not isinstance(checks, list) or len(checks) != len(REQUIRED_CHECKS):
        raise AcceptanceError(
            f"checks must contain exactly {len(REQUIRED_CHECKS)} entries"
        )
    by_id = {}
    for check in checks:
        if not isinstance(check, dict) or check.get("id") in by_id:
            raise AcceptanceError(
                "acceptance checks contain an invalid or duplicate id"
            )
        by_id[check.get("id")] = check
    exact(set(by_id), REQUIRED_CHECKS, "acceptance check ids")
    used_paths = set()
    current = now or datetime.now(timezone.utc)
    for label in sorted(by_id):
        facts = validate_common_check(root, by_id[label], used_paths, current)
        validate_check(label, facts)


def main():
    parser = argparse.ArgumentParser(
        description="Validate the H7CTF Finals closed-staging evidence bundle"
    )
    parser.add_argument("evidence", type=Path)
    arguments = parser.parse_args()
    try:
        path = arguments.evidence.resolve(strict=True)
        document = load_json(path)
        validate(document, path.parent)
    except (AcceptanceError, OSError) as error:
        print(f"closed staging: RED: {error}", file=sys.stderr)
        return 1
    print(
        "closed staging: GREEN: immutable 6+3 release evidence and every production rehearsal passed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
