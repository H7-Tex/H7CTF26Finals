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

variable "builder_instance_ids" {
  type = map(string)

  validation {
    condition = alltrue([
      for role in ["platform-x86", "platform-arm", "production", "workbench"] :
      startswith(lookup(var.builder_instance_ids, role, ""), "ocid1.instance.oc1.ap-hyderabad-1.") &&
      !contains([
        "ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goacy3dojy463ubuy7ibn5w5qkl2wuaoclhof7q2k54wof2q",
        "ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goaccomxx6u2gtj4l75e7rmruf3ygrvp2sqy7e3m3ta6x3ia",
        "ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goacrkckfhkxhedqym7qggptmctcbcg5wrijqg7xhn6v7drq",
        "ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goacmb2j6gjpf63gphl7xhdc4izh4uakh6nlm5uw2pbwaguq",
      ], lookup(var.builder_instance_ids, role, ""))
    ])
    error_message = "builder_instance_ids must contain Hyderabad instance OCIDs for all four roles."
  }
}

variable "source_revision" {
  type = string

  validation {
    condition     = can(regex("^[0-9a-f]{40}$", var.source_revision))
    error_message = "source_revision must be a full lowercase Git commit SHA."
  }
}
