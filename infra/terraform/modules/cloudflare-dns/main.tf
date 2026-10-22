resource "cloudflare_dns_record" "finals" {
  zone_id = var.zone_id
  name    = "finals.h7tex.com"
  type    = "A"
  content = var.web_ipv4
  ttl     = var.ttl
  proxied = false
  comment = "H7CTF'26 Finals web ingress; managed by Terraform"
}

resource "cloudflare_dns_record" "vpn" {
  zone_id = var.zone_id
  name    = "vpn.h7tex.com"
  type    = "A"
  content = var.vpn_ipv4
  ttl     = var.ttl
  proxied = false
  comment = "H7CTF'26 Finals WireGuard ingress; managed by Terraform"
}

resource "cloudflare_dns_record" "repository" {
  zone_id = var.zone_id
  name    = "git.h7tex.com"
  type    = "A"
  content = var.repository_ipv4
  ttl     = var.ttl
  proxied = false
  comment = "H7CTF'26 Finals private repository; managed by Terraform"
}
