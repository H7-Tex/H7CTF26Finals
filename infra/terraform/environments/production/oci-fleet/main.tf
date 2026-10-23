module "fleet" {
  source = "../../../modules/oci-compute-fleet"

  compartment_id                     = var.finals_compartment_id
  availability_domain                = var.availability_domain
  production_subnet_ids              = var.production_subnet_ids
  workbench_subnet_ids               = var.workbench_subnet_ids
  game_nsg_id                        = var.game_nsg_id
  production_image_id                = var.production_image_id
  reference_production_image_id      = var.reference_production_image_id
  workbench_image_id                 = var.workbench_image_id
  production_numbers                 = var.production_numbers
  workbench_numbers                  = var.workbench_numbers
  organizer_ssh_authorized_keys      = var.organizer_ssh_authorized_keys
  team_workbench_ssh_authorized_keys = var.team_workbench_ssh_authorized_keys
  production_cloud_init              = var.production_cloud_init
  workbench_cloud_init               = var.workbench_cloud_init
}
