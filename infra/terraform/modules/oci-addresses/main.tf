locals {
  addresses = toset(["vpn", "web"])
  tags = {
    event      = "finals-2026"
    managed_by = "terraform"
  }
}

resource "oci_core_public_ip" "ingress" {
  for_each = local.addresses

  compartment_id = var.compartment_id
  display_name   = each.key
  lifetime       = "RESERVED"
  private_ip_id  = lookup(var.private_ip_ids, each.key, null)
  freeform_tags  = merge(local.tags, { ingress = each.key })

  lifecycle {
    prevent_destroy = true
  }
}
