# OCI ingress contract

This module assigns two floating private ingress addresses to one active gateway VNIC:

- `10.60.250.100`: UDP 443 only for WireGuard;
- `10.60.250.101`: TCP 443 only for TLS pass-through to Anvil.

It also assigns `10.60.250.121-135` as private-only team attack-egress identities on the active VNIC. The independent `oci-addresses` stack remains the sole owner of the two reserved public IPs.

The OCI NSG is attached to the VNIC rather than an individual secondary IP, so it necessarily admits both UDP 443 and TCP 443 to that VNIC. The reviewed router image and its nftables acceptance test must enforce destination-IP separation before this module can be applied:

```nft
ip daddr 10.60.250.100 udp dport 443 accept
ip daddr 10.60.250.101 tcp dport 443 accept
ip daddr { 10.60.250.100, 10.60.250.101 } meta l4proto { tcp, udp } th dport 443 drop
```

The complete router ruleset must place those decisions ahead of generic input acceptance, then expose only the WireGuard listener on `.100` and the web proxy on `.101`. The checked-in cloud-init renders only the active or standby role; all host policy lives in the immutable image. The failover runbook moves both ingress private addresses and the 15 team identities, confirms all four positive/negative protocol tests and then changes `active_router` to reconcile Terraform.

There is no TCP VPN fallback in this module.
