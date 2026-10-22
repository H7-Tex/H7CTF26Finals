# Deployment Orchestrator

The Deployment Orchestrator is the organizer-owned, per-team control service for the Verified Deployment Model. It runs on each production host on TCP 9300. It accepts only the matching private Gitea repository's signed push webhook and Anvil's scoped internal token.

This directory is a production canary, not an enabled production deployment. It deliberately has no fallback runner. The service will not validate, initialize or start until the root-owned runner, exact team identity, two 32-byte secrets, one seeded repository and all configured service manifests are present.

## Security contract

- The webhook requires `X-Gitea-Event: push`, a unique `X-Gitea-Delivery`, and the lowercase hexadecimal HMAC-SHA256 in `X-Gitea-Signature`. The signed body must name the configured repository, `refs/heads/main`, and exact before/after object IDs. A repeated delivery is idempotent only when its body hash is identical.
- A 15-second `git ls-remote` reconciliation catches lost webhooks. The fetched object must equal the advertised remote head and descend from the last approved head. Changed services come from an authoritative Git diff; webhook file lists are ignored.
- The organizer manifest is outside the player repository. It pins each initial commit, player-bundle SHA-256, factory image digest, exact patch allowlist, context limit and CPU, memory, PID and timeout bounds. Unknown roots, protected paths, symlinks, submodules and oversized trees fail before a build.
- Build, gate, promotion, rollback and health work crosses one fixed root-owned executable boundary. The executable is an unprivileged adapter: this unit has no capabilities, container-runtime group or Docker socket access. Requests are JSON on stdin and results are strict JSON on stdout. No shell command, mutable image tag, Docker socket or secret is constructed by this service.
- The state separates source commit, candidate digest, current digest, last-known-good digest, factory digest, copied gate data and recovery snapshot. Every build, gate, promotion, recovery and rollback persists its complete runner request and unique operation ID before execution; a restart replays only that exact request. Normal rollback changes only the image digest and sends `data_mode: preserve-current`.
- Promotion waits for Anvil's live checker quiet window and cannot promote the same service twice in one tick. A transport-ambiguous cutover retries its exact idempotent request; an explicit failed cutover asks the runner to restore the previous digest. A candidate enters green history only after two consecutive post-promotion `OK` ticks. Two consecutive ticks count toward automatic rollback only when the promoted digest is down and the corresponding prior digest is healthy.
- State is atomically replaced. Audit events are append-only, fsynced and sequence-linked to the state snapshot. Startup fsync-truncates at most one complete or partial audit tail left ahead of unchanged state; any gap, malformed complete record or larger divergence fails closed.

The systemd unit uses a locked `deploy-orchestrator` account, no capabilities, a read-only host filesystem, private temporary and device namespaces, syscall restrictions and explicit network destinations. Root-owned configuration remains mode 0700 under `/etc/deployment-orchestrator`; systemd credentials expose read-only copies to the service. Its root preflight requires exact ownership and modes for configuration, the fixed runner, repository and initialized state before the unprivileged process can start.

## Internal API

| Method and path | Caller | Purpose |
|---|---|---|
| `POST /v1/webhooks/gitea` | matching Gitea repository | authenticate and wake reconciliation |
| `GET /v1/status` | Anvil | complete per-service candidate/current/LKG/factory state |
| `GET /v1/audit?after=N&limit=100` | Anvil | ordered lifecycle events for reconciliation |
| `POST /v1/rollback/{service}` | Anvil | durably queue restoration of `last-known-good`, `factory` or an exact green digest |
| `POST /v1/health-observations` | Anvil | submit causal post-promotion checker results |
| `GET /healthz` | host monitor | component and durable-store health |

Every `/v1` endpoint except the webhook requires `Authorization: Bearer $ANVIL_GAME_INTERNAL_TOKEN`. Missing or wrong credentials return 404. Rollback requests require `target`, stable `actor_id` and `trace_id`. Health observations require the active and prior digest, tick, `OK|DOWN|ERROR` status for each digest and a trace ID. Do not expose TCP 9300 to team or public networks.

## Commissioning

1. Generate the six-service file from the committed challenge release manifests. Use only the locked slugs `sign-me-in`, `can-we-settle-this`, `update-pending`, `book-me-if-you-can`, `ship-it` and `terms-may-apply`; set `expected_services` to 6. Copy each committed player export's `BUNDLE.json` digest into `bundle_sha256`.
2. Seed `team-NN/services` from those player exports, retain the common initial monorepo commit, clone it to `/var/lib/deployment-orchestrator/repository`, and install a read-only deploy key plus pinned Gitea host key below the service account's `.ssh` directory. The clone's `origin` must exactly match `remote_url`.
3. Install the fixed unprivileged runner adapter and its organizer-owned build definitions. It must pass the contract in [RUNNER-CONTRACT.md](RUNNER-CONTRACT.md). The executable must be root-owned and not group/world-writable. Promotion still requires the separately reviewed privileged executor/socket described there; do not add the service account to the Docker group or mount a runtime socket into this unit.
4. Install `config.json`, `services.json`, `webhook.secret` and `anvil.token` as root-only files below `/etc/deployment-orchestrator`. Add `10.60.200.10 finals.h7tex.com` to the production host's private resolution so tick HTTPS keeps the public certificate name without public hairpinning.
5. Build without embedding source state in the image, then install:

   ```bash
   CGO_ENABLED=0 go build -trimpath -ldflags='-s -w' -o deployment-orchestrator ./cmd/deployment-orchestrator
   sudo ./install.sh ./deployment-orchestrator
   ```

6. Before the first start, verify the live factory digest for every service and create the durable state exactly once:

   ```bash
   sudo -u deploy-orchestrator \
     /usr/local/bin/deployment-orchestrator initialize \
     --config /run/credentials/deployment-orchestrator.service/config.json
   ```

   Run this through a temporary credential-bearing systemd unit; the literal `/run/credentials/...` path exists only inside the unit. Never fabricate `state.json` by hand or repeat initialization on a used box.

7. Enable one canary only after [REHEARSAL.md](REHEARSAL.md) passes. The unit is shipped disabled:

   ```bash
   sudo systemctl enable --now deployment-orchestrator.service
   sudo journalctl -u deployment-orchestrator.service -n 50 --no-pager
   ```

The generic production image contains the account, static binary, hardened unit and empty directories, but does not enable the unit or install a runner, configuration, credentials or state. Missing challenge manifests, a real Deployment Gate, the unprivileged runner adapter, privileged executor, production secret-bundle delivery, Anvil lifecycle integration and a rehearsed state backup/restore are release blockers, not optional development modes. The current secret relay targets only shared platform roles; it does not commission production hosts.
