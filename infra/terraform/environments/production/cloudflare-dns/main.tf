module "finals_dns" {
  source = "../../../modules/cloudflare-dns"

  zone_id         = var.cloudflare_zone_id
  web_ipv4        = var.web_ipv4
  vpn_ipv4        = var.vpn_ipv4
  repository_ipv4 = var.repository_ipv4
  ttl             = var.ttl
}
