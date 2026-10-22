variable "compartment_id" {
  description = "OCID of the dedicated finals compartment."
  type        = string
}

variable "availability_domain" {
  description = "Availability domain used by the finals fleet."
  type        = string
}

variable "instance_ids" {
  description = "Instance OCIDs keyed by platform, repository, mirror and gateway-primary."
  type        = map(string)

  validation {
    condition     = alltrue([for key in ["platform", "repository", "mirror", "gateway-primary"] : contains(keys(var.instance_ids), key)])
    error_message = "instance_ids must contain platform, repository, mirror and gateway-primary."
  }
}
