variable "compartment_id" {
  description = "OCID of the dedicated finals compartment."
  type        = string
}

variable "availability_domain" {
  description = "Availability domain used by the finals fleet."
  type        = string
}

variable "production_subnet_ids" {
  description = "Production subnet OCIDs keyed p01 through p16."
  type        = map(string)
}

variable "workbench_subnet_ids" {
  description = "Workbench subnet OCIDs keyed w01 through w17."
  type        = map(string)
}

variable "game_nsg_id" {
  description = "Network security group for team workloads."
  type        = string
}

variable "production_image_id" {
  description = "Reviewed immutable production image OCID."
  type        = string
}

variable "workbench_image_id" {
  description = "Reviewed immutable workbench image OCID."
  type        = string
}

variable "production_numbers" {
  description = "Production host numbers enabled in this rollout."
  type        = set(number)
  nullable    = false

  validation {
    condition     = alltrue([for number in var.production_numbers : number >= 1 && number <= 16 && number == floor(number)])
    error_message = "production_numbers may contain only integers from 1 through 16."
  }
}

variable "workbench_numbers" {
  description = "Workbench numbers enabled in this rollout."
  type        = set(number)
  nullable    = false

  validation {
    condition     = alltrue([for number in var.workbench_numbers : number >= 1 && number <= 17 && number == floor(number)])
    error_message = "workbench_numbers may contain only integers from 1 through 17."
  }
}

variable "organizer_ssh_authorized_keys" {
  description = "Organizer break-glass SSH public keys installed on production and workbench hosts."
  type        = string
}

variable "team_workbench_ssh_authorized_keys" {
  description = "Team public SSH keys keyed by every enabled workbench."
  type        = map(string)

  validation {
    condition = alltrue([
      for team, keys in var.team_workbench_ssh_authorized_keys :
      can(regex("^team-(0[1-9]|1[0-5])$", team)) && trimspace(keys) != ""
    ])
    error_message = "Workbench SSH keys must be non-empty and keyed team-01 through team-15."
  }
}

variable "production_cloud_init" {
  description = "Non-secret production cloud-init."
  type        = string
  default     = "#cloud-config\n{}\n"
}

variable "workbench_cloud_init" {
  description = "Non-secret workbench cloud-init."
  type        = string
  default     = "#cloud-config\n{}\n"
}
