output "records" {
  description = "Published DNS names and their reserved OCI addresses."
  value = {
    "finals.h7tex.com" = var.web_ipv4
    "git.h7tex.com"    = var.repository_ipv4
    "vpn.h7tex.com"    = var.vpn_ipv4
  }
}
