module "ingress" {
  source = "../../../modules/oci-ingress"

  compartment_id      = var.finals_compartment_id
  availability_domain = var.availability_domain
  edge_subnet_id      = var.edge_subnet_id
  router_nsg_id       = var.router_nsg_id
  router_image_id     = var.router_image_id
  ssh_authorized_keys = var.ssh_authorized_keys
  cloud_init          = var.router_cloud_init
  active_router       = var.active_router
}
