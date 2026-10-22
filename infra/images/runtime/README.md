# Runtime images

This build produces four immutable Ubuntu 24.04 images: x86 and Arm platform bases, a minimal x86 production base, and an x86 workbench base with offline build tools. Every image includes Docker Compose, bounded container logs, key-only SSH, time synchronization, audit logging and the same reviewed host baseline.

Builders accept no ingress or SSH key. Cloud-init installs and tests the role, records the reviewed source revision, removes package/build state, resets machine identity and powers off. Capture only a stopped revision-tagged builder through the separate `oci-runtime-images` stack.

The production image deliberately contains no challenge, flag, repository credential or deployment key. The workbench image grants the default `ubuntu` user access to Docker; all other images keep Docker root-only. Runtime secrets and team keys are installed only after instance creation.
