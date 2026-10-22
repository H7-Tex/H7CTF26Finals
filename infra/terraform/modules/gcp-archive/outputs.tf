output "buckets" {
  description = "Private archive bucket names keyed by purpose."
  value       = { for purpose, bucket in google_storage_bucket.archive : purpose => bucket.name }
}

output "workload_identity_provider" {
  description = "X.509 workload identity provider used by OCI archive writers."
  value       = google_iam_workload_identity_pool_provider.oci_instance.name
}
