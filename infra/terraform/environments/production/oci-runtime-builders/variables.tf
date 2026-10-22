variable "region" {
  type    = string
  default = "ap-hyderabad-1"

  validation {
    condition     = var.region == "ap-hyderabad-1"
    error_message = "The finals live data plane is locked to ap-hyderabad-1."
  }
}

variable "compartment_id" {
  type = string
}

variable "availability_domain" {
  type = string
}

variable "vcn_id" {
  type = string
}

variable "edge_subnet_id" {
  type = string
}

variable "x86_base_image_id" {
  description = "Pinned Canonical Ubuntu 24.04 x86_64 image OCID."
  type        = string

  validation {
    condition     = startswith(var.x86_base_image_id, "ocid1.image.oc1.ap-hyderabad-1.")
    error_message = "x86_base_image_id must be an image OCID in ap-hyderabad-1."
  }
}

variable "arm_base_image_id" {
  description = "Pinned Canonical Ubuntu 24.04 AArch64 image OCID."
  type        = string

  validation {
    condition     = startswith(var.arm_base_image_id, "ocid1.image.oc1.ap-hyderabad-1.")
    error_message = "arm_base_image_id must be an image OCID in ap-hyderabad-1."
  }
}

variable "source_revision" {
  type = string

  validation {
    condition     = can(regex("^[0-9a-f]{40}$", var.source_revision))
    error_message = "source_revision must be a full lowercase Git commit SHA."
  }
}
