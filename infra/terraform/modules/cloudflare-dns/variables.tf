variable "zone_id" {
  description = "Cloudflare zone ID for h7tex.com."
  type        = string
  sensitive   = true
}

variable "web_ipv4" {
  description = "Reserved OCI web ingress IPv4 address."
  type        = string

  validation {
    condition     = can(cidrnetmask("${var.web_ipv4}/32"))
    error_message = "web_ipv4 must be a valid IPv4 address."
  }
}

variable "vpn_ipv4" {
  description = "Reserved OCI WireGuard ingress IPv4 address."
  type        = string

  validation {
    condition     = can(cidrnetmask("${var.vpn_ipv4}/32"))
    error_message = "vpn_ipv4 must be a valid IPv4 address."
  }
}

variable "ttl" {
  description = "DNS TTL during commissioning."
  type        = number
  default     = 60

  validation {
    condition     = var.ttl >= 60 && var.ttl <= 86400
    error_message = "ttl must be between 60 and 86400 seconds."
  }
}
