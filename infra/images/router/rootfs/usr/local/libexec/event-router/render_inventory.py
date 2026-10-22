#!/usr/bin/env python3
import argparse
import base64
import ipaddress
import json
import re
from pathlib import Path


IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
TOP_LEVEL_KEYS = {"version", "generation", "peers"}
PEER_KEYS = {"peer_id", "team_id", "team_number", "public_key", "address"}


def fail(message):
    raise ValueError(message)


def load_inventory(path):
    try:
        inventory = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail(f"cannot read inventory: {error}")

    if not isinstance(inventory, dict) or set(inventory) != TOP_LEVEL_KEYS:
        fail("inventory must contain only version, generation and peers")
    if type(inventory["version"]) is not int or inventory["version"] != 1:
        fail("inventory version must be 1")
    if type(inventory["generation"]) is not int or inventory["generation"] < 1:
        fail("generation must be a positive integer")
    if not isinstance(inventory["peers"], list) or len(inventory["peers"]) > 600:
        fail("peers must be a list with at most 600 entries")
    return inventory


def ensure_successor(inventory, active_inventory):
    if active_inventory is None:
        return
    active = load_inventory(active_inventory)
    if inventory["generation"] < active["generation"]:
        fail("peer inventory generation cannot move backward")
    if inventory["generation"] == active["generation"] and inventory != active:
        fail("peer inventory changed without a new generation")


def validate_peer(peer):
    if not isinstance(peer, dict) or set(peer) != PEER_KEYS:
        fail("each peer must contain only peer_id, team_id, team_number, public_key and address")

    for field in ("peer_id", "team_id"):
        value = peer[field]
        if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
            fail(f"invalid {field}")

    team = peer["team_number"]
    if type(team) is not int or not 1 <= team <= 15:
        fail("team_number must be between 1 and 15")

    if not isinstance(peer["address"], str):
        fail("peer address must be a string")
    try:
        address = ipaddress.ip_interface(peer["address"])
    except (TypeError, ValueError) as error:
        fail(f"invalid peer address: {error}")
    octets = address.ip.packed
    if address.version != 4 or address.network.prefixlen != 32:
        fail("peer address must be an IPv4 /32")
    if octets[:3] != bytes((10, 80, team)) or not 200 <= octets[3] <= 239:
        fail("peer address must be inside its team's 10.80.T.200-239 pool")

    key = peer["public_key"]
    if not isinstance(key, str):
        fail("public_key must be a string")
    try:
        decoded_key = base64.b64decode(key, validate=True)
    except ValueError:
        fail("public_key must be valid base64")
    if len(decoded_key) != 32 or not any(decoded_key):
        fail("public_key must encode a non-zero 32-byte key")

    return address.ip, f"10.60.250.{120 + team}"


def render(inventory):
    peers = []
    seen_ids = set()
    seen_keys = set()
    seen_addresses = set()

    for peer in inventory["peers"]:
        address, egress = validate_peer(peer)
        if peer["peer_id"] in seen_ids:
            fail("peer_id values must be unique")
        if peer["public_key"] in seen_keys:
            fail("public_key values must be unique")
        if address in seen_addresses:
            fail("peer addresses must be unique")
        seen_ids.add(peer["peer_id"])
        seen_keys.add(peer["public_key"])
        seen_addresses.add(address)
        peers.append((address, egress, peer["public_key"]))

    peers.sort(key=lambda item: int(item[0]))
    wireguard = []
    for address, _, public_key in peers:
        wireguard.extend(("[Peer]", f"PublicKey = {public_key}", f"AllowedIPs = {address}/32", ""))

    nftables = [
        "flush set inet event_router peer_addresses",
        "flush set inet event_router peer_workbench_access",
        "flush map inet event_router peer_snat",
    ]
    if peers:
        addresses = ", ".join(str(address) for address, _, _ in peers)
        mappings = ", ".join(f"{address} : {egress}" for address, egress, _ in peers)
        workbenches = ", ".join(
            f"{address} . 10.61.{address.packed[2]}.2" for address, _, _ in peers
        )
        nftables.append(f"add element inet event_router peer_addresses {{ {addresses} }}")
        nftables.append(f"add element inet event_router peer_workbench_access {{ {workbenches} }}")
        nftables.append(f"add element inet event_router peer_snat {{ {mappings} }}")

    return "\n".join(wireguard), "\n".join(nftables) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("inventory", type=Path)
    parser.add_argument("--wireguard-output", required=True, type=Path)
    parser.add_argument("--nft-output", required=True, type=Path)
    parser.add_argument("--active-inventory", type=Path)
    args = parser.parse_args()

    try:
        inventory = load_inventory(args.inventory)
        ensure_successor(inventory, args.active_inventory)
        wireguard, nftables = render(inventory)
    except ValueError as error:
        parser.error(str(error))

    args.wireguard_output.write_text(wireguard, encoding="utf-8")
    args.nft_output.write_text(nftables, encoding="utf-8")


if __name__ == "__main__":
    main()
