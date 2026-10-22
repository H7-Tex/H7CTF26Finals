# Terraform foundation

This tree is the reproducible infrastructure source for H7CTF'26 Finals. It is safe to format and validate locally; nothing here is permission to plan against, apply to, or destroy cloud resources.

## Locked topology

- OCI Hyderabad is the only live game data plane.
- GCP project `ctf26-512405` is backup/archive only and is never on the scoring path.
- Cloudflare exposes `finals.h7tex.com` on TCP 443 and `vpn.h7tex.com` on UDP 443 as DNS-only records after OCI reserves two stable public IPs.
- 15 team monorepositories feed 15 team `h7d` deployers. Dormant service directories are added only at release.
- The fleet is 16 production boxes including NOP, 15 workbenches, six Attack-Defense services, and three hills.
- Mirror and shared-service internet egress are explicit warm-up switches and default off; production and workbench subnets never receive an internet default route.

The current authoritative deployment design is `/home/abu/Main/Projects/CTF26/handoffs/finals-build/VERIFIED-DEPLOYMENT-MODEL.md`. The Terraform audit and rollout plan is `/home/abu/Main/Projects/CTF26/handoffs/finals-build/TERRAFORM-BUILD-PLAN.md`.

## Layout

- `bootstrap/gcp-state`: one-time private GCS state bucket bootstrap.
- `modules`: reusable cloud-specific resources.
- `environments/production`: production roots with independent state.
- `scripts/check.sh`: credential-free formatting and static validation.

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
