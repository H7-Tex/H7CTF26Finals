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
  default = "h7-finals"
}

variable "enable_mirror_warmup_egress" {
  description = "Temporary mirror-only NAT egress. Keep false for rehearsal and event."
  type        = bool
  default     = false
}
