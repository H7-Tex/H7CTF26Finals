# Shared platform commissioning

The shared hosts are built from two reviewed immutable images. Cloud-init regenerates one unique Ed25519 SSH host key, assigns one fixed role and applies its default-deny host firewall. It does not start Anvil, Gitea, the mirror, the checker gate or the peer reconciler. Secret-dependent services remain disabled until their fixed preflights succeed.

| Role | Address | Image | Durable mount | Intended listeners |
| --- | --- | --- | --- | --- |
| platform | `10.60.200.10` | `platform-x86` | `/srv/anvil` | TCP 443 and 4141 |
| operations | `10.60.200.5` | `platform-arm` | none | management SSH only |
| control | `10.60.201.20` | `platform-x86` | none | management SSH only |
| repository | `10.60.201.30` | `platform-arm` | `/srv/gitea` | Gitea SSH 22, HTTPS 443, management SSH 2222 |
| mirror | `10.60.202.10` | `platform-arm` | `/srv/cache` | TCP 3141, 3142, 4873 and 5000 |
| hill-01 | `10.60.210.11` | `platform-x86` | none | TCP 7101 |
| hill-02 | `10.60.210.12` | `platform-x86` | none | TCP 7102 |
| hill-03 | `10.60.210.13` | `platform-x86` | none | TCP 7103 |

The platform, repository and mirror data disks are exactly 150, 100 and 300 GiB. The primary gateway has the separate 500 GiB capture disk. Each initializer discovers exactly one non-root whole disk, refuses partitions or signatures, formats ext4 once and mounts by a fixed label. A first cloud-init run may race the OCI attachment; the enabled initializer retries, while all dependent services remain closed. Do not bypass a failed initializer. Verify `findmnt`, its label, and `systemctl status finals-volume@ROLE` before commissioning a service.

The active gateway writes structured conntrack lifecycle events, peer inventory generations and peer `/32` to team/participant correlation records to `/srv/captures/events.jsonl`. The collector caches inventory until its mtime or size changes and batches at most 1 MiB or two seconds before an fsync, so an abrupt host loss has an explicit maximum two-second/1-MiB unflushed window. Logs rotate at 1 GiB with 300 retained files; each rollover is recorded, and overwriting the oldest file emits a `retention_drop` event. This reserves about 300 GiB of the 500 GiB disk for the 24-hour event while leaving filesystem and operational headroom. Every collector start emits a `collection_gap` record using the durable heartbeat, including whether the prior stop was clean and the measured gap. After the event, stop collection, take and verify a protected volume backup, and retain the event files and backup without reuse for at least 30 days. This is durable attribution, not gapless HA telemetry: the single capture disk is protected and normally attached to the primary gateway.

For a gateway failover, first stop `event-router-flow-log.service` and record the last durable heartbeat. In a reviewed break-glass commit, temporarily remove `prevent_destroy` only from the capture volume attachment, change `gateway_primary_instance_id` in the platform stack to the promoted gateway instance OCID, and apply a saved plan containing exactly one detach and one attach—never a volume destroy. On the promoted gateway run `finals-initialize-volume captures`, then `event-router-initialize active`; demote the former gateway with `event-router-initialize standby`. Confirm the new `collection_gap` record, its duration, the current `inventory_applied` mapping, and fresh correlated conntrack events before restoring the attachment guard in code. Rehearse this procedure before the event and record the observed telemetry gap; do not claim continuous capture across failover.

## Image and DNS gates

The runtime builder accepts only Anvil v0.355.0 commit `f55f44f9328aa12fdf60babfd9c8ff2669c35fa8`. It clones that public revision during the outbound-only build, runs its finals checks, prebuilds the API and web layers, pulls every pinned compose image and installs the exact tree at `/opt/anvil/current`. No service, certificate or secret is embedded in the image.

Builder source is stored as fixed-path executable payloads in a private transient OCI Object Storage bucket. Per-role object-read PARs use an explicit reviewed expiry no more than 24 hours away. Tiny cloud-init runs a bounded downloader that verifies exact byte length and SHA-256 before executing the payload; it does not recursively invoke cloud-init. Capture only stopped, tested builders. Destroy the builder stack after capture to revoke the PARs and delete the source objects. The production image capture must use the final repository revision containing the reviewed Deployment Orchestrator, runner adapter, socket executor and state helper with all hardened units disabled. The real effect commands, executor policy, manifests, credentials and initialized state are separate commissioning artifacts and are never embedded in the generic image.

Cloudflare must hold these DNS-only records:

- `finals.h7tex.com` at the existing web ingress public IP.
- `vpn.h7tex.com` at the existing WireGuard public IP.
- `git.h7tex.com` at private address `10.60.201.30`.

The repository record creates no public endpoint and no SRM whitelist item. Team and organizer clients resolve it only while routed through the finals network. Keep all three records unproxied.

Temporarily enable only service-subnet warm-up egress, then run manual DNS-01 Certbot on the operations host for `finals.h7tex.com` and `git.h7tex.com`. Create each requested `_acme-challenge` TXT value in Cloudflare, wait for authoritative resolution and continue issuance. Package the resulting certificate and key into the fixed `anvil` and `repository` age bundles; do not copy plaintext keys to their target hosts. Certbot and `age` are preinstalled, so package egress is not needed. Disable service warm-up egress immediately after certificate and relay commissioning.

## Host-bound secret relay

Before applying the host stacks, create a dedicated event-only Ed25519 operations-relay keypair. Do not reuse an organizer, workstation or personal identity. Supply organizer break-glass public key(s) through `organizer_ssh_authorized_keys` and the raw relay public key through `operations_relay_ssh_public_key` in the ingress and platform stacks. Terraform constrains the relay key to the fixed secret receiver on both gateways, platform, control and repository; it does not install that key on operations, mirror or hill hosts. The control reconciler key is separate and is installed on gateways only through its forced-command authorization flow.

Golden images contain no SSH host keys. For each relay target, read the `FINALS_HOST_RECIPIENT` line and SHA-256 fingerprint from OCI console history. Build an exact five-line `known_hosts` file using the verified Ed25519 public keys for both gateways, platform, control and repository; the repository management entry is `[10.60.201.30]:2222`, while every other entry uses its plain address and SSH 22. Temporarily enable service warm-up egress and use OCI Run Command to retrieve the operations host recipient; compare it with its console line. Locally build an `operations-relay` JSON bundle containing only the dedicated private key and exact known-hosts file, encrypt it to that recipient, and send only the age ciphertext through Run Command:

```bash
sudo finals-install-secret-bundle operations-relay < operations-relay.age
```

Run Command content must never contain plaintext key or certificate material. The installed relay files are fixed at `/etc/finals-platform/operations/id_ed25519` and `known_hosts`, root-only. The operations host sends a separately host-key-encrypted age bundle through `sudo finals-operations-ssh TARGET TYPE < bundle.age`; the wrapper accepts no arbitrary command, always uses the dedicated identity, strict known-host checking and the target's compiled-in address and port. The forced receiver permits only the exact bundle type assigned to that immutable host role and can execute only the matching passwordless installer command. The target decrypts from standard input with its post-launch `/etc/ssh/ssh_host_ed25519_key`; the relay never sees plaintext. The fixed installer rejects unknown bundle types, missing or extra files, unsafe environment text, wrong TLS names, mismatched keys, unexpected hosts and arbitrary destinations.

After delivery, set `enable_service_warmup_egress=false`, apply the reviewed foundation plan, confirm the service route table has no `0.0.0.0/0`, and prove public HTTPS fails from operations. Private SSH from `10.60.200.5` must still work. Players and workbenches must not reach management SSH.

## Repository

The repository age bundle contains independent 32-or-more-character `GITEA_SECRET_KEY` and `GITEA_INTERNAL_TOKEN` values plus a DNS-01 certificate for `git.h7tex.com`. After `/srv/gitea` is mounted, run:

```bash
sudo finals-install-secret-bundle repository < repository.age
sudo finals-repository-commission
```

Commissioning writes a locked offline Gitea configuration, creates a durable Ed25519 Gitea SSH host key under `/srv/gitea/data/ssh`, moves host management SSH to TCP 2222 and starts the pinned Gitea and Nginx images. The public Gitea key survives container replacement; record and distribute its verified fingerprint. Teams use Gitea SSH 22 or HTTPS 443. Only operations may reach host SSH 2222.

Registration, migrations, Actions, packages, LFS and external mirrors are disabled. Create the initial administrator with Gitea's random-password CLI, require an immediate password change, then create only the reviewed private team repositories. Take an OCI volume backup and rehearse a restore before the event; a configured backup policy without a restore test is not accepted.

## Dependency mirror

Create reviewed content under all four durable roots: `apt`, static PEP 503 `pypi`, Verdaccio `verdaccio`, and OCI-distribution `registry`. Before seeding, apply a reviewed foundation plan with `enable_mirror_warmup_egress=true`, then explicitly open the host gate:

```bash
sudo finals-mirror-mode warmup
```

Warm-up permits only public TCP 80/443 from this host. Populate the exact dependency closure and run all workbench builds against the mirror. Generate and review the complete file inventory:

```bash
sudo finals-mirror-manifest > /tmp/preseed-manifest.json
sudo install -o root -g root -m 0644 /tmp/preseed-manifest.json /etc/finals-platform/mirror/preseed-manifest.json
sudo finals-mirror-mode offline
```

Offline mode atomically reloads and verifies a host firewall with no public web egress, enables apt-cacher-ng offline mode, makes the registry read-only and validates every artifact digest and size before starting. Then set `enable_mirror_warmup_egress=false`, apply, confirm the mirror route table has no default route and prove public HTTP and HTTPS fail. Both the host gate and Terraform route must be closed for rehearsal and the event.

## Control, checkers and hills

Control activation fixes `finals.h7tex.com` to `10.60.200.10` in `/etc/hosts`. The peer-reconciler timer remains disabled until its token, dedicated SSH identity and exact two-gateway known-hosts bundle are installed and an end-to-end reconciliation succeeds. Follow `infra/reconciler/README.md`; do not enable the timer on a partial result.

Checker artifacts live below `/opt/finals-checkers`. A reviewed `artifact-manifest.json` records each relative path, size, executable marker and SHA-256. `finals-checkers-ready.service` is disabled and refuses activation on any missing, changed, linked or escaping artifact. This is an integrity gate only; it does not invent a checker API or scheduler.

Production host firewalls accept challenge ports `7001-7006` only from the router's normalized private identity `10.60.250.120`; they do not admit control or team identities directly. The router preserves original sources only in pre-NAT telemetry and adds no application or transport marker. Each hill host firewall drops all sibling-hill traffic in input, forward and output paths. It exposes only its assigned 7101, 7102 or 7103 listener to team identities and control. Before opening play, prove the assigned port works from one team and control, every unassigned hill port fails, and no hill container or host can connect to either sibling address.

## Final acceptance

- Every source revision, Anvil revision and container image is immutable and reviewed.
- Every post-launch SSH host fingerprint and the durable Gitea fingerprint is recorded.
- All four fixed volumes show their expected ext4 labels and mount points.
- Anvil, repository, mirror, reconciler and checker gates fail closed when one required artifact is removed.
- Service and mirror default routes are absent; production, workbench and hills never had one.
- Player paths reach only game, hill, Anvil and team repository ports. Operations remains the only management source.
- Restore, gateway failover, repository clone/push, dependency-offline build and overnight soak tests have passed before production activation.
