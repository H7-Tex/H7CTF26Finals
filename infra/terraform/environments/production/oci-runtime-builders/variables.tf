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

variable "anvil_revision" {
  description = "Exact reviewed Anvil commit embedded and prebuilt in the platform x86 image."
  type        = string

  validation {
    condition     = var.anvil_revision == "6b8a77845a8d72672aaa1b7a76a5d96d7b7332b9"
    error_message = "anvil_revision must be the reviewed Anvil v0.362.0 commit 6b8a77845a8d72672aaa1b7a76a5d96d7b7332b9."
  }
}

variable "source_bundle_expires_at" {
  description = "Reviewed RFC3339 expiry for transient object-read PARs; must be within 24 hours of planning."
  type        = string

  validation {
    condition = (
      can(formatdate("YYYY-MM-DD'T'hh:mm:ssZ", var.source_bundle_expires_at)) &&
      timecmp(var.source_bundle_expires_at, timestamp()) > 0 &&
      timecmp(var.source_bundle_expires_at, timeadd(timestamp(), "24h")) <= 0
    )
    error_message = "source_bundle_expires_at must be a future RFC3339 timestamp no more than 24 hours away."
  }
}
