variable "compartment_id" {
  description = "OCID of the dedicated h7-finals compartment."
  type        = string
}

variable "team_count" {
  description = "Number of competing teams. One extra production subnet is created for NOP."
  type        = number
  default     = 15

  validation {
    condition     = var.team_count == 15
    error_message = "The H7CTF'26 Finals topology is locked to 15 competing teams."
  }
}

variable "vcn_cidr" {
  description = "Finals VCN CIDR."
  type        = string
  default     = "10.60.0.0/15"

  validation {
    condition     = var.vcn_cidr == "10.60.0.0/15"
    error_message = "The finals routing and checker contract requires 10.60.0.0/15."
  }
}

variable "enable_mirror_warmup_egress" {
  description = "Temporarily give only the mirror subnet a NAT default route while caches are populated. Must be false for rehearsal and event."
  type        = bool
  default     = false
}

variable "enable_service_warmup_egress" {
  description = "Temporarily give the shared service subnet a NAT default route while hosts are commissioned. Must be false for rehearsal and event."
  type        = bool
  default     = false
}
