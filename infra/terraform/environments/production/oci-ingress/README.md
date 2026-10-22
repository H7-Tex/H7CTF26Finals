# OCI ingress stack

This OCI Resource Manager root consumes reviewed `oci-foundation` outputs and creates primary and standby gateways plus floating private ingress addresses. The separate `oci-addresses` stack owns the stable public addresses and binds them after this stack returns the private IP identifiers.

Do not plan or apply it until the immutable router image and cloud-init pass the destination-IP separation tests in `../../../modules/oci-ingress/README.md`. The checked-in example cloud-init is intentionally not deployable.

After creation, the routing stack must point the game routes at the active router's VPN secondary private IP. Mid-event failover moves both secondary private/public pairs together, runs the four positive/negative protocol probes, and then updates `active_router` so the next plan does not move them back.
