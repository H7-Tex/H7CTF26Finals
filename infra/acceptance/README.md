# Closed-staging acceptance gate

This gate is the last default-closed evidence boundary before any player bundle or challenge metadata may be published. It validates one private staging manifest against the locked six Attack-Defense services and three Hills, immutable infra/Anvil/challenge revisions and immutable runtime image IDs.

Run it only after every rehearsal has completed on production-equivalent hosts:

```text
infra/acceptance/run.sh /private/evidence/evidence.json
```

Every manifest selects exactly one deployment `model`: `C` for the verified deployment pipeline or `A` for direct team administration of its production host. Each profile requires exactly thirteen checks, and every check must attach its own non-empty transcript or machine report by relative path, exact byte size and SHA-256. The validator rejects a missing or unknown model, cross-profile checks, duplicate or missing checks, reused artifacts, symlinks, path escapes, stale structural claims and any attached file containing a raw `H7CTF` flag, private-key material, a WireGuard private key or an unmasked 64-hex team token.

Both profiles require live evidence for:

- exact 6+3 immutable inventory and default-closed player visibility;
- all six two-store/five-tick checkers plus NOP-only, audit-only Reference Attack compatibility through normalized ingress;
- redaction, host-bound secret rotation, cross-container denial and teardown;
- gateway failover and failback without changing `129.225.71.11` or `140.245.253.126`, including a real UDP WireGuard handshake;
- at least 200 error-free rounds and the `00:00-06:00` Asia/Kolkata Night Watch transitions;
- a complete model-specific player journey.

Model C additionally requires promotion, manual and automatic rollback; Anvil/Gitea/Deployment Orchestrator restores; one-team and 90-candidate load; all factory restores; and the workbench-to-promotion player journey.

Model A instead requires all 15 `ubuntu` production-key grants and revocations; all 210 directed cross-team SSH paths denied while each team reaches only its own `10.60.T.2:22`; one production reset or reimage with fixed IP and service data preserved; an independent Anvil Postgres restore; and the VPN-to-production patch/restart/recovery journey. Model A has no Gitea, Deployment Orchestrator, promotion or rollback evidence requirement.

Start Model C from `evidence.template.json` or Model A from `evidence.model-a.template.json`, replace every placeholder, keep the bundle private and store it with the release ledger. The validator proves the bundle is complete and internally consistent; it does not run the rehearsals or make organizer-authored evidence trustworthy by itself. Retain the original host transcripts and monitoring exports under the same access controls.

The gate intentionally has no override or partial-green mode. If one check is unavailable or red, the release stays closed.
