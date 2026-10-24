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
    condition     = var.anvil_revision == "21d50f53afd60eef2aa9dd466f52fa6ec83dabdd"
    error_message = "anvil_revision must be the reviewed Anvil v0.365.1 commit 21d50f53afd60eef2aa9dd466f52fa6ec83dabdd."
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

variable "model_a_release_url" {
  description = "Read PAR base URL (ending /o/) for the private Model A release bucket. Sensitive; production builders only."
  type        = string
  sensitive   = true
  default     = ""
  validation {
    condition     = var.model_a_release_url == "" || can(regex("^https://objectstorage\\.ap-hyderabad-1\\.oraclecloud\\.com/p/[A-Za-z0-9_.+=%-]+/n/[a-z0-9]+/b/[A-Za-z0-9_.-]+/o/$", var.model_a_release_url))
    error_message = "model_a_release_url must be a Hyderabad object storage PAR ending in /o/."
  }
}

variable "model_a_release" {
  description = "Exact Model A release pinned by Codex-2's release.json (challenge c045db0)."
  type = object({
    release_sha256 = string
    objects        = map(object({ sha256 = string, size = number }))
  })
  default = {
    release_sha256 = "d1d427d928b1aa96394a201af048ec5f3c1eb67471b36bae65c9887c95b9a7e4"
    objects = {
      "release.json"                = { sha256 = "d1d427d928b1aa96394a201af048ec5f3c1eb67471b36bae65c9887c95b9a7e4", size = 4721 }
      "archives/player-bundles.tar" = { sha256 = "ac00de1ff5ba52aa76fa1ba9b0aba794b4fed3a3b1960b4f9fe1e84361efaa43", size = 95928320 }
      "archives/factory-images.tar" = { sha256 = "9fb2bc8aec17c12bd2e425030d495459ad80228a909ba52b14a061312816d8b7", size = 280207360 }
      "archives/base-images.tar"    = { sha256 = "ee06b3b975ae5fac7e7600e3c0214eab7099029106289705c9fbe1d12b70c348", size = 1300224000 }
    }
  }
}
