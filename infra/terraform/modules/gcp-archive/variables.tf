variable "project_id" {
  description = "GCP backup project ID."
  type        = string
}

variable "project_number" {
  description = "GCP project number used to make bucket names globally unique."
  type        = string
}

variable "location" {
  description = "GCS archive location."
  type        = string
}

variable "bucket_purposes" {
  description = "Independent archive buckets to provision."
  type        = set(string)
  default     = ["database", "gitea", "pcaps", "scores"]
}
