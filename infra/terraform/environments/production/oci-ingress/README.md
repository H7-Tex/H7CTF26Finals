# OCI ingress stack

This OCI Resource Manager root consumes reviewed `oci-foundation` outputs and creates primary and standby gateways, floating private ingress addresses and 15 private team egress identities. The separate `oci-addresses` stack owns only the stable public addresses and binds them after this stack returns the ingress private IP identifiers.

Do not plan or apply it until the immutable router image and checked-in cloud-init pass the destination-IP separation tests in `../../../modules/oci-ingress/README.md`.

After creation, the routing stack must point the game routes at the active gateway's VPN secondary private IP. Mid-event failover moves both ingress private addresses and the 15 team identities together, runs the four positive/negative protocol probes, and then updates `active_router` so the next plan does not move them back.

Feed `routing_private_ip_id` into the foundation stack only after this stack is applied. Review that separate plan before adding the service, mirror and isolated intra-VCN routes.
