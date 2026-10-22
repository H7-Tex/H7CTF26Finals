variable "compartment_id" {
  type = string
}

variable "availability_domain" {
  type = string
}

variable "edge_subnet_id" {
  type = string
}

variable "router_nsg_id" {
  type = string
}

variable "router_image_id" {
  description = "Immutable reviewed router image OCID."
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

variable "cloud_init" {
  description = "Non-secret cloud-init for the router image."
  type        = string

  validation {
    condition = (
      length(regexall("__ROUTER_STATE__", var.cloud_init)) == 2 &&
      length(regexall("ssh_deletekeys: true", var.cloud_init)) == 1 &&
      length(regexall("finals-host-recipient", var.cloud_init)) == 1 &&
      length(regexall("event-router-initialize", var.cloud_init)) == 1
    )
    error_message = "cloud_init must contain two gateway-role placeholders, regenerate the host key and invoke the reviewed router initializer."
  }
}

variable "active_router" {
  description = "Router that owns both stable ingress private/public IP pairs."
  type        = string
  default     = "primary"

  validation {
    condition     = contains(["primary", "standby"], var.active_router)
    error_message = "active_router must be primary or standby."
  }
}
