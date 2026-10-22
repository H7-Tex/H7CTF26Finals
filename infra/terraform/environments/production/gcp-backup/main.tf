module "archive" {
  source = "../../../modules/gcp-archive"

  project_id     = var.project_id
  project_number = var.project_number
  location       = var.location

  oci_identity_root_ca_pems = var.oci_identity_root_ca_pems
  verifier_instance_id      = var.verifier_instance_id
  writer_instance_ids       = var.writer_instance_ids
}
