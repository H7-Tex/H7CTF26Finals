# Cloudflare DNS

This root manages the two public ingress records and the private repository name. `git.h7tex.com` is deliberately a DNS-only A record for `10.60.201.30`; it is reachable only over the finals VPN or routed private networks and creates no public endpoint or SRM whitelist item.

The organizer may create the repository record manually before this stack is applied. Import that existing record before planning so Terraform never attempts a duplicate:

```bash
terraform init -backend-config=backend.hcl
terraform import 'module.finals_dns.cloudflare_dns_record.repository' '<h7tex-zone-id>/<git-record-id>'
terraform plan -out=reviewed.tfplan
```

Read the record ID from the Cloudflare dashboard or API. The first reviewed plan after import must show `git.h7tex.com` as DNS-only with content `10.60.201.30`, and no replacement of the unchanged `finals.h7tex.com` or `vpn.h7tex.com` records.
