# Runner contract

The runner is a separately reviewed organizer component. The Deployment Orchestrator executes one root-owned absolute path with exactly one argv value: `build`, `gate`, `promote`, `rollback` or `health`. It sends one schema-version-1 JSON request on stdin and accepts one JSON result, at most 64 KiB, on stdout. A timeout kills the runner's complete process group. Any non-zero exit, extra JSON field, malformed digest, policy-version mismatch or missing required identity fails closed.

The same `operation_id` may be retried after a process or host failure. Every operation must therefore be idempotent and return the already completed result when its complete request hash matches. Reuse with different input must fail. IDs are unique across build, gate, promote, recovery and rollback requests; only a byte-equivalent retry reuses one.

## Privilege boundary

`/usr/local/libexec/deployment-orchestrator/runner` runs as `deploy-orchestrator`; root ownership of that file does not grant it privilege. It is a schema-validating client to the root-owned, socket-activated `deployment-executor.service`. The `AF_UNIX` socket is writable only by `root:deploy-orchestrator`. `SO_PEERCRED` must match the one numeric UID in the root-only policy. There is no network listener.

The executor independently validates the exact team, service, repository, source identity, immutable digests, policy version, resource limits and data mode. It records the canonical request hash below `/var/lib/deployment-executor/operations` before invoking a backend. A byte-identical retry replays a completed result or retries a pending idempotent backend request; reuse of the ID with any changed field fails. Requests for different services may execute independently, while effects for one service are serialized.

Each operation maps to one mode-0700, root-owned command directly below `/usr/local/libexec/deployment-executor/commands`. Commands receive the operation as their only argument and the validated request as JSON on stdin. They return strict JSON on stdout. No shell string or player-controlled argv is constructed. The policy, command directory and executor state are root-only.

The adapter, executor and systemd units are installed in the production image, but the socket ships disabled and cannot start without `/etc/deployment-executor/policy.json`. The five real backend commands, container-runtime/registry policy and credentials are commissioning inputs and are intentionally absent. Adding `deploy-orchestrator` to a container-runtime group, making the adapter setuid, granting capabilities or mounting the Docker socket into the orchestrator is prohibited.

Commissioning must also extend the reviewed service policy and backend preflight to bind each service identity to its one fixed TCP port and XFS project-quota tree: `7001=1GiB/65536`, `7002=1GiB/65536`, `7003=512MiB/32768`, `7004=1GiB/65536`, `7005=2GiB/131072`, and `7006=1GiB/65536` below `/srv/finals/service-data/<port>/{live,gate,recovery}`. Named volumes, bind mounts outside that tree, quota mismatches and undeclared persistence must fail before any effect. The option-A boundary does not yet encode this map, so the socket must remain disabled until the final six service manifests and real backend enforce it.

## Required behavior

`build` composes the pinned organizer build definition with only the candidate service tree at the exact commit. It verifies the committed player-bundle provenance, uses preloaded or internally mirrored digest-pinned bases and cached dependencies, and denies build-network access. It runs outside scored service capacity with the requested memory, CPU, PID, context and timeout caps. It never mounts a cloud metadata credential, production secret, host Docker socket or another team's cache. Success returns the registry manifest digest in `digest`.

`gate` requires `data_mode: copy-current`. It creates a service-aware disposable copy of current live data, returns its opaque identifier in `data_copy_id`, starts the full candidate service and dependencies in the checker-only staging network, waits for readiness, then runs both stores, every declared noise/havoc variant, old-flag reads for five ticks and private over-patch probes. It never runs reference attacks. Failure destroys staging and returns only a curated `public_message`.

`promote` requires the candidate and current immutable digests, `data_mode: preserve-current` and the authorized promotion tick. It creates a service-aware recovery snapshot, health-checks a blue/green candidate, swaps traffic by digest without recreating the durable volume, and verifies the live digest. Success returns the candidate `digest`, `healthy: true` and `recovery_snapshot_id`.

`rollback` accepts only `target_digest`, retains the current durable volume, swaps to that digest and verifies health. Success returns the exact target digest and `healthy: true`. Snapshot restore is not part of this operation.

`health` verifies that the requested immutable digest is the live healthy factory/current image. Commissioning uses this operation before creating state.

Every result includes the exact `runner_policy_version` from the request. Logs and result fields must exclude flags, webhook keys, deploy keys, registry credentials, build secrets, hidden gate inputs and player source content.

## Minimal request and result

```json
{
  "schema_version": 1,
  "operation": "gate",
  "operation_id": "4c33290f2f614e3290bb2cc4702b9834",
  "team_id": "11111111-1111-4111-8111-111111111111",
  "team_number": 1,
  "service": "sign-me-in",
  "repository_path": "/var/lib/deployment-orchestrator/repository",
  "commit": "1111111111111111111111111111111111111111",
  "base_commit": "2222222222222222222222222222222222222222",
  "bundle_sha256": "3333333333333333333333333333333333333333333333333333333333333333",
  "policy_version": "finals-1",
  "candidate_digest": "sha256:4444444444444444444444444444444444444444444444444444444444444444",
  "factory_digest": "sha256:5555555555555555555555555555555555555555555555555555555555555555",
  "data_mode": "copy-current",
  "previous_flag_ticks": 5,
  "resources": {
    "network_mode": "none",
    "maximum_context_bytes": 52428800,
    "memory_bytes": 805306368,
    "cpu_millis": 1000,
    "pids": 256,
    "timeout_seconds": 90
  }
}
```

```json
{
  "ok": true,
  "data_copy_id": "copy-opaque-01",
  "runner_policy_version": "finals-1"
}
```
