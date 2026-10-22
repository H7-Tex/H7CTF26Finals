module "ingress" {
  source = "../../../modules/oci-ingress"

  compartment_id                  = var.finals_compartment_id
  availability_domain             = var.availability_domain
  edge_subnet_id                  = var.edge_subnet_id
  router_nsg_id                   = var.router_nsg_id
  router_image_id                 = var.router_image_id
  organizer_ssh_authorized_keys   = var.organizer_ssh_authorized_keys
  operations_relay_ssh_public_key = var.operations_relay_ssh_public_key
  cloud_init                      = file("${path.module}/../../../../images/router/cloud-init.yaml")
  active_router                   = var.active_router
}
