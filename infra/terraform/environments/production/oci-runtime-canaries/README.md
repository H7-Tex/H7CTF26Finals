# OCI runtime image canaries

This isolated stack boots the four reviewed runtime images once before any production rotation. The instances have no public IP, no ingress, no SSH keys and no data volumes. Their dedicated NSG permits only TCP 443 to the Hyderabad Oracle Services Network so OCI Run Command can acknowledge commands; the service subnet has no internet route.

Each canary verifies the root-owned runtime manifest, exact image and Anvil revisions, package-manifest hash and role-specific default-off state. The x86 platform canary also proves Anvil migration 067 is present. Safe platform role activation is exercised without secrets; production must reject its uncommissioned preflight, while workbench proves its local toolchain and Docker runtime. Every result is written to the serial console and the guest powers off within ten minutes.

Apply only a separately reviewed four-instance, one-NSG, one-egress-rule plan. After all four serial logs contain `phase=complete status=passed` and guest poweroff evidence, reconcile OCI state to `STOPPED` only with explicit approval, then destroy this entire disposable stack through another reviewed plan. Never feed these instance IDs to platform or fleet stacks.
