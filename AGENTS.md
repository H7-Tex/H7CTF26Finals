# Repository working agreement

These rules apply to every directory in this repository unless a more specific `AGENTS.md` says otherwise.

## Safety and release discipline

- Work locally first. Do not edit files on production hosts.
- Do not apply Terraform, create cloud resources, change DNS, or deploy without an explicit reviewed production step.
- Never commit credentials, private keys, WireGuard profiles, team secrets, live flags, Terraform state, or non-example variable files.
- Pin deployable artifacts by digest or an immutable version. Do not make production depend on a mutable `latest` tag.
- Preserve unrelated work in shared worktrees. Use a dedicated branch or worktree for each implementation lane.

## Challenge contract

- The canonical flag form is `H7CTF{<32 lowercase hexadecimal characters>}`.
- Each Attack–Defense service exposes exactly two scored flag stores. Exploit variants do not increase the store count.
- Keep organizers' reference attacks and private validation material outside player-visible source bundles.
- A service is releaseable only after checker, availability, benign-patch, exploit, rollback, soak, and adversarial-review gates pass.

## Infrastructure contract

- OCI Hyderabad is the live primary data plane. GCP is backup/archive capacity and must not sit on the live scoring path.
- Public event entry points are `finals.h7tex.com` on TCP 443 and `vpn.h7tex.com` on UDP 443.
- Infrastructure changes must be reproducible through reviewed code. Record imports and any emergency manual action in the matching runbook.
- Run formatting and static validation before committing Terraform. A plan must be reviewed before any apply.

## Commit style

Use only `v0.0.N` as the commit subject. Put each outcome in the body as a bullet such as `- build production platform services`. Keep commits scoped and independently testable.
