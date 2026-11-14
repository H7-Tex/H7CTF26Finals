# infra

Everything we used to run the H7CTF 2026 finals: six Attack-Defense services per team, three King of the Hill boxes, Anvil as the scoreboard and tick scheduler, all behind a WireGuard VPN. OCI Hyderabad was the live data plane. GCP only held post-event archives and Terraform state. Cloudflare served DNS.

Public entry points were `finals.h7tex.com` (TCP 443, Anvil) and `vpn.h7tex.com` (UDP 443, WireGuard). Everything else lives on private `10.60.0.0/15` addresses and is only reachable over the VPN.

## Layout

```
terraform/        OCI, GCP and Cloudflare roots (environments/production/*) and modules
images/router/    gateway image: nftables policy, WireGuard, NAT, flow capture
images/runtime/   platform (x86 + arm), production and workbench images
platform/         shared hosts: Anvil, Gitea, dependency mirror, firewall, volume init
secrets/          age bundles encrypted to each host's SSH key, plus the installer
reconciler/       control host job that pushes Anvil's VPN peer list to both gateways
checkers/         runs the six checker containers (plus Mongo) on the control host
hills/            pulls hill credentials from Anvil and starts the three hill boxes
model-a-runtime/  installs the six services on a team box, the `h7` player tool
deployment/       Go deployment orchestrator (git push to deploy), built but default off
team-access/      compiles team SSH keys and applies them to workbenches
volumes/          XFS data volume with per-service byte and inode quotas
integration/      static check that the challenge repo matches these contracts
acceptance/       validates the staging evidence bundle before release
archive/          OCI to GCS upload after the event, no service account keys
```

## Network

| Host | Address | What runs there |
| --- | --- | --- |
| platform | 10.60.200.10 | Anvil (443, 4141) |
| operations | 10.60.200.5 | management SSH, secret relay |
| control | 10.60.201.20 | checkers (9001-9006), peer reconciler |
| repository | 10.60.201.30 | Gitea (`git.h7tex.com`, VPN only) |
| mirror | 10.60.202.10 | apt 3142, PyPI 3141, npm 4873, registry 5000 |
| hill-01..03 | 10.60.210.11-13 | hills on 7101-7103 |
| team T box | 10.60.T.2 | services on 7001-7006 |

Two gateways (primary and standby) hold the public IPs through floating private addresses. All service traffic is source-NATed to `10.60.250.120`, so services never see who attacked them; the original source only lives in the gateway's flow log. Each team's outbound traffic is NATed to `10.60.250.121-135`. Production and workbench subnets have no internet route at all; the mirror and service subnets get one only during warm-up.

## Bringing it up

Order matters because later stacks read outputs from earlier ones. Each OCI root runs as a Resource Manager stack built with `terraform/scripts/package-oci-stack.sh <stack>`. Always plan, read the plan, then apply.

1. `terraform/bootstrap/gcp-state` once for the state bucket, then `oci-foundation` (VCN, subnets, route tables).
2. `oci-addresses` reserves the two public IPs.
3. Images: `oci-gateway-builder` then `oci-gateway-image`; `oci-runtime-builders` then `oci-runtime-images`. A builder that stopped on its own with `phase=seal status=success` on the serial console is good; anything else gets thrown away. `oci-runtime-canaries` boots each image once as a smoke test.
4. `oci-ingress` (gateways), then feed its `routing_private_ip_id` back into `oci-foundation` and apply again.
5. `oci-platform` (shared hosts), `oci-fleet` (team boxes and workbenches), `cloudflare-dns`.
6. Secrets: read each host's `FINALS_HOST_RECIPIENT` from the OCI console, encrypt a bundle to it with `age`, and install it with `finals-install-secret-bundle <type> < bundle.age` (directly via Run Command, or relayed from operations with `finals-operations-ssh`). Plaintext never leaves the laptop.
7. Commission the shared hosts: `finals-repository-commission` for Gitea, `finals-mirror-mode warmup`, seed, then `finals-mirror-mode offline`. Turn warm-up egress back off in Terraform.
8. Control host: run the reconciler once by hand, check both gateways show the same generation, then enable `peer-reconciler.timer`. Install checker images under `/opt/finals-checkers` and run `checker-runtime-commission`.
9. Hills: `systemctl enable --now finals-hill-credentials.service`, then `finals-hill-compose up`. Never call `docker compose` on a hill directly.
10. Team boxes: `model-a-runtime/prepare-release.py <challenge repo> <out>` builds the release once, then `finals-model-a-install <release> <team> <sha256>` on each box.
11. Team SSH keys: `team-access/team-access.py compile`, then `finals-team-access apply` on each workbench.
12. Run `integration/run.sh <challenge repo>` and `acceptance/run.sh <evidence.json>`, then `event-router-challenge-access open` on the active gateway to let players in.

Gateway failover means moving the capture volume attachment and all floating private IPs to the standby, then `event-router-initialize active` there and `standby` on the old one. Expect a short gap in the flow log.

After the event, stop each service, `finals-archive-egress enable`, `finals-archive upload <purpose> <file>`, then `finals-archive-egress disable`.

## Tests

Most directories have `tests/run.sh`. Terraform has `terraform/scripts/check.sh` (fmt and validate, no credentials) and `terraform/tests/`. None of them touch the cloud.

Nothing secret is checked in. State, real `.tfvars`, keys, tokens and certificates stay out of git; the `*.example` files show the shape.
