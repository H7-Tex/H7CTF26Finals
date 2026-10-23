#!/usr/bin/env python3
import argparse
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath


class ContractError(Exception):
    pass


def duplicate_safe_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def load_json(path, label):
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > 1024 * 1024:
            raise ContractError(f"{label} must be a regular file no larger than 1 MiB")
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=duplicate_safe_object)
    except ContractError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ContractError(f"cannot read {label}: {error}") from error


def exact(value, expected, label):
    if value != expected:
        raise ContractError(f"{label} does not match the platform contract")


def scaled_number(value, scale, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{label} is not numeric")
    return int(value * scale)


def normalized_relative(value, label):
    if not isinstance(value, str) or not value or value.startswith("/") or "\\" in value:
        raise ContractError(f"{label} is not a relative POSIX path")
    candidate = value[:-1] if value.endswith("/") else value
    if str(PurePosixPath(candidate)) != candidate or ".." in PurePosixPath(candidate).parts:
        raise ContractError(f"{label} is not normalized")


def require_path(root, value, label):
    normalized_relative(value, label)
    target = root / value
    try:
        resolved_root = root.resolve(strict=True)
        resolved = target.resolve(strict=True)
    except OSError as error:
        raise ContractError(f"{label} is absent") from error
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise ContractError(f"{label} escapes its challenge directory")
    current = root
    for part in PurePosixPath(value.rstrip("/")).parts:
        current /= part
        if current.is_symlink():
            raise ContractError(f"{label} contains a symbolic link")
    return target


def validate_player_export(challenge_root, includes, label):
    if not isinstance(includes, list) or not includes or len(set(includes)) != len(includes):
        raise ContractError(f"{label} player include list is empty or duplicated")
    forbidden_parts = {".git", "__pycache__", "validation", "checker", "checkers", "attacks", "patches"}
    forbidden_names = {"manifest.json", "compose.yaml", "docker-compose.yaml", "docker-compose.yml"}
    for include in includes:
        target = require_path(challenge_root, include, f"{label} player include {include!r}")
        paths = [target] if target.is_file() else target.rglob("*")
        for path in paths:
            relative = path.relative_to(challenge_root)
            if path.is_symlink():
                raise ContractError(f"{label} player include exposes symbolic link {relative}")
            if not path.is_file():
                continue
            denied = forbidden_parts.intersection(relative.parts) or path.name in forbidden_names or path.suffix in {".pyc", ".pyo"}
            if target.is_file() and denied:
                raise ContractError(f"{label} player include exposes private path {relative}")


def compose_document(path, overrides=()):
    command = ["docker", "compose", "-f", str(path)]
    for override in overrides:
        command.extend(("-f", str(override)))
    command.extend(("config", "--format", "json"))
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
        return json.loads(result.stdout, object_pairs_hook=duplicate_safe_object)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        raise ContractError(f"cannot render Compose contract {path}") from error


def secret_sources(service):
    secrets = service.get("secrets") or []
    return {item.get("source"): item.get("target") for item in secrets if isinstance(item, dict)}


def validate_ad(challenge_root, checker_contract, release_contract):
    manifests = sorted((challenge_root / "services").glob("*/manifest.json"))
    if len(manifests) != 6:
        raise ContractError("challenge tree must contain exactly six AD manifests")
    challenge_by_slot = {}
    for path in manifests:
        document = load_json(path, f"AD manifest {path.parent.name}")
        slot = document.get("slot")
        if slot in challenge_by_slot:
            raise ContractError(f"duplicate AD slot {slot}")
        challenge_by_slot[slot] = (path.parent, document)
    checker_by_slot = {service["slot"]: service for service in checker_contract["services"]}
    release_by_slot = {service["slot"]: service for service in release_contract["services"]}
    exact(set(challenge_by_slot), {f"AD{number}" for number in range(1, 7)}, "AD slots")
    exact(set(checker_by_slot), set(challenge_by_slot), "checker slots")
    exact(set(release_by_slot), set(challenge_by_slot), "deployment slots")

    for slot in sorted(challenge_by_slot):
        root, challenge = challenge_by_slot[slot]
        checker = checker_by_slot[slot]
        release = release_by_slot[slot]
        label = challenge.get("slug", slot)
        exact(challenge.get("schema_version"), 2, f"{label} schema")
        exact(challenge.get("kind"), "attack-defense-service", f"{label} kind")
        for key in ("slot", "name", "slug"):
            exact(challenge.get(key), checker[key], f"{label} {key}")
        endpoint = challenge.get("endpoint") or {}
        exact(endpoint.get("port"), checker["target_port"], f"{label} checker port")
        exact(endpoint.get("port"), release["port"], f"{label} deployment port")
        exact(endpoint.get("protocol"), release["protocol"], f"{label} protocol")
        stores = challenge.get("stores")
        if not isinstance(stores, list) or len(stores) != 2 or {store.get("index") for store in stores if isinstance(store, dict)} != {0, 1}:
            raise ContractError(f"{label} must define exactly two indexed stores")
        exact(checker["flag_stores"], 2, f"{label} checker store count")
        challenge_checker = challenge.get("checker") or {}
        exact(challenge_checker.get("protocol"), "enowars-v2-http", f"{label} checker protocol")
        for key in ("noise_variants", "havoc_variants", "timeout_ms"):
            exact(challenge_checker.get(key), checker[key], f"{label} checker {key}")
        patch_paths = (challenge.get("patch") or {}).get("allow")
        exact(patch_paths, release["build"]["allowed_paths"], f"{label} patchable paths")
        for path in patch_paths or []:
            require_path(root, path, f"{label} patchable path {path!r}")
        validate_player_export(root, (challenge.get("player") or {}).get("include"), label)
        runtime = challenge.get("runtime") or {}
        resources = runtime.get("resources") or {}
        exact(runtime.get("state_paths"), ["/data"], f"{label} state paths")
        exact(runtime.get("outbound_network"), False, f"{label} outbound network")
        exact(runtime.get("user"), release["runtime"]["uid"], f"{label} runtime UID")
        exact(scaled_number(resources.get("cpus"), 1000, f"{label} CPU"), release["runtime"]["cpu_millis"], f"{label} CPU")
        exact(scaled_number(resources.get("memory_mb"), 1024 * 1024, f"{label} memory"), release["runtime"]["memory_bytes"], f"{label} memory")
        exact(resources.get("pids"), release["runtime"]["pids"], f"{label} PIDs")
        exact(scaled_number(resources.get("storage_mb"), 1024 * 1024, f"{label} storage quota"), release["quota"]["bytes"], f"{label} storage quota")
        if release.get("previous_flag_ticks") != 5 or set(release.get("generations", {})) != {"live", "gate", "recovery"}:
            raise ContractError(f"{label} lifecycle retention contract is incomplete")
        if any(release.get(key) != "" for key in ("base_commit", "bundle_sha256", "factory_image", "private_gate_artifact")):
            raise ContractError(f"{label} template contains release identity bytes")
        base_images = release["build"].get("base_images")
        if not isinstance(base_images, list) or not base_images:
            raise ContractError(f"{label} has no pinned build inputs")
        for image in base_images:
            if not isinstance(image, str) or not re.fullmatch(r"[^@]+@sha256:[0-9a-f]{64}", image):
                raise ContractError(f"{label} build input is not digest-pinned")
        variants = challenge.get("variants")
        if not isinstance(variants, list) or len(variants) != 4 or not all(isinstance(variant, dict) for variant in variants):
            raise ContractError(f"{label} must contain four private attack variants")
        if {variant.get("store") for variant in variants if isinstance(variant, dict)} != {0, 1}:
            raise ContractError(f"{label} attack variants do not cover both stores")
        for variant in variants:
            require_path(root, variant.get("reference"), f"{label} reference attack")
            require_path(root, variant.get("correct_patch"), f"{label} correct patch")
            wrong = variant.get("wrong_patches")
            if not isinstance(wrong, list) or not wrong:
                raise ContractError(f"{label} variant has no incomplete patch")
            for path in wrong:
                require_path(root, path, f"{label} incomplete patch")


def validate_hills(challenge_root, credentials_override):
    expected = {
        "HILL1": ("current-affairs", 7101, 11001, 512, 160, 512),
        "HILL2": ("majority-rules", 7102, 11002, 1536, 192, 1024),
        "HILL3": ("tag-youre-it", 7103, 11003, 768, 160, 2048),
    }
    manifests = sorted((challenge_root / "hills").glob("*/manifest.json"))
    if len(manifests) != 3:
        raise ContractError("challenge tree must contain exactly three Hill manifests")
    seen = set()
    for path in manifests:
        root = path.parent
        challenge = load_json(path, f"Hill manifest {root.name}")
        slot = challenge.get("slot")
        if slot not in expected or slot in seen:
            raise ContractError(f"invalid or duplicate Hill slot {slot}")
        seen.add(slot)
        slug, port, uid, memory_mb, pids, storage_mb = expected[slot]
        label = challenge.get("slug", slot)
        exact(challenge.get("schema_version"), 2, f"{label} schema")
        exact(challenge.get("kind"), "adaptive-hill", f"{label} kind")
        exact(challenge.get("slug"), slug, f"{label} slug")
        endpoint = challenge.get("endpoint") or {}
        exact(endpoint.get("protocol"), "http", f"{label} protocol")
        exact(endpoint.get("port"), port, f"{label} port")
        exact(challenge.get("rounds"), {"implemented_doors": 5, "draw": 3, "locks_per_holder": 1}, f"{label} rounds")
        controller = challenge.get("controller") or {}
        exact(controller.get("protocol"), "hill-v2-http", f"{label} controller protocol")
        for key in ("status_path", "claim_path", "lock_path", "reset_path"):
            if not isinstance(controller.get(key), str) or not controller[key].startswith("/"):
                raise ContractError(f"{label} controller {key} is invalid")
        doors = challenge.get("doors")
        if not isinstance(doors, list) or not all(isinstance(door, dict) for door in doors) or [door.get("id") for door in doors] != [f"d{number}" for number in range(1, 6)]:
            raise ContractError(f"{label} must define doors d1 through d5")
        for door in doors:
            require_path(root, door.get("reference"), f"{label} door reference")
            require_path(root, door.get("correct_patch"), f"{label} door patch")
        validate_player_export(root, (challenge.get("player") or {}).get("include"), label)
        runtime = challenge.get("runtime") or {}
        resources = runtime.get("resources") or {}
        exact(runtime.get("outbound_network"), False, f"{label} outbound network")
        exact(runtime.get("user"), uid, f"{label} runtime UID")
        exact(resources.get("memory_mb"), memory_mb, f"{label} memory")
        exact(resources.get("pids"), pids, f"{label} PIDs")
        exact(resources.get("storage_mb"), storage_mb, f"{label} storage")

        compose_path = root / "compose.yaml"
        base = compose_document(compose_path)
        combined = compose_document(compose_path, (credentials_override,))
        services = base.get("services") or {}
        expected_services = {"arena", "evm"} if slug == "majority-rules" else {"arena"}
        exact(set(services), expected_services, f"{label} Compose services")
        exact(secret_sources(services["arena"]), {
            "hill_reset": "/run/secrets/hill_reset",
            "hill_teams": "/run/secrets/hill_teams",
        }, f"{label} arena secrets")
        if services["arena"].get("ports"):
            raise ContractError(f"{label} base Compose must not publish a host port")
        serialized = json.dumps(combined, sort_keys=True)
        if "ANVIL_GAME_INTERNAL_TOKEN" in serialized:
            raise ContractError(f"{label} Compose exposes the Anvil internal token")
        exact(secret_sources(combined["services"]["arena"]), {
            "hill_reset": "/run/secrets/hill_reset",
            "hill_teams": "/run/secrets/hill_teams",
        }, f"{label} commissioned arena secrets")
        if slug == "majority-rules":
            exact(secret_sources(services["evm"]), {
                "hill_evm_mnemonic": "/run/secrets/hill_evm_mnemonic",
            }, f"{label} EVM secrets")
            if services["evm"].get("environment"):
                raise ContractError(f"{label} EVM secret must not enter the environment")


def validate(challenge_root, platform_root):
    checker = load_json(platform_root / "infra/checkers/artifact-manifest.example.json", "checker contract")
    release = load_json(platform_root / "infra/deployment/release.template.json", "deployment contract")
    if checker.get("version") != 2 or len(checker.get("services", [])) != 6:
        raise ContractError("checker contract is not the locked six-service v2 schema")
    if release.get("schema_version") != 1 or len(release.get("services", [])) != 6:
        raise ContractError("deployment contract is not the locked six-service schema")
    validate_ad(challenge_root, checker, release)
    validate_hills(challenge_root, platform_root / "infra/hills/credentials.compose.yaml")


def main():
    parser = argparse.ArgumentParser(description="Validate the private challenge tree against the platform contract")
    parser.add_argument("challenge_root", type=Path)
    arguments = parser.parse_args()
    platform_root = Path(__file__).resolve().parents[2]
    try:
        validate(arguments.challenge_root.resolve(strict=True), platform_root)
    except (ContractError, OSError) as error:
        print(f"challenge integration: RED: {error}", file=sys.stderr)
        return 1
    print("challenge integration: GREEN: six AD services and three Hills match the closed platform contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
