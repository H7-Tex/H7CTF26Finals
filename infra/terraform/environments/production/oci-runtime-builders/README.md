# OCI runtime image builders

This temporary Resource Manager stack creates four outbound-only builders in the public edge subnet. The builders accept no ingress or SSH key. Each installs and tests one runtime role from the reviewed repository revision, seals its state and powers off. The platform-x86 build also pins, tests and prebuilds Anvil v0.360.0 at `2385596058c0d861981132572f9b3359f0a8a869`.

The production builder tests the deployment package with Ubuntu 24.04's Go 1.22 toolchain, installs four static binaries and their default-off units, then purges Go and the C toolchain before the resolved package manifest is recorded. The generic image includes the unprivileged runner adapter and socket executor boundary but deliberately omits the executor policy, five real effect commands, service manifests, repository material and credentials.

The expanded build source is too large for OCI instance metadata. Terraform therefore renders four fixed-path shell payloads with base64 file bodies, stores them as objects in one transient no-public-access bucket and creates object-read PARs with an explicit reviewed RFC3339 expiry no more than 24 hours away. Instance metadata contains only the short-lived PAR, exact size and SHA-256 plus a small verifier; an apply-time assertion keeps encoded user data below 16 KiB. The verifier bounds the download, checks it and executes the fixed payload directly. It never recursively invokes cloud-init, and no GitHub credential or private repository token is used.

The first plan is one private bucket, four source objects, four PARs, one NSG, one egress rule and four builder instances. A stopped instance is the success signal. Do not capture a running builder. Destroy this builder stack after successful image capture; dependency ordering stops the instances before revoking PARs and deleting the transient objects.

Each role must stop naturally within its bounded build window. Serial evidence must show verified download and digest checks, every role-applicable install and test phase, seal scheduling and a final `phase=seal status=success` record binding the exact source revision, role and package-manifest SHA-256. Missing, failed or out-of-order evidence keeps that role red.

The v0.0.43, v0.0.44, v0.0.46, v0.0.47 and v0.0.48 builder generations failed before all four roles sealed and are prohibited from capture. Their instance OCIDs are recorded in the `oci-runtime-images` validation and README.
