# Closed-staging acceptance gate

This gate is the last default-closed evidence boundary before any player bundle or challenge metadata may be published. It validates one private staging manifest against the locked six Attack-Defense services and three Hills, immutable infra/Anvil/challenge revisions and immutable runtime image IDs.

Run it only after every rehearsal has completed on production-equivalent hosts:

```text
infra/acceptance/run.sh /private/evidence/evidence.json
```

Each of the thirteen checks must attach its own non-empty transcript or machine report by relative path, exact byte size and SHA-256. The validator rejects duplicate or missing checks, reused artifacts, symlinks, path escapes, stale structural claims and any attached file containing a raw `H7CTF` flag, private-key material, a WireGuard private key or an unmasked 64-hex team token.

The required live evidence is:

- exact 6+3 immutable inventory and default-closed player visibility;
- all six two-store/five-tick checkers plus NOP-only, audit-only Reference Attack compatibility through normalized ingress;
- promotion, manual rollback and automatic rollback with reconciled deployment events and no data snapshot restore;
- redaction, host-bound secret rotation, cross-container denial and teardown;
- verified Anvil Postgres, Gitea and Deployment Orchestrator restores to new targets;
- gateway failover and failback without changing `129.225.71.11` or `140.245.253.126`, including a real UDP WireGuard handshake;
- one-team six-service and 15-team 90-candidate load, all 15 factory restores, and zero cross-team access;
- at least 200 error-free rounds and the `00:00-06:00` Asia/Kolkata Night Watch transitions;
- the complete attributed player journey through VPN, workbench, attack, flag submission, patch rejection/promotion/rollback and Hill claim/lock.

Start from `evidence.template.json`, replace every placeholder, keep the bundle private and store it with the release ledger. The validator proves the bundle is complete and internally consistent; it does not run the rehearsals or make organizer-authored evidence trustworthy by itself. Retain the original host transcripts and monitoring exports under the same access controls.

The gate intentionally has no override or partial-green mode. If one check is unavailable or red, the release stays closed.
