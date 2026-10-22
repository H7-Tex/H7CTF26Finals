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
        "ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goacz5owemazyq72tfqdriutkqsv4k4arluim2mt223sknfq",
        "ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goacdkqloulenb33an5dw6aj4fro4wbt7dplrt22v43vpyqa",
        "ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goacf74slght5m37vsh54tdyyfhm2ukebicmx5du2deywo3a",
        "ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goacoy7zvi6n667lc5cru636x3syhzpzuwmrhnlklybla5qa",
        "ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goac3z62q66d7h5qkfxwvnekd6x3scgdaldfyqpbeoklsuaa",
        "ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goaclkmig5434ou6hkigzf4qx5d3uvbofeiejfoy7fwljc2a",
        "ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goacubaccuijeotibtjqw7zt325dhg4fdw756gntikdnwgoa",
        "ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goacw7aqccrl4vifdxeiyukg3lygu6hnwyqhlrhxtjwwwagq",
        "ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goacnky6ssv72tuk54mqass4t3kgyhndftdtaini763mxyta",
        "ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goacrwug6qmay35zn7mqyuwhfmy54dgca6qi3jrutln3r2mq",
        "ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goacbli3sydukpwff2g4slterojvims7wahp26apvhrgqgua",
        "ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goacs5d3744oky4vjh22dpm2ysykrlqhypk4jffg3mi5kemq",
        "ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goacdfs27zsszpx7suhnmcuwpwlpbdjalhwzwmkah42ol4uq",
        "ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goacpjlgntnqxekvsvfo34az2hfw7zvdmlndi4h6fvx765ua",
        "ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goac4mtijxgx5sjhzrhr6pa7xyx3nveaywaiwzc6lc4z2m6q",
        "ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goacpodd3zw4nrujfrozyc27phqo7xwy2k67ryfa2f4qpszq",
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
