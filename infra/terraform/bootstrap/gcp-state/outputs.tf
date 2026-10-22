output "bucket_name" {
  description = "Bucket name to use in GCS backend configuration."
  value       = google_storage_bucket.terraform_state.name
}

output "bucket_url" {
  description = "Canonical GCS URL for the state bucket."
  value       = google_storage_bucket.terraform_state.url
}
