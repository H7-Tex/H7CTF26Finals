module "platform" {
  source = "../../../modules/oci-platform"

  compartment_id                  = var.finals_compartment_id
  availability_domain             = var.availability_domain
  subnet_ids                      = var.subnet_ids
  infra_nsg_id                    = var.infra_nsg_id
  x86_image_id                    = var.x86_image_id
  platform_image_id               = var.platform_image_id
  arm_image_id                    = var.arm_image_id
  organizer_ssh_authorized_keys   = var.organizer_ssh_authorized_keys
  operations_relay_ssh_public_key = var.operations_relay_ssh_public_key
  operations_bastion_source_ip    = oci_bastion_bastion.operations.private_endpoint_ip_address
  # Deferred until each affected immutable host receives a reviewed replacement plan.
  relay_authorized_keys_readable_roles = ["platform", "control"]
}

module "storage" {
  source = "../../../modules/oci-storage"

  compartment_id      = var.finals_compartment_id
  availability_domain = var.availability_domain
  instance_ids = merge(module.platform.instance_ids, {
    gateway-primary = var.gateway_primary_instance_id
  })
}

resource "oci_bastion_bastion" "operations" {
  bastion_type                 = "standard"
  client_cidr_block_allow_list = ["27.61.61.38/32", "27.61.63.104/32", "27.61.60.100/32", "144.24.149.51/32"]
  compartment_id               = var.finals_compartment_id
  dns_proxy_status             = "DISABLED"
  max_session_ttl_in_seconds   = 10800
  name                         = "operations"
  target_subnet_id             = var.subnet_ids["services"]

  freeform_tags = {
    event      = "finals-2026"
    managed_by = "terraform"
  }

  lifecycle {
    ignore_changes = [bastion_type]
  }
}
