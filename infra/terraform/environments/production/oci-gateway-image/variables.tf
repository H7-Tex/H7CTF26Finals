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

variable "builder_instance_id" {
  description = "Stopped gateway image builder instance OCID."
  type        = string

  validation {
    condition = (
      startswith(var.builder_instance_id, "ocid1.instance.oc1.ap-hyderabad-1.") &&
      var.builder_instance_id != "ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goaceebogxa47rg74d6izhqorb2dgnjjlfsv7gupjwbevyva" &&
      var.builder_instance_id != "ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goacvwoxwqstnmj6bwirfuxxan45gpqbbuzt7fw5if2zjfbq" &&
      var.builder_instance_id != "ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goacptf4hmhhjlqee2ucownqcd6amop4lye7j3m3z27z2uqq"
    )
    error_message = "builder_instance_id must be an approved instance OCID in ap-hyderabad-1."
  }
}

variable "source_revision" {
  description = "Full reviewed Git commit installed on the builder."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-f]{40}$", var.source_revision))
    error_message = "source_revision must be a full lowercase Git commit SHA."
  }
}
