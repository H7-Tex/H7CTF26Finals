module "platform" {
  source = "../../../modules/oci-platform"

  compartment_id      = var.finals_compartment_id
  availability_domain = var.availability_domain
  subnet_ids          = var.subnet_ids
  infra_nsg_id        = var.infra_nsg_id
  x86_image_id        = var.x86_image_id
  arm_image_id        = var.arm_image_id
  ssh_authorized_keys = var.ssh_authorized_keys
  cloud_init_by_role  = var.cloud_init_by_role
}

module "storage" {
  source = "../../../modules/oci-storage"

  compartment_id      = var.finals_compartment_id
  availability_domain = var.availability_domain
  instance_ids = merge(module.platform.instance_ids, {
    gateway-primary = var.gateway_primary_instance_id
  })
}
