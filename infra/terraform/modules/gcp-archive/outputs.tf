output "buckets" {
  description = "Private archive bucket names keyed by purpose."
  value       = { for purpose, bucket in google_storage_bucket.archive : purpose => bucket.name }
}
