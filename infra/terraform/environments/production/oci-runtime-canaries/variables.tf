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

variable "service_subnet_id" {
  type = string
}

variable "image_ids" {
  type = map(string)

  validation {
    condition = (
      toset(keys(var.image_ids)) == toset(["platform-x86", "platform-arm", "production", "workbench"]) &&
      alltrue([for image_id in values(var.image_ids) : startswith(image_id, "ocid1.image.oc1.ap-hyderabad-1.")])
    )
    error_message = "image_ids must contain only the four Hyderabad runtime image roles."
  }
}

variable "image_source_revision" {
  type    = string
  default = "c7c6d42de4e11541b733ad0dc0af1d17f3df1868"

  validation {
    condition     = var.image_source_revision == "c7c6d42de4e11541b733ad0dc0af1d17f3df1868"
    error_message = "image_source_revision must be the reviewed v0.0.97 runtime image source."
  }
}

variable "anvil_revision" {
  type    = string
  default = "764d7bc2be5ca8cb6c62edbb357a87d9924c3fb7"

  validation {
    condition     = var.anvil_revision == "764d7bc2be5ca8cb6c62edbb357a87d9924c3fb7"
    error_message = "anvil_revision must be the reviewed Anvil v0.365.0 commit."
  }
}

variable "package_source_revision" {
  type = string

  validation {
    condition     = can(regex("^[0-9a-f]{40}$", var.package_source_revision))
    error_message = "package_source_revision must be a full lowercase Git commit SHA."
  }
}
