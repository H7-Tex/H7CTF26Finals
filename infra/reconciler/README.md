# VPN peer reconciler

The reconciler runs only on the private control host at `10.60.201.20`. Every 15 seconds it reads the active desired peers from Anvil, validates the exact router inventory contract, and publishes one identical root-only snapshot to the standby gateway before the primary gateway.

Anvil remains the identity and revocation ledger. This component receives no private keys or personal data and logs only outcome, generation, peer count and gateway role. A failed request never changes gateway state. A partial publish leaves a durable pending generation that is replayed before Anvil is queried again.

## Fixed production contract

- Anvil: `GET https://finals.h7tex.com/api/v1/internal/arena/vpn/peers`
- Authentication: `Authorization: Bearer $ANVIL_GAME_INTERNAL_TOKEN`
- Response: `{ "peers": [...] }`, with the five fields documented in the router inventory contract
- Standby gateway: `10.60.250.11`
- Primary gateway: `10.60.250.10`
- SSH account: `peer-reconciler`, forced command only

The URL and secret path are explicit in `/etc/peer-reconciler/config.json`. The tracked file contains no secret.

## Commissioning

Build the control-host image from this directory or run `install.sh` during its reviewed image build. Do not start the timer until Anvil, both gateways and their immutable images are commissioned.

1. Add this exact private resolution on the control host so HTTPS retains the public certificate name while avoiding public hairpinning:

   ```text
   10.60.200.10 finals.h7tex.com
   ```

2. Generate one dedicated Ed25519 key as the `peer-reconciler` account. Install the private half at `/etc/peer-reconciler/id_ed25519` with owner `peer-reconciler:peer-reconciler` and mode `0600`.
3. On each gateway, pass the public half to `event-router-authorize-reconciler`. The resulting account is restricted by both `sshd` policy and its authorized-key options: no shell, PTY, forwarding, tunnel, agent or arbitrary command.
4. Verify each gateway SSH host-key fingerprint through the OCI console, then install the pinned keys in `/etc/peer-reconciler/known_hosts`. Do not trust an unverified `ssh-keyscan` result.
5. Install the Anvil internal token at `/etc/peer-reconciler/anvil.token` with owner `peer-reconciler:peer-reconciler` and mode `0600`. Use the same scoped value configured by Anvil; never pass it on a command line.
6. Confirm `/etc/peer-reconciler`, both secret files and `/var/lib/peer-reconciler` are inaccessible to other users.
7. Run one foreground reconciliation and inspect its structured journal entry:

   ```bash
   sudo -u peer-reconciler /usr/local/libexec/peer-reconciler/reconcile.py
   sudo journalctl -u peer-reconciler.service -n 20 --no-pager
   ```

8. Confirm both gateways report the same generation and peer count, then enable polling:

   ```bash
   sudo systemctl enable --now peer-reconciler.timer
   ```

Run `tests/run.sh` before building the image. The tests cover no-change suppression, standby-first ordering, partial-failure replay and invalid desired state.

## Failure and recovery

- Anvil or TLS failure: the service exits non-zero and keeps the active and pending state untouched.
- Standby failure: the primary is not contacted. The durable pending generation is retried on the next timer run.
- Primary failure: the standby may be one generation ahead. The same pending snapshot is replayed to both gateways until the primary succeeds.
- Invalid, stale or changed same-generation input: the gateway rejects it before runtime state is changed.

To freeze peer changes, stop and disable `peer-reconciler.timer`; existing WireGuard state remains active. After recovering the failed dependency, run the service once and verify both gateways before enabling the timer again. Never delete `active.json` or `pending.json` to work around a generation error; reconcile the records from the journal and Anvil ledger first.

Include `/var/lib/peer-reconciler/active.json` and any `pending.json` in the control-host backup. Restore that state before enabling the timer on a replacement host so generations never restart from one.
