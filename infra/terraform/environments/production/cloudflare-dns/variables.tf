variable "cloudflare_zone_id" {
  description = "Cloudflare zone ID for h7tex.com."
  type        = string
  sensitive   = true
}

variable "web_ipv4" {
  description = "Reserved OCI web ingress IPv4 address."
  type        = string
}

variable "vpn_ipv4" {
  description = "Reserved OCI WireGuard ingress IPv4 address."
  type        = string
}

variable "ttl" {
  description = "DNS TTL during commissioning."
  type        = number
  default     = 60
}
