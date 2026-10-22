# Terraform foundation

This tree is the reproducible infrastructure source for H7CTF'26 Finals. It is safe to format and validate locally; nothing here is permission to plan against, apply to, or destroy cloud resources.

## Locked topology

- OCI Hyderabad is the only live game data plane.
- The VCN uses OCI-native `10.60.0.0/16` and `10.61.0.0/16` blocks; clients may advertise the aggregate `10.60.0.0/15` route.
- GCP project `ctf26-512405` is backup/archive only and is never on the scoring path.
- Cloudflare publishes `finals.h7tex.com` and `vpn.h7tex.com` as DNS-only records after OCI reserves two stable public IPs. It also publishes the VPN-only private name `git.h7tex.com` at fixed address `10.60.201.30`; this adds no public endpoint. Caddy manages public TLS for the web ingress; WireGuard uses UDP 443 directly.
- 15 team monorepositories feed 15 team Deployment Orchestrators. Dormant service directories are added only at release.
- The fleet is 16 production boxes including NOP, 15 workbenches, six Attack-Defense services, and three hills. Every production host has a separate 50 GiB XFS data volume with hard per-service byte and inode project quotas.
- Mirror and shared-service internet egress are explicit warm-up switches and default off; production and workbench subnets never receive an internet default route.

The current authoritative deployment design is `/home/abu/Main/Projects/CTF26/handoffs/finals-build/VERIFIED-DEPLOYMENT-MODEL.md`. The Terraform audit and rollout plan is `/home/abu/Main/Projects/CTF26/handoffs/finals-build/TERRAFORM-BUILD-PLAN.md`.

## Layout

- `bootstrap/gcp-state`: one-time private GCS state bucket bootstrap.
- `modules`: reusable cloud-specific resources.
- `environments/production`: production roots with independent state.
- `scripts/check.sh`: credential-free formatting and static validation.
- `scripts/package-oci-stack.sh`: deterministic Resource Manager package from a clean current Git HEAD.

OCI roots will run as OCI Resource Manager stacks because Sage can authenticate with an OCI instance principal without copying a key. Resource Manager currently executes Terraform 1.5.x, so all code must remain compatible with Terraform 1.5 even though local development is pinned to 1.16.6.

GCP and Cloudflare roots use a GCS backend after the bootstrap bucket exists. Local Google provider operations require Application Default Credentials:

```bash
/home/abu/google-cloud-sdk/bin/gcloud auth application-default login you@example.com
/home/abu/google-cloud-sdk/bin/gcloud auth application-default set-quota-project ctf26-512405
```

Do not copy or commit the generated credential file. Cloudflare authentication is supplied only through `CLOUDFLARE_API_TOKEN`.

## Local checks

```bash
mise exec -- infra/terraform/scripts/check.sh
```

CI runs the same validation with Terraform 1.5.7 and 1.16.6. It never runs `plan` or `apply` and receives no cloud credentials.

## Production discipline

1. Merge reviewed code.
2. Package or initialize the exact commit.
3. Produce a saved plan or OCI Resource Manager plan job.
4. Review identity, region, cost, creates, replacements, and destroys.
5. Apply that reviewed plan only after the explicit production gate.

Never use `-auto-approve`, `-lock=false`, or a manual production edit as a normal workflow. State, plan files, `.tfvars`, keys, tokens, player profiles, and runtime secrets are ignored and must remain outside Git.

Package an OCI root only after its commit exists and the worktree is clean:

```bash
infra/terraform/scripts/package-oci-stack.sh oci-platform
```

The script prints the ZIP path, SHA-256 checksum path, exact commit and Resource Manager working directory. Upload that ZIP unchanged and record the values with the plan job.
