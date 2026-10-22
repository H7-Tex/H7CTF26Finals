variable "compartment_id" {
  description = "OCID of the dedicated finals compartment."
  type        = string
}

variable "availability_domain" {
  description = "Availability domain used by the finals fleet."
  type        = string
}

variable "subnet_ids" {
  description = "Shared subnet OCIDs keyed by services, core, mirror and hills."
  type        = map(string)

  validation {
    condition     = alltrue([for key in ["services", "core", "mirror", "hills"] : contains(keys(var.subnet_ids), key)])
    error_message = "subnet_ids must contain services, core, mirror and hills."
  }
}

variable "infra_nsg_id" {
  description = "Network security group for shared platform hosts."
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

variable "ssh_authorized_keys" {
  description = "Organizer break-glass SSH public keys."
  type        = string
}

variable "cloud_init_by_role" {
  description = "Optional non-secret cloud-init keyed by platform role."
  type        = map(string)
  default     = {}
}
