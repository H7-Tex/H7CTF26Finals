# Deployment Orchestrator

The Deployment Orchestrator is the organizer-owned, per-team control service for the Verified Deployment Model. It runs on each production host on TCP 9300. It accepts only the matching private Gitea repository's signed push webhook and Anvil's scoped internal token.

This directory is a production canary, not an enabled production deployment. It deliberately has no fallback backend. The service will not validate, initialize or start until the exact team identity, executor policy and five root-only backend commands, two 32-byte secrets, one seeded repository and all configured service manifests are present.

## Security contract

- The webhook requires `X-Gitea-Event: push`, a unique `X-Gitea-Delivery`, and the lowercase hexadecimal HMAC-SHA256 in `X-Gitea-Signature`. The signed body must name the configured repository, `refs/heads/main`, and exact before/after object IDs. A repeated delivery is idempotent only when its body hash is identical.
- A 15-second `git ls-remote` reconciliation catches lost webhooks. The fetched object must equal the advertised remote head and descend from the last approved head. Changed services come from an authoritative Git diff; webhook file lists are ignored.
- The organizer release manifest is outside the player repository. It is the one source for the six service identities, build inputs, immutable artifacts, runtime contract, fixed backends and separate live/gate/recovery quotas. The compiler rejects blanks, mutable images, unknown fields, duplicate JSON keys and changed fixed topology before emitting `services.json`, executor policy, volume policy or HAProxy configuration.
- Build, gate, promotion, rollback and health work crosses one fixed root-owned executable boundary. The executable is an unprivileged adapter: this unit has no capabilities, container-runtime group or Docker socket access. Requests are JSON on stdin and results are strict JSON on stdout. No shell command, mutable image tag, Docker socket or secret is constructed by this service.
- The state separates source commit, candidate digest, current digest, last-known-good digest, factory digest, copied gate data and recovery snapshot. Every build, gate, promotion, recovery and rollback persists its complete runner request and unique operation ID before execution; a restart replays only that exact request. Normal rollback changes only the image digest and sends `data_mode: preserve-current`.
- Promotion waits for Anvil's live checker quiet window and cannot promote the same service twice in one tick. A transport-ambiguous cutover retries its exact idempotent request; an explicit failed cutover asks the runner to restore the previous digest. A candidate enters green history only after two consecutive post-promotion `OK` ticks. Two consecutive ticks count toward automatic rollback only when the promoted digest is down and the corresponding prior digest is healthy.
- State is atomically replaced. Audit events are append-only, fsynced and sequence-linked to the state snapshot. Startup fsync-truncates at most one complete or partial audit tail left ahead of unchanged state; any gap, malformed complete record or larger divergence fails closed.

The systemd unit uses a locked `deploy-orchestrator` account, no capabilities, a read-only host filesystem, private temporary and device namespaces, syscall restrictions and explicit network destinations. Root-owned configuration remains mode 0700 under `/etc/deployment-orchestrator`; systemd credentials expose read-only copies to the service. Its root preflight requires exact ownership and modes for configuration, the fixed runner, offline lock, repository and initialized state before the unprivileged process can start. The repository is mode 0750 and created under umask 0027. The capless executor receives only the `deploy-orchestrator` supplementary group, allowing read-only build-context traversal without access to mode-0600 state or any container-runtime group.

The runner validates JSON and connects only to `/run/deployment-executor/control.sock`. The socket authenticates the peer UID and activates a root service with no IP address family. The executor repeats every authorization check, records idempotency state before effects, and invokes only the exact `build`, `gate`, `promote`, `rollback` or `health` mode-0700 command from its root-only command directory. The executor socket, orchestrator and service proxy all ship disabled.

The service proxy is a static L4 HAProxy boundary. Team traffic uses `10.60.<team>.2:7001..7006`, staging uses `10.60.<team>.3:7001..7006`, and fixed loopback targets provide two live slots and one gate slot. Every server starts disabled. Promotion and rollback must change only those reviewed server states through the root-only `/run/finals-service-proxy/control.sock`; no PROXY protocol or HTTP forwarding header is present, so HTTP and raw TCP services observe the same normalized source.

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

1. Copy `release.template.json` and `team.template.json` into a private commissioning workspace. Fill the six final base commits, player `BUNDLE.json` SHA-256 values, immutable factory image references, immutable private-gate artifact references and exact team identity. The checked-in templates deliberately cannot compile. Produce the four host inputs with `finals-compile-release RELEASE TEAM OUTPUT`; do not hand-edit generated files.
2. Seed `team-NN/services` from those player exports, retain the common initial monorepo commit, and clone it as `deploy-orchestrator` under umask 0027 to `/var/lib/deployment-orchestrator/repository`. The complete working tree must remain owner-writable, group-readable, never group-writable and inaccessible to other users. Install a read-only deploy key plus pinned Gitea host key below the service account's `.ssh` directory. The clone's `origin` must exactly match `remote_url`.
3. Install the compiled executor policy as `/etc/deployment-executor/policy.json`, compiled volume policy as `/etc/finals-release/volume-policy.json`, and compiled proxy configuration as `/etc/finals-release/haproxy.cfg`, all root-owned mode 0600. Install the five reviewed backend commands below `/usr/local/libexec/deployment-executor/commands`, each root-owned mode 0700. The backend must enforce every image, bind, generation, quota and backend field already encoded in policy and implement the behavior in [RUNNER-CONTRACT.md](RUNNER-CONTRACT.md). Do not add the service account to the Docker group or mount a runtime socket into the orchestrator.
4. Install `config.json`, the compiled `services.json`, `webhook.secret` and `anvil.token` as root-only files below `/etc/deployment-orchestrator`. Add `10.60.200.10 finals.h7tex.com` to the production host's private resolution so tick HTTPS keeps the public certificate name without public hairpinning.
5. Build without embedding source state in the image, then install:

   ```bash
   mkdir -p build
   CGO_ENABLED=0 go build -trimpath -ldflags='-s -w' -o build/deployment-orchestrator ./cmd/deployment-orchestrator
   CGO_ENABLED=0 go build -trimpath -ldflags='-s -w' -o build/runner ./cmd/deployment-runner
   CGO_ENABLED=0 go build -trimpath -ldflags='-s -w' -o build/executor ./cmd/deployment-executor
   CGO_ENABLED=0 go build -trimpath -ldflags='-s -w' -o build/deployment-orchestrator-state ./cmd/deployment-state
   sudo ./install.sh build/deployment-orchestrator build/runner build/executor build/deployment-orchestrator-state
   ```

6. Before the first start, verify the live factory digest for every service and create the durable state exactly once:

   ```bash
   sudo -u deploy-orchestrator \
     /usr/local/bin/deployment-orchestrator initialize \
     --config /run/credentials/deployment-orchestrator.service/config.json
   ```

   Run this through a temporary credential-bearing systemd unit; the literal `/run/credentials/...` path exists only inside the unit. Never fabricate `state.json` by hand or repeat initialization on a used box.

7. Enable one canary only after [REHEARSAL.md](REHEARSAL.md) passes and the full private challenge gate is installed. The units are shipped disabled:

   ```bash
   sudo systemctl enable --now finals-service-proxy.service deployment-executor.socket deployment-orchestrator.service
   sudo journalctl -u deployment-orchestrator.service -n 50 --no-pager
   ```

## Offline state backup

`deployment-orchestrator-state` backs up and restores `state.json` and `audit.jsonl` as one verified pair. It takes the exclusive locks held for the full orchestrator and executor lifetimes, so no container effect can remain in flight. A restore writes a durable marker before replacing either file; startup fails closed while that marker exists, and retrying the same restore completes it. Restore also requires the exact team UUID.

The image includes a static, disabled `deployment-orchestrator-backup.service`. It runs only when the orchestrator is stopped and a root-owned mode-0700 durable mount already exists at `/var/backups/deployment-orchestrator`. No timer is provided. Restore is intentionally manual:

```bash
sudo systemctl start deployment-orchestrator-backup.service
sudo /usr/local/sbin/deployment-orchestrator-state restore \
  --config /etc/deployment-orchestrator/config.json \
  --services /etc/deployment-orchestrator/services.json \
  --backup /var/backups/deployment-orchestrator/backup-YYYYMMDDTHHMMSSZ-ID \
  --confirm-team TEAM-UUID
sudo systemctl start deployment-orchestrator.service
```

The generic production image contains the account, compiler, four static binaries, hardened units, HAProxy and empty private directories, but enables nothing and installs no compiled policy, backend command, proxy configuration, credential or state. Final challenge identities and private gate artifacts, the five effect commands, production credential delivery, Anvil lifecycle integration and a mounted/tested backup target remain release blockers. The current Anvil Gate is not a substitute for the challenge repository's full two-store, five-tick, anti-oracle and private over-patch gate.
