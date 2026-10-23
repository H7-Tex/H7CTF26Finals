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
  # Deferred until each affected immutable host receives a reviewed replacement plan.
  relay_authorized_keys_readable_roles = []
}

module "storage" {
  source = "../../../modules/oci-storage"

  compartment_id      = var.finals_compartment_id
  availability_domain = var.availability_domain
  instance_ids = merge(module.platform.instance_ids, {
    gateway-primary = var.gateway_primary_instance_id
  })
}
