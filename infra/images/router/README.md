# Competition ingress router

This image artifact supplies the minimum host policy required before the OCI ingress stack can be planned. It has no credentials, player profiles, cloud identifiers, DNS changes or deployment side effects.

## Address contract

| Address | Function |
|---|---|
| `10.60.250.100` | Reserved VPN private address; accepts only WireGuard UDP 443 |
| `10.60.250.101` | Reserved web private address; forwards only TCP 443 to `10.60.200.10:443` |
| `10.60.250.121-135` | Private team attack-egress identities for teams 1-15 |
| `10.80.255.1/16` | Router-side WireGuard address |
| `10.80.T.200-239/32` | Non-reused individual peer addresses for team `T` |

There are exactly two reserved public IPs. The 15 team identities are secondary private IPs only. On failover, all 17 secondary private IP objects move to the standby VNIC, the operating-system address role is changed, and the Terraform `active_router` input is reconciled after the probes pass.

## Runtime policy

`nftables.conf` defaults input, forwarding and output to drop. It:

- accepts UDP 443 only on the VPN destination and forwards TCP 443 only on the web destination;
- drops the inverse protocol/address combinations before generic state handling;
- limits peers and workbenches to released service ports, hill endpoints, Anvil HTTPS and VPN-only TCP `4141`, Gitea and their team-owned management paths;
- limits checker, repository, production dependency and organizer management traffic to sparse source, destination and port sets;
- limits workbench and production dependency downloads to the mirror's PyPI `3141`, APT `3142`, npm `4873` and OCI registry `5000` ports;
- denies unmapped WireGuard sources and VPN internet forwarding;
- SNATs every accepted individual peer and team workbench to the stable team identity;
- records rate-limited pre-NAT allow/drop metadata in the kernel journal;
- records conntrack `NEW` and `DESTROY` events with timestamps, original/reply tuples, counters and connection identifiers.

The router journal contains network metadata, not packet payloads. The operations log shipper must add router identity and forward these records to the restricted sink. That sink joins the pre-NAT `/32`, active inventory generation, team egress address, destination inventory and game tick. It retains identifiable records for 30 days and marks collection gaps rather than reconstructing them.

## Peer inventory boundary

Anvil owns the append-only issue, revoke and rotation ledger. The router receives only a root-readable active snapshot:

```json
{
  "version": 1,
  "generation": 42,
  "peers": [
    {
      "peer_id": "peer-opaque-id",
      "team_id": "team-opaque-id",
      "team_number": 7,
      "public_key": "replace-with-wireguard-public-key",
      "address": "10.80.7.200/32"
    }
  ]
}
```

The renderer rejects unknown fields, duplicate identifiers, keys and addresses, malformed public keys, cross-team addresses and addresses outside `.200-.239`. The apply path refuses group/world-readable inputs, stale generations and same-generation changes. It synchronizes WireGuard before atomically replacing the nftables peer/SNAT maps, so a partial update fails closed.

Private keys, user names, email addresses, Discord identities and revoked peers never appear in the snapshot. The WireGuard server private key is delivered separately to `/etc/wireguard/private.key` on both routers by the audited secret bootstrap. It is never stored in Terraform state or this repository.

The private control-host reconciler in `infra/reconciler` converts Anvil's desired peer records into the root-only monotonic snapshot on both gateways. Anvil does not enter network namespaces, and the gateway exposes no public peer-management API.

## Image build gate

Use a reviewed Ubuntu 24.04 OCI base image and install `nftables`, `wireguard-tools`, `conntrack`, `python3`, `iproute2`, `systemd` and `systemd-timesyncd`. Run `install.sh` as root inside the image, then run:

```bash
infra/images/router/tests/run.sh
```

The harness runs inventory validation and an unprivileged Linux network-namespace topology. It proves:

1. VPN UDP 443 succeeds and VPN TCP 443 fails.
2. Web TCP 443 reaches Anvil and web UDP 443 fails.
3. Two peers on one team render to the same egress identity.
4. A mapped peer and its team workbench appear as `10.60.250.121` at the target.
5. An unmapped peer source and VPN internet forwarding fail.
6. Standby role removes every secondary address.

Before creating either router, the image build still needs the reviewed OCI base-image OCID, image compartment, build subnet, builder authentication method and immutable output image OCID. Runtime commissioning still needs the server key, first signed peer snapshot, internal journal destination, clock-skew alert, game route-table change and rehearsed failover procedure.
