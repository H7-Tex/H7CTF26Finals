variable "region" {
  description = "Locked OCI live region."
  type        = string
  default     = "ap-hyderabad-1"

  validation {
    condition     = var.region == "ap-hyderabad-1"
    error_message = "The finals live data plane is locked to ap-hyderabad-1."
  }
}

variable "finals_compartment_id" {
  description = "Finals compartment OCID from the foundation stack."
  type        = string
}

variable "availability_domain" {
  description = "Availability domain used by the finals fleet."
  type        = string
}

variable "subnet_ids" {
  description = "Shared subnet OCIDs from the foundation stack."
  type        = map(string)
}

variable "infra_nsg_id" {
  description = "Shared platform NSG OCID from the foundation stack."
  type        = string
}

variable "x86_image_id" {
  description = "Reviewed immutable x86_64 platform image OCID."
  type        = string
}

variable "arm_image_id" {
  description = "Reviewed immutable AArch64 platform image OCID."
  type        = string
}

variable "gateway_primary_instance_id" {
  description = "Primary gateway instance OCID from the ingress stack."
  type        = string
}

variable "ssh_authorized_keys" {
  description = "Organizer break-glass SSH public keys."
  type        = string
}

variable "cloud_init_by_role" {
  description = "Optional non-secret cloud-init keyed by platform role."
  type        = map(string)
  default     = {}
}
