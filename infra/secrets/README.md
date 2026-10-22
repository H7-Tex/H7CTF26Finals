# Host-bound secret bootstrap

Production secrets are encrypted to the unique Ed25519 host key generated after an instance boots. Golden-image builder keys are deleted before capture. The installer accepts fixed bundle types, reads age ciphertext from standard input, validates the complete payload, and writes only its compiled-in root-owned paths.

The operations host is the commissioning relay. Temporarily enable service-subnet warm-up egress, retrieve its post-launch SSH public key and fingerprint through OCI Run Command, compare them with the serial-console identity line, and encrypt its operations bundle locally. Send only age ciphertext through Run Command. Disable service warm-up egress immediately after the bundle and access checks succeed.

For private hosts, read each `FINALS_HOST_RECIPIENT` line from OCI console history, compare its fingerprint with a key scan from the operations host, and encrypt a separate bundle to that exact public key. The operations host copies the ciphertext over SSH using the dedicated event-only operations-relay identity whose public half is in target launch metadata, then runs the fixed installer remotely. It never relays plaintext.

Create a bundle locally without shell interpolation:

```bash
python3 - <<'PY' > bundle.json
import base64, json, pathlib
files = {
    "environment": pathlib.Path("repository.env").read_bytes(),
    "certificate": pathlib.Path("fullchain.pem").read_bytes(),
    "private_key": pathlib.Path("privkey.pem").read_bytes(),
}
print(json.dumps({"type": "repository", "files": {k: base64.b64encode(v).decode() for k, v in files.items()}}))
PY
age --recipient-file verified-host-ed25519.pub --output repository.age bundle.json
```

Install on the intended host with no plaintext file:

```bash
sudo finals-install-secret-bundle repository < repository.age
```

Supported types are `gateway-wireguard`, `gateway-reconciler`, `anvil`, `control-reconciler`, `control-checkers`, `repository`, and `operations-relay`. `control-checkers` contains only the short-lived Anvil admin JWT used by the default-off checker commissioning flow; successful commissioning deletes it. The operations relay identity must be a new event-only Ed25519 key, never a copied organizer or user identity. Its raw public half is supplied separately from organizer keys; Terraform adds a restrictive forced-command authorization only to both gateways, platform, control and repository. Its fixed bundle contains the private half and exactly those five verified Ed25519 `known_hosts` entries. Mirror and hill hosts receive neither this key nor a relay known-host entry. The target receiver accepts only `install TYPE`, maps the host's immutable role to allowed bundle types and invokes one exact passwordless installer command. After installing `gateway-reconciler`, run `event-router-authorize-reconciler /etc/event-router/reconciler_authorized_key` on each gateway. That separate wrapper validates the key again and writes only a forced-command, no-forwarding SSH authorization.
