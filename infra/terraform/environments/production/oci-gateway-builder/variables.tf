variable "region" {
  type    = string
  default = "ap-hyderabad-1"

  validation {
    condition     = var.region == "ap-hyderabad-1"
    error_message = "The finals live data plane is locked to ap-hyderabad-1."
  }
}
variable "compartment_id" {
  description = "OCID of the finals compartment."
  type        = string
}

variable "availability_domain" {
  description = "Hyderabad availability-domain name."
  type        = string
}

variable "vcn_id" {
  description = "VCN output from the foundation stack."
  type        = string
}

variable "edge_subnet_id" {
  description = "Public edge subnet output from the foundation stack."
  type        = string
}

variable "base_image_id" {
  description = "Pinned Canonical Ubuntu 24.04 platform-image OCID."
  type        = string

  validation {
    condition     = startswith(var.base_image_id, "ocid1.image.oc1.ap-hyderabad-1.")
    error_message = "base_image_id must be an image OCID in ap-hyderabad-1."
  }
}

variable "source_revision" {
  description = "Full reviewed Git commit used to build the image."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-f]{40}$", var.source_revision))
    error_message = "source_revision must be a full lowercase Git commit SHA."
  }
}

variable "source_bundle_expires_at" {
  description = "Reviewed RFC3339 expiry for the transient object-read PAR; must be within 24 hours of planning."
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
