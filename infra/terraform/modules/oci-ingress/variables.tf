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

variable "ssh_authorized_keys" {
  description = "Organizer public SSH keys only."
  type        = string
}

variable "cloud_init" {
  description = "Non-secret cloud-init for the router image."
  type        = string

  validation {
    condition = (
      length(regexall("__ROUTER_STATE__", var.cloud_init)) == 2 &&
      length(regexall("event-router-addresses", var.cloud_init)) > 0 &&
      length(regexall("event-router\\.target", var.cloud_init)) > 0
    )
    error_message = "cloud_init must contain two gateway-role placeholders and start the reviewed router runtime."
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
