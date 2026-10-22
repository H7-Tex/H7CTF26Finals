variable "project_id" {
  description = "Locked finals backup project."
  type        = string
  default     = "ctf26-512405"

  validation {
    condition     = var.project_id == "ctf26-512405"
    error_message = "Finals backups must stay in project ctf26-512405."
  }
}

variable "project_number" {
  description = "Locked finals backup project number."
  type        = string
  default     = "1049039378581"

  validation {
    condition     = var.project_number == "1049039378581"
    error_message = "Unexpected GCP project number."
  }
}

variable "location" {
  description = "GCS archive location."
  type        = string
  default     = "asia-south1"
}
