variable "project_id" {
  description = "GCP project that owns the Terraform state bucket."
  type        = string
  default     = "ctf26-512405"

  validation {
    condition     = var.project_id == "ctf26-512405"
    error_message = "The finals state bucket must stay in project ctf26-512405."
  }
}

variable "bucket_name" {
  description = "Globally unique state bucket name. Use the GCP project number as the suffix."
  type        = string
  default     = "finals-terraform-state-1049039378581"

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]$", var.bucket_name))
    error_message = "bucket_name must be a valid lower-case GCS bucket name."
  }
}

variable "location" {
  description = "GCS location for the state bucket."
  type        = string
  default     = "asia-south1"
}
