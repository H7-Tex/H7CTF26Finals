# OCI ingress addresses

This Resource Manager stack owns the stable `web` and `vpn` public addresses. It reserves them before the gateway fleet exists and later binds them to the floating private ingress addresses without changing the public values.

The web address permits TCP 443. The VPN address permits UDP 443. Gateway failover moves the floating private addresses, so the same two public addresses remain valid for the venue allowlist.
