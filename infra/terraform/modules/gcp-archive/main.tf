resource "google_project_service" "archive" {
  for_each = toset([
    "cloudresourcemanager.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
  ])

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

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

  retention_policy {
    retention_period = var.retention_seconds
    is_locked        = false
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

resource "google_iam_workload_identity_pool" "archive" {
  project                   = var.project_id
  workload_identity_pool_id = "finals-archive"
  display_name              = "Finals archive"
  description               = "OCI instance identities for append-only finals archives"

  depends_on = [google_project_service.archive]
}

resource "google_iam_workload_identity_pool_provider" "oci_instance" {
  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.archive.workload_identity_pool_id
  workload_identity_pool_provider_id = "oci-instance"
  display_name                       = "OCI instance"
  description                        = "Hyderabad OCI instance identity certificates"
  attribute_mapping = {
    "google.subject" = "assertion.subject.dn.cn"
  }
  attribute_condition = join(" || ", [
    for id in distinct(concat(values(var.writer_instance_ids), [var.verifier_instance_id])) :
    "assertion.subject.dn.cn == '${id}'"
  ])

  x509 {
    trust_store {
      dynamic "trust_anchors" {
        for_each = toset(var.oci_identity_root_ca_pems)
        content {
          pem_certificate = trust_anchors.value
        }
      }
    }
  }
}

locals {
  archive_principal_prefix = "principal://iam.googleapis.com/projects/${var.project_number}/locations/global/workloadIdentityPools/${google_iam_workload_identity_pool.archive.workload_identity_pool_id}/subject/"
}

resource "google_storage_bucket_iam_member" "writer_create" {
  for_each = google_storage_bucket.archive

  bucket = each.value.name
  role   = "roles/storage.objectCreator"
  member = "${local.archive_principal_prefix}${var.writer_instance_ids[each.key]}"
}

resource "google_storage_bucket_iam_member" "writer_verify" {
  for_each = google_storage_bucket.archive

  bucket = each.value.name
  role   = "roles/storage.objectViewer"
  member = "${local.archive_principal_prefix}${var.writer_instance_ids[each.key]}"
}

resource "google_storage_bucket_iam_member" "operations_recovery" {
  for_each = google_storage_bucket.archive

  bucket = each.value.name
  role   = "roles/storage.objectViewer"
  member = "${local.archive_principal_prefix}${var.verifier_instance_id}"
}
