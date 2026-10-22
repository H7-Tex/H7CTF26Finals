# Runtime images

This build produces four immutable Ubuntu 24.04 images: x86 and Arm platform bases, a minimal x86 production base, and an x86 workbench base with offline build tools. Every image includes Docker Compose, bounded container logs, key-only SSH, time synchronization, audit logging and the same reviewed host baseline.

Builders accept no ingress or SSH key. Cloud-init installs and tests the role, records the reviewed source revision, removes package/build state, resets machine identity and powers off. Capture only a stopped revision-tagged builder through the separate `oci-runtime-images` stack.

The production image contains four static deployment binaries—the Deployment Orchestrator, unprivileged runner adapter, root socket executor and offline state helper—plus their default-off units, the fixed default-deny production host firewall and the fail-closed XFS data-volume initializer. It contains no executor policy or real effect command, challenge, flag, service manifest, repository credential or deployment key, so commissioning hard-fails before the orchestrator can start. Production resolves `finals.h7tex.com` to private Anvil address `10.60.200.10`; its TCP 9300 listener is admitted only from Anvil, control and Gitea.

Each production host receives one 50 GiB `service-data` volume mounted at `/srv/finals/service-data` with project quotas enabled. Ports 7001 through 7006 have independent hard byte and inode limits; their live, gate and recovery generations share the same project quota. The initializer refuses extra disks, unexpected signatures, filesystems, labels, mounts, mapping conflicts or a mount without active project quotas.

Docker requires the successful production-volume initializer and repeats its verification before every daemon start, so restored containers cannot write to a hidden root-disk directory before the data mount. On a pristine host, `finals-rehearse-production-quota` proves byte and inode `EDQUOT`, atomic-rewrite headroom, sibling isolation and Docker health, then restores the fixed limits. Do not run it after service commissioning. If the rehearsal is forcibly interrupted, rerun `finals-initialize-volume production` before any commissioning step.

The workbench image grants the default `ubuntu` user access to Docker; all other images keep Docker root-only. Runtime secrets and team keys are installed only after instance creation. Go and the C toolchain exist only during the production image build; the sealed package manifest is recorded after both are purged and the build source is removed.
