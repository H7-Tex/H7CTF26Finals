variable "compartment_id" {
  description = "OCID of the finals compartment."
  type        = string
}

variable "private_ip_ids" {
  description = "Optional floating private IP assignments keyed by vpn and web."
  type        = map(string)
  default     = {}

  validation {
    condition     = alltrue([for name in keys(var.private_ip_ids) : contains(["vpn", "web"], name)])
    error_message = "private_ip_ids may contain only vpn and web."
  }
}
