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

variable "platform_image_id" {
  description = "Optional reviewed immutable image OCID used only by the platform host."
  type        = string
  default     = null
}

variable "arm_image_id" {
  description = "Reviewed immutable AArch64 platform image OCID."
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

variable "operations_bastion_source_ip" {
  description = "Private endpoint address of the restricted Operations Bastion."
  type        = string

  validation {
    condition = (
      startswith(var.operations_bastion_source_ip, "10.60.200.") &&
      can(cidrnetmask("${var.operations_bastion_source_ip}/32"))
    )
    error_message = "operations_bastion_source_ip must be an IPv4 address in the services subnet."
  }
}

variable "relay_authorized_keys_readable_roles" {
  description = "Fixed roles whose public forced-command key file uses the sshd-readable 0644 mode."
  type        = set(string)
  default     = ["platform", "control", "repository"]

  validation {
    condition = alltrue([
      for role in var.relay_authorized_keys_readable_roles : contains(["platform", "control", "repository"], role)
    ])
    error_message = "relay_authorized_keys_readable_roles may contain only platform, control and repository."
  }
}
