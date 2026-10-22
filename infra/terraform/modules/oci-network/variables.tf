variable "compartment_id" {
  description = "OCID of the dedicated finals compartment."
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

variable "vcn_cidrs" {
  description = "Finals VCN IPv4 blocks."
  type        = list(string)
  default     = ["10.60.0.0/16", "10.61.0.0/16"]

  validation {
    condition     = var.vcn_cidrs == tolist(["10.60.0.0/16", "10.61.0.0/16"])
    error_message = "The finals routing and checker contract requires the 10.60.0.0/16 and 10.61.0.0/16 VCN blocks."
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

variable "routing_private_ip_id" {
  description = "Optional floating gateway private-IP OCID used for intra-VCN routing."
  type        = string
  default     = null

  validation {
    condition     = var.routing_private_ip_id == null ? true : startswith(var.routing_private_ip_id, "ocid1.privateip.oc1.ap-hyderabad-1.")
    error_message = "routing_private_ip_id must be null or a private-IP OCID in ap-hyderabad-1."
  }
}
