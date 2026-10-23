# Model A service runtime

This lane starts the six Attack-Defense services on each team's production box without the Deployment Orchestrator. It is fixed to challenge commit `c901df95b3fad91349c66e40a631a633b92e9241`.

The release builder exports only each manifest's player allowlist, builds the six factory images through the committed Compose build definitions with build networking disabled, and saves three artifacts:

- `player-bundles.tar`
- `factory-images.tar`
- `base-images.tar`

`release.json` records every artifact SHA-256, factory and base image ID, service identity, and storage quota. The offline registry is not required.

The production image installs the fixed tools with:

```text
sudo infra/model-a-runtime/install.sh
```

An organizer prepares the offline release from a clean exact challenge checkout:

```text
python3 infra/model-a-runtime/prepare-release.py /home/abu/Main/Projects/H7CTF26Finals-challenges /secure/output/model-a-c901df9
```

After the production data volume initializer has mounted XFS with project quota enforcement, root installs one team box with:

```text
finals-model-a-install /secure/input/model-a-c901df9 TEAM_NUMBER RELEASE_JSON_SHA256
```

The expected release hash must arrive through the organizer's trusted commissioning command. The installer verifies that root hash, all archive hashes, and all image IDs; reasserts each live-generation byte and inode hard limit; installs factory and editable player trees; starts the six health-checked containers; and enables `finals-service-proxy`. HAProxy owns `10.60.T.2:7001-7006`; containers publish only to `127.0.0.1:17001-17006`. No PROXY protocol or source header reaches a service.

The service networks are fixed to `172.31.60.0/28`, `172.31.60.16/28`, `172.31.60.32/28`, `172.31.60.48/28`, `172.31.60.64/28`, and `172.31.60.80/28` in port order. The production host firewall must allow host output to the exact aggregate `172.31.60.0/24`, or HAProxy's DNAT path is dropped when Docker's userland proxy is disabled.

The editable trees are under `/opt/finals/services/<slug>`. Durable state remains under `/srv/finals/service-data/<port>/live` and is mounted at `/data`. Before first start, the installer creates each service's unique instance key with its required raw or hexadecimal encoding, service UID ownership, and mode `0600`. A reinstall preserves a valid key and refuses an unsafe owner, mode, size, encoding, or file type.

The player commands are:

```text
h7 status
h7 logs <service>
h7 rebuild <service>
h7 restart <service>
h7 reset <service>
h7 diff <service>
```

`h7 rebuild` uses only local immutable base images and a build network of `none`. `h7 reset` restores factory source and the exact factory image ID while preserving `/data`. `finals-rehearse-production-quota` must pass on the pristine production volume before commissioning; this installer then refuses a non-XFS or non-enforcing mount and reasserts every live-generation hard byte and inode limit.

Run source and export checks with:

```text
CHALLENGE_REPO=/home/abu/Main/Projects/H7CTF26Finals-challenges infra/model-a-runtime/tests/run.sh
```

Run the isolated Docker acceptance with:

```text
infra/model-a-runtime/tests/local-acceptance.py /secure/output/model-a-c901df9 /home/abu/Main/Projects/H7CTF26Finals-challenges /secure/evidence/model-a-local.json
```

It starts unique local projects, runs each exact checker through a metadata-free TCP proxy, verifies both stores and one exploit per checker, rebuilds an edited service, proves old-flag retention, resets factory source and image while retaining data, records image IDs and timings, and removes its containers and networks.

The production firewall source gate verifies the platform-owned host-output allowance:

```text
infra/model-a-runtime/tests/firewall-path.py
```

Do not copy the challenge repository to a team box. Checkers, attacks, patches, manifests, evidence, and organizer credentials remain outside every generated player artifact.
