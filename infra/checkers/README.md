# Private checker runtime

The control host runs exactly six reviewed ENOWARS v2 HTTP checker images. Anvil remains the only tick scheduler: this component imports immutable checker artifacts, supervises the six checker/database pairs, publishes private checker endpoints and registers those endpoints once in Anvil. It does not mint flags, schedule tasks or contain checker source.

## Fixed runtime contract

- Host: control at `10.60.201.20`.
- Checker endpoints: `10.60.201.20:9001-9006`, reachable only from Anvil at `10.60.200.10`.
- Supervisor health: `127.0.0.1:9160/healthz` and readiness at `/readyz`.
- One internal Docker network connects each checker to only its Mongo database. A second bridge permits checker calls into the private service networks with bridge inter-container communication disabled, so checkers cannot reach each other. The control subnet has no public default route.
- Mongo state survives service and host restarts below `/var/lib/checker-runtime/data`. Runtime import and registration journals are atomically written to `/var/lib/checker-runtime/state.json`.
- The public Mongo image is digest-pinned in the reviewed host image. Private checker image archives are never placed in Git, Terraform, cloud-init or a golden image.

The service is disabled and cannot start until both `/etc/checker-runtime/enabled` and a valid root-only manifest exist. Control-role activation explicitly disables it. Do not create the enable gate by hand; use the commissioning command only after the checks below pass.

## Prepare artifacts

Build the six checker images from one reviewed challenge-repository revision on a trusted offline build host. Give every image a revision tag, record the Docker image ID, and export each image independently:

```bash
docker build --tag finals/checkers/SERVICE:SOURCE_REVISION services/SERVICE/checker
docker image inspect --format '{{.Id}}' finals/checkers/SERVICE:SOURCE_REVISION
umask 077
docker image save --output checker-image.tar finals/checkers/SERVICE:SOURCE_REVISION
sha256sum checker-image.tar
stat --format '%s' checker-image.tar
```

Start from `artifact-manifest.example.json`. Replace every placeholder with the reviewed source revision, archive byte size, archive SHA-256 and exact `sha256:...` image ID. Do not alter the organizer-confirmed categories, locked service order or runtime fields without a reviewed contract change.

Transfer the six archives through an encrypted, audited organizer path and decrypt them only on the control host. Install this exact layout as root; directories are mode `0700`, archives and manifest are `0600`, and no component may be a symbolic link:

```text
/etc/finals-platform/checkers/artifact-manifest.json
/opt/finals-checkers/SERVICE/checker-image.tar
```

Run the read-only preflight before installing any credential:

```bash
sudo /usr/local/libexec/finals-platform/checker-preflight
```

## Register and commission

Anvil v0.355 exposes service creation only through its admin API. Consequently, registration needs a short-lived admin JWT once; steady-state runtime needs no Anvil credential. Keep the game stopped, confirm no conflicting service rows exist, create a token with the shortest practical expiry, wrap it as the single `admin_token` file in a `control-checkers` host-bound age bundle, then relay only the ciphertext:

```bash
sudo finals-operations-ssh control control-checkers < control-checkers.age
```

On the control host:

```bash
sudo checker-runtime-commission
```

Commissioning validates every byte, imports and verifies every image ID, creates all twelve containers, waits for six healthy checker endpoints, journals and registers the services in deterministic order, creates the enable gate, starts the disabled unit, verifies loopback readiness, and deletes the admin token. It fails closed and removes only labeled managed containers on an incomplete first attempt. A crash after an Anvil POST is recovered from the durable pending journal; an existing unjournaled, disabled, duplicated, unexpected or drifted service is rejected, and the final inventory must be exactly the six locked services.

This registrar cannot compare `flag_stores`, noise/havoc counts or sort order on an existing row because the current Anvil list response omits them, and Anvil cannot update those fields. Review them in Anvil before play. A future internal-token idempotent service-upsert endpoint would remove this one-time admin-token and visibility limitation.

## Operate and recover

```bash
sudo systemctl status checker-runtime.service
sudo /usr/local/libexec/checker-runtime/runtime.py status
curl --fail http://127.0.0.1:9160/readyz
journalctl -u checker-runtime.service
```

Logs are structured and include only fixed service slugs, component names and bounded error classes. They do not include flags, requests, response bodies, checker output or credentials. Anvil calls the private endpoints and owns task scheduling and SLA accounting.

Every service start revalidates the archives, idempotently restores missing images, verifies the persistent import journal, recreates missing containers and repairs the checker egress attachment. A manifest, archive, image-ID, container-label or network-contract mismatch leaves readiness closed. An unmanaged container is never replaced.

To stop without deleting Mongo state:

```bash
sudo systemctl disable --now checker-runtime.service
sudo rm -f /etc/checker-runtime/enabled
```

Disabling the runtime does not remove Anvil service rows. While the game is stopped, disable or delete those rows through the reviewed admin procedure before changing the manifest. Recommissioning a changed checker set requires a fresh reviewed manifest, fresh archives, a fresh short-lived admin JWT and an explicit registration-state migration; do not edit `state.json` in place.
