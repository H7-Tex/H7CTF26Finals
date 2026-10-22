variable "region" {
  type    = string
  default = "ap-hyderabad-1"

  validation {
    condition     = var.region == "ap-hyderabad-1"
    error_message = "The finals live data plane is locked to ap-hyderabad-1."
  }
}

variable "finals_compartment_id" {
  description = "Compartment output from the reviewed oci-foundation stack."
  type        = string
}

variable "availability_domain" {
  description = "Hyderabad availability-domain name verified during preflight."
  type        = string
}

variable "edge_subnet_id" {
  description = "Edge subnet output from the reviewed oci-foundation stack."
  type        = string
}

variable "router_nsg_id" {
  description = "Router NSG output from the reviewed oci-foundation stack."
  type        = string
}

variable "router_image_id" {
  description = "Immutable reviewed router golden-image OCID."
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

variable "active_router" {
  description = "Router that owns both ingress IP pairs."
  type        = string
  default     = "primary"
}
