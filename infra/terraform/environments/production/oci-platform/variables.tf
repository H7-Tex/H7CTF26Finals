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

variable "organizer_ssh_authorized_keys" {
  description = "Reviewed organizer break-glass SSH public key lines."
  type        = string

  validation {
    condition     = trimspace(var.organizer_ssh_authorized_keys) != ""
    error_message = "organizer_ssh_authorized_keys must contain at least one reviewed public key."
  }
}

variable "operations_relay_ssh_public_key" {
  description = "Raw event-only operations-relay Ed25519 public key without options or a comment."
  type        = string

  validation {
    condition     = can(regex("^ssh-ed25519 [A-Za-z0-9+/]{68}$", var.operations_relay_ssh_public_key))
    error_message = "operations_relay_ssh_public_key must be one raw Ed25519 public key without options or a comment."
  }
}
