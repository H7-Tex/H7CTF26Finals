# Runtime images

This build produces four immutable Ubuntu 24.04 images: x86 and Arm platform bases, a minimal x86 production base, and an x86 workbench base with offline build tools. Every image includes Docker Compose, bounded container logs, key-only SSH, time synchronization, audit logging and the same reviewed host baseline.

Builders accept no ingress or SSH key. Cloud-init installs and tests the role, records the reviewed source revision, removes package/build state, resets machine identity and powers off. Capture only a stopped revision-tagged builder through the separate `oci-runtime-images` stack.

The production image contains the static Deployment Orchestrator binary, its disabled unit and the fixed default-deny production host firewall. It contains no runner, challenge, flag, service manifest, repository credential or deployment key, so the orchestrator cannot start before explicit commissioning. Production resolves `finals.h7tex.com` to private Anvil address `10.60.200.10`; its TCP 9300 listener is admitted only from Anvil, control and Gitea.

The workbench image grants the default `ubuntu` user access to Docker; all other images keep Docker root-only. Runtime secrets and team keys are installed only after instance creation. Go and the C toolchain exist only during the production image build; the sealed package manifest is recorded after both are purged and the build source is removed.
