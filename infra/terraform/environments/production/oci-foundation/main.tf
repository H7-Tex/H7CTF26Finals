resource "oci_identity_compartment" "finals" {
  compartment_id = var.tenancy_ocid
  name           = var.compartment_name
  description    = "Dedicated H7CTF'26 Finals infrastructure"
  enable_delete  = false

  freeform_tags = {
    event      = "finals-2026"
    managed_by = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}

locals {
  budget_alert_thresholds = {
    advisory = 175
    warning  = 250
    critical = 300
    ceiling  = 315
  }
}

resource "oci_budget_budget" "finals" {
  compartment_id = var.tenancy_ocid
  amount         = 325
  reset_period   = "MONTHLY"
  display_name   = "finals-2026"
  description    = "H7CTF'26 Finals compartment budget"
  target_type    = "COMPARTMENT"
  targets        = [oci_identity_compartment.finals.id]

  freeform_tags = {
    event      = "finals-2026"
    managed_by = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "oci_budget_alert_rule" "actual" {
  for_each = local.budget_alert_thresholds

  budget_id      = oci_budget_budget.finals.id
  display_name   = "finals-${each.key}"
  description    = "Actual finals spend reached SGD ${each.value}"
  message        = "H7CTF'26 Finals actual spend reached SGD ${each.value}."
  recipients     = var.budget_alert_recipients
  threshold      = each.value
  threshold_type = "ABSOLUTE"
  type           = "ACTUAL"

  freeform_tags = {
    event      = "finals-2026"
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
  vcn_cidrs      = ["10.60.0.0/16", "10.61.0.0/16"]

  enable_mirror_warmup_egress  = var.enable_mirror_warmup_egress
  enable_service_warmup_egress = var.enable_service_warmup_egress
  routing_private_ip_id        = var.routing_private_ip_id
}
