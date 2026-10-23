# Deployment rehearsal

Production enablement requires both rehearsals below with immutable evidence: repository commit, orchestrator binary SHA-256, policy version, runner version, factory/candidate digests, audit sequence range, timing and operator. Synthetic flags must follow the event format and must never be reused in the live game.

Before either rehearsal, run `finals-rehearse-production-quota` on an uncommissioned host and record its output. It must prove byte and inode exhaustion in a live generation does not consume gate or recovery capacity. Run `finals-service-proxy-smoke`; its HTTP-shaped and raw TCP flows must reach the backend from the same normalized source with unchanged payloads. Validate the compiled HAProxy configuration and prove all 18 backends are disabled before commissioning chooses a factory slot.

## One-team canary

Run the complete path on a disposable team before provisioning all 15 instances:

1. Prove missing/weak secrets, wrong team/repository/branch, invalid signature, reused delivery ID, non-descendant history and an unknown root all fail before fetch/build.
2. Drop one valid webhook and prove the 15-second poll discovers the exact remote head once.
3. Push changes to two allowed service directories and prove only those services queue. Change the Dockerfile, manifest, Compose, health check and a root file; each must be rejected with production untouched.
4. Prove no-egress build, limits, timeout and context cap. Verify the candidate identity is an immutable registry manifest digest and its trusted build definition includes the committed bundle provenance.
5. Prove the gate uses a service-aware copy of current data, covers two stores and five old ticks, destroys staging on failure and never changes live volumes.
6. Promote inside the quiet window. Verify current/LKG/factory are separate, the live digest equals audit state and flags/data survive the cutover.
7. Roll back to LKG, factory and one historical green digest. Verify the digest changes in under 15 seconds and data written after promotion remains.
8. Submit two causal checker failures and prove automatic rollback occurs only when the previous digest is healthy. An `ERROR`, a stale tick, a mismatched digest or non-consecutive ticks must not trigger it.
9. Kill the service during build, gate and promotion. Restart from durable pending state; an ambiguous promotion must restore the prior digest or stop for operator recovery.
10. Stop Anvil, Gitea, runner and registry independently. Existing production must continue; status and audit must reconcile after recovery without duplicated promotion.
11. Reject one deployment-event request after Anvil commits it, then retry it. Verify the same team, service, audit sequence and state are accepted idempotently, the durable report cursor advances only after HTTP 200/201, and no commit, digest, message, trace, flag or runner output reaches Anvil.
12. Exercise an offline state backup: stop the orchestrator cleanly, copy `state.json` and `audit.jsonl` together with modes and ownership to the encrypted operations backup target, restart it, and validate the copy with `OpenStore` semantics on a spare host using the identical config and manifest hash. Restore that pair on the spare and replay the persisted in-flight intent. Repository data is re-cloned from the pinned private remote; credentials are restored through the secret system and must never enter the backup archive.

Targets are push acknowledgement under 5 seconds, p95 gate result under 90 seconds, p95 healthy production under 120 seconds and rollback under 15 seconds.

## Fifteen-team burst

From 15 private repositories, push one allowed change to all six services in a controlled burst. Verify 90 isolated candidates, one in-flight candidate per team/service, at most one successful promotion per service/tick, no cross-team cache/data/registry access, bounded production load and complete Anvil reconciliation. Record queue depth, oldest age and build/gate/promotion p50/p95/p99.

Then repeat a mixed burst containing valid patches, protected paths, build failures, gate failures, lost webhooks, manual rollbacks and two causal post-promotion failures. No failed candidate may change a live digest or durable data. Do not call the platform production-ready until every audit sequence is accounted for and all 15 factory restores have been exercised.

The repository has a static offline backup/restore helper but no production-host secret-bundle target, encrypted operations mount or retention workflow. Those commissioning inputs and a restore drill remain mandatory. Do not schedule live two-file copies: without stopping the writer they are not a consistent backup boundary.
