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
  description = "Workbench subnet OCIDs keyed w01 through w15."
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

variable "organizer_ssh_authorized_keys" {
  description = "Organizer break-glass SSH public keys installed on production and workbench hosts."
  type        = string
}

variable "team_workbench_ssh_authorized_keys" {
  description = "Team public SSH keys keyed team-01 through team-15."
  type        = map(string)

  validation {
    condition = alltrue([
      for team in range(1, 16) :
      contains(keys(var.team_workbench_ssh_authorized_keys), format("team-%02d", team))
    ])
    error_message = "A workbench SSH public-key set is required for every competing team."
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
