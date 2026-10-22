module "archive" {
  source = "../../../modules/gcp-archive"

  project_id     = var.project_id
  project_number = var.project_number
  location       = var.location
}
