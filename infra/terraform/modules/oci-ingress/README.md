# OCI ingress contract

This module reserves two stable public/private address pairs on one active router VNIC:

- `10.60.250.100` / `vpn_public_ip`: UDP 443 only for WireGuard;
- `10.60.250.101` / `web_public_ip`: TCP 443 only for TLS pass-through to Anvil.

The OCI NSG is attached to the VNIC rather than an individual secondary IP, so it necessarily admits both UDP 443 and TCP 443 to that VNIC. The reviewed router image and its nftables acceptance test must enforce destination-IP separation before this module can be applied:

```nft
ip daddr 10.60.250.100 udp dport 443 accept
ip daddr 10.60.250.101 tcp dport 443 accept
ip daddr { 10.60.250.100, 10.60.250.101 } meta l4proto { tcp, udp } th dport 443 drop
```

The complete router ruleset must place those decisions ahead of generic input acceptance, then expose only the WireGuard listener on `.100` and the web proxy on `.101`. The failover runbook moves both secondary private IPs and confirms all four positive/negative protocol tests before changing `active_router` to reconcile Terraform.

There is no TCP VPN fallback in this module.
