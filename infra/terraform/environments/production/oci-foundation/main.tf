resource "oci_identity_compartment" "finals" {
  compartment_id = var.tenancy_ocid
  name           = var.compartment_name
  description    = "Dedicated H7CTF'26 Finals infrastructure"
  enable_delete  = false

  freeform_tags = {
    event      = "h7ctf26-finals"
    managed_by = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}

module "network" {
  source = "../../../modules/oci-network"

  compartment_id = oci_identity_compartment.finals.id
  team_count     = 15
  vcn_cidr       = "10.60.0.0/15"

  enable_mirror_warmup_egress = var.enable_mirror_warmup_egress
}
