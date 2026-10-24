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
    condition     = var.anvil_revision == "764d7bc2be5ca8cb6c62edbb357a87d9924c3fb7"
    error_message = "anvil_revision must be the reviewed Anvil v0.365.0 commit 764d7bc2be5ca8cb6c62edbb357a87d9924c3fb7."
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
    release_sha256 = "c78b158472194e9ba208a94a90a77deba89bbb0b5f75dd22f067477131f0cac8"
    objects = {
      "release.json"                = { sha256 = "c78b158472194e9ba208a94a90a77deba89bbb0b5f75dd22f067477131f0cac8", size = 4721 }
      "archives/player-bundles.tar" = { sha256 = "738e3664efae0df5940c718c9705d62703fb4d2d53f5c10243cb4cad21cfd190", size = 95928320 }
      "archives/factory-images.tar" = { sha256 = "c023e38602499aa3a5ee6b059dec29baa7d8296b888510ed4bd02b6ce4452b49", size = 280236544 }
      "archives/base-images.tar"    = { sha256 = "bf428c66c5fd42272137e7cfa5e1275c4e91c463b0dd8862e059ce23038b8db3", size = 1300224000 }
    }
  }
}
