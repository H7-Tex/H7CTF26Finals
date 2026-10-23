# Adaptive Hill credential delivery

Each fixed hill host fetches exactly one `hill-v2-http` credential response from Anvil over certificate-verified TLS directly to `10.60.200.10`. The fixed hill UUID is the request path; the response must name the commissioned challenge UUID and the exact 15-team UUID set. Holder slugs are recomputed from Anvil's v0.359 contract before any file is activated.

The synchronizer converts the response into only the two files consumed by the challenge controller:

- `hill_reset`: the 48-character reset credential used by `X-Reset-Token`;
- `hill_teams`: a JSON object mapping each bearer credential to its deterministic holder slug.

Both files are installed as one generation below volatile `/run`, owned by root, and activated by one atomic symlink replacement. The Compose overlay mounts only those two read-only files at `/run/secrets/hill_reset` and `/run/secrets/hill_teams`. An existing container keeps its complete prior generation until it is recreated; a new container receives the complete new generation. No credential, response body or credential-derived identifier is written to Terraform, an image, persistent state, audit output or logs.

The legacy KoTH controller and its `/arena/koth` endpoints are not involved or changed.

## Commissioning inputs

For each host, obtain the hill UUID and challenge UUID from the reviewed Anvil admin configuration after the 15 active non-NOP teams exist. Install `/etc/finals-hill/config.json` as root-owned mode `0600`:

```json
{
  "schema_version": 1,
  "role": "hill-01",
  "slug": "current-affairs",
  "hill_id": "11111111-1111-4111-8111-111111111111",
  "challenge_id": "22222222-2222-4222-8222-222222222222",
  "team_ids": [
    "33333333-3333-4333-8333-333333333331",
    "33333333-3333-4333-8333-333333333332",
    "33333333-3333-4333-8333-333333333333",
    "33333333-3333-4333-8333-333333333334",
    "33333333-3333-4333-8333-333333333335",
    "33333333-3333-4333-8333-333333333336",
    "33333333-3333-4333-8333-333333333337",
    "33333333-3333-4333-8333-333333333338",
    "33333333-3333-4333-8333-333333333339",
    "33333333-3333-4333-8333-33333333333a",
    "33333333-3333-4333-8333-33333333333b",
    "33333333-3333-4333-8333-33333333333c",
    "33333333-3333-4333-8333-33333333333d",
    "33333333-3333-4333-8333-33333333333e",
    "33333333-3333-4333-8333-33333333333f"
  ]
}
```

The fixed role mapping is `hill-01` → `current-affairs`, `hill-02` → `majority-rules`, and `hill-03` → `tag-youre-it`. The host's existing `/etc/finals-platform/role` must match.

Create one `hill-control` age bundle containing the same `ANVIL_GAME_INTERNAL_TOKEN` used by the internal Anvil API. Encrypt it separately to each verified post-launch hill host recipient. Because the operations relay deliberately has no access to hill hosts, deliver only the age ciphertext with OCI Run Command and execute:

```bash
sudo finals-install-secret-bundle hill-control < hill-control.age
```

Install the reviewed challenge release at `/opt/finals-hill`, with its immutable image references and the matching base Compose file. Do not add credentials to that directory. Then run, in order:

```bash
sudo systemctl enable --now finals-hill-credentials.service
sudo finals-hill-credentials check
sudo finals-hill-compose config
sudo finals-hill-compose up
```

Confirm the container health endpoint on the host's assigned port, prove the other two hill ports are closed, and only then open the router's persisted challenge-access gate. A missing token, wrong TLS peer, wrong hill/challenge/team set, malformed response, incomplete local generation or unavailable Anvil endpoint prevents synchronization and therefore prevents first start.

For an intentional credential rotation, restart the credential service, then `sudo finals-hill-compose recreate`. `finals-hill-compose` always uses the same four files: the release compose, the credentials overlay, the role network overlay and the role endpoint overlay, which publishes only `10.60.210.1N:710N`. On `hill-02` it adds `hill-02.evm.compose.yaml`, which maps the private EVM mnemonic to `/run/finals-hill/evm/mnemonic`. `finals-hill-compose up` generates that file once on the host with `cast wallet new-mnemonic` from the release EVM image (mode `0444` under a root-only `0700` directory) and keeps it while it exists. The EVM keeps no chain state, so after a reboot a new mnemonic starts a clean chain and the arena redeploys its contract. To rotate it, run `finals-hill-compose down`, remove the file and run `up`. Never run `docker compose` against a hill with a partial file set. Repeating the sequence with unchanged credentials is idempotent.
