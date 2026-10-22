# H7CTF'26 Finals

Private source repository for the H7CTF'26 Finals: a 24-hour Attack–Defense event with simultaneous King of the Hill rounds.

## Repository layout

- `services/` — six Attack–Defense services, their checkers, reference attacks, patch corpus, and service-specific tests.
- `hills/` — three King of the Hill targets, controllers, reference interactions, and tests.
- `infra/terraform/` — reproducible OCI-primary, GCP-backup, and Cloudflare infrastructure.
- `infra/images/` — image-building and host-bootstrap inputs.
- `infra/reconciler/` — private desired-state distribution from Anvil to both VPN gateways.
- `ops/` — runbooks, rehearsals, monitoring, recovery, and event configuration.
- `docs/` — author contracts and internal architecture decisions.

Challenge and infrastructure content is private until the organizers explicitly release it. The Anvil platform remains in its own repository; finals-specific Anvil configuration and deployment inputs belong here.

## Delivery rule

Every change follows the same path:

1. Build and test locally.
2. Commit and push for review.
3. Exercise the change in staging.
4. Promote an immutable, identified artifact to production.

Production hosts are deployment targets, never editing workspaces.

## Current event contract

- 15 competing teams plus one non-playing reference team.
- Six Attack–Defense services with exactly two scored flag stores each.
- Three King of the Hill targets.
- Flags match `H7CTF{<32 lowercase hexadecimal characters>}`.
- Player service patches pass the Verified Deployment Model before promotion.

Detailed planning and handoffs live in `/home/abu/Main/Projects/CTF26/handoffs/finals-build/` until they are reconciled into this repository.
