# OCI runtime image builders

This temporary Resource Manager stack creates four outbound-only builders in the public edge subnet. The builders accept no ingress or SSH key. Each installs and tests one runtime role from the reviewed repository revision, seals its state and powers off. The platform-x86 build also pins, tests and prebuilds Anvil v0.354.0 at `c879ebf6c9a583416edf141830fbc1e606e0eb1c`.

The production builder tests the Deployment Orchestrator with Ubuntu 24.04's Go 1.22 toolchain, installs one static binary and its disabled unit, then purges Go and the C toolchain before the resolved package manifest is recorded. The generic image deliberately omits the runner, service manifests, repository material and credentials.

The expanded build source is too large for OCI instance metadata. Terraform therefore renders four fixed-path shell payloads with base64 file bodies, stores them as objects in one transient no-public-access bucket and creates object-read PARs with an explicit reviewed RFC3339 expiry no more than 24 hours away. Instance metadata contains only the short-lived PAR, exact size and SHA-256 plus a small verifier; an apply-time assertion keeps encoded user data below 16 KiB. The verifier bounds the download, checks it and executes the fixed payload directly. It never recursively invokes cloud-init, and no GitHub credential or private repository token is used.

The first plan is one private bucket, four source objects, four PARs, one NSG, one egress rule and four builder instances. A stopped instance is the success signal. Do not capture a running builder. Destroy this builder stack after successful image capture; dependency ordering stops the instances before revoking PARs and deleting the transient objects.
