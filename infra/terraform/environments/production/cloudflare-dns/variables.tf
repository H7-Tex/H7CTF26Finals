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

variable "repository_ipv4" {
  description = "Fixed private address of the VPN-only finals repository."
  type        = string
  default     = "10.60.201.30"

  validation {
    condition     = var.repository_ipv4 == "10.60.201.30"
    error_message = "repository_ipv4 must remain the fixed private address 10.60.201.30."
  }
}

variable "ttl" {
  description = "DNS TTL during commissioning."
  type        = number
  default     = 60
}
