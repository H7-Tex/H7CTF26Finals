resource "google_storage_bucket" "archive" {
  for_each = var.bucket_purposes

  name                        = "finals-${each.key}-${var.project_number}"
  project                     = var.project_id
  location                    = var.location
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  versioning {
    enabled = true
  }

  labels = {
    event      = "finals-2026"
    managed_by = "terraform"
    purpose    = each.key
  }

  lifecycle {
    prevent_destroy = true
  }
}
