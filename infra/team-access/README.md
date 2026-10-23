# Team workbench access

Team workbenches use individual Ed25519 keys. Shared passwords are not a fallback. The organizer key remains the break-glass identity and cannot be removed by a team-key update.

## Compile the reviewed submission

Create a private, uncommitted manifest with exactly `team-01` through `team-15`:

```json
{
  "schema_version": 1,
  "change_id": "ticket-2026-001",
  "teams": [
    {
      "team": "team-01",
      "participants": [
        {"participant_id": "registration-id", "public_key": "ssh-ed25519 AAAA..."}
      ]
    }
  ],
  "spare_assignment": null
}
```

The abbreviated example must be expanded to all 15 teams. Participant identifiers must be roster-stable IDs, not names or email addresses.

```bash
python3 infra/team-access/team-access.py compile \
  --manifest /private/path/team-access.json \
  --organizer-keys /home/abu/.ssh/id_ed25519_central.pub \
  --output /private/path/team-access-output
```

Compilation fails on a missing team, malformed/non-Ed25519 key, repeated participant, or any repeated key fingerprint across teams or organizers. Review `fingerprints.json` against the roster. The generated `team-workbench-ssh-authorized-keys.auto.tfvars.json` is valid input for the initial fleet plan and contains public keys only; it remains uncommitted because it contains participant access data.

## Apply or replace keys after launch

The final workbench image installs `finals-team-access`. Send the matching `payloads/workbench-NN.json` as standard input through OCI Run Command:

```bash
sudo /usr/local/sbin/finals-team-access apply <<'JSON'
{reviewed payload}
JSON
```

The first apply proves the reviewed organizer key is already present, pins it root-only, and atomically rewrites `ubuntu`'s authorized keys. Later applies must contain that exact organizer set. A replacement therefore revokes the old participant key without risking organizer access. The command logs only its change ID and host.

To undo the last update:

```bash
sudo /usr/local/sbin/finals-team-access rollback
```

Rollback swaps the current and previous reviewed states and preserves the pinned organizer key. It is available for fixed team workbenches and the spare. A fixed workbench cannot be reassigned to another team. The spare accepts either one team assignment or an unassigned payload with no team keys; rehearse assignment and rollback before the event.

After every apply or rollback, verify one organizer login, one affected participant login, rejection of the revoked key, and the expected host identity over the VPN. Record the change ID, participant, team, fingerprint, Run Command ID and results in the access ledger.
