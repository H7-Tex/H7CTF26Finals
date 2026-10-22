variable "tenancy_ocid" {
  description = "Sahalmn tenancy OCID, pre-populated by OCI Resource Manager."
  type        = string
}

variable "region" {
  description = "Locked OCI live region."
  type        = string
  default     = "ap-hyderabad-1"

  validation {
    condition     = var.region == "ap-hyderabad-1"
    error_message = "The finals live data plane is locked to ap-hyderabad-1."
  }
}

variable "compartment_name" {
  type    = string
  default = "finals"
}

variable "enable_mirror_warmup_egress" {
  description = "Temporary mirror-only NAT egress. Keep false for rehearsal and event."
  type        = bool
  default     = false
}

variable "enable_service_warmup_egress" {
  description = "Temporary shared-service NAT egress for operations commissioning. Keep false for rehearsal and event."
  type        = bool
  default     = false
}

variable "routing_private_ip_id" {
  description = "Floating gateway private-IP OCID from the applied ingress stack."
  type        = string
  default     = null

  validation {
    condition     = var.routing_private_ip_id == null || startswith(var.routing_private_ip_id, "ocid1.privateip.oc1.ap-hyderabad-1.")
    error_message = "routing_private_ip_id must be null or a private-IP OCID in ap-hyderabad-1."
  }
}
