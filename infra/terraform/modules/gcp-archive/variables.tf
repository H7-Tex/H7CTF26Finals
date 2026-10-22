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

  validation {
    condition     = var.bucket_purposes == toset(["database", "gitea", "pcaps", "scores"])
    error_message = "Finals archives require exactly the database, Gitea, capture and score buckets."
  }
}

variable "retention_seconds" {
  description = "Minimum archive retention before an object can be deleted."
  type        = number
  default     = 2592000

  validation {
    condition     = var.retention_seconds >= 2592000
    error_message = "Finals archives must be retained for at least 30 days."
  }
}

variable "oci_identity_root_ca_pems" {
  description = "Current OCI Hyderabad instance-identity root CA certificates from the authenticated OCI endpoint."
  type        = list(string)

  validation {
    condition = (
      length(var.oci_identity_root_ca_pems) >= 1 &&
      length(var.oci_identity_root_ca_pems) <= 3 &&
      alltrue([for certificate in var.oci_identity_root_ca_pems : length(certificate) <= 32768 && startswith(certificate, "-----BEGIN CERTIFICATE-----") && endswith(trimspace(certificate), "-----END CERTIFICATE-----")])
    )
    error_message = "Provide between one and three PEM-encoded OCI instance-identity root CA certificates."
  }
}

variable "writer_instance_ids" {
  description = "Exact OCI instance OCID authorized to append each archive purpose."
  type        = map(string)

  validation {
    condition = (
      toset(keys(var.writer_instance_ids)) == toset(["database", "gitea", "pcaps", "scores"]) &&
      alltrue([for id in values(var.writer_instance_ids) : can(regex("^ocid1[.]instance[.]oc1[.]ap-hyderabad-1[.][a-z0-9]+$", id))])
    )
    error_message = "writer_instance_ids must map every bucket purpose to an exact Hyderabad OCI instance OCID."
  }
}

variable "verifier_instance_id" {
  description = "Exact operations-host OCI instance OCID authorized to read archives for verification and recovery."
  type        = string

  validation {
    condition     = can(regex("^ocid1[.]instance[.]oc1[.]ap-hyderabad-1[.][a-z0-9]+$", var.verifier_instance_id))
    error_message = "verifier_instance_id must be an exact Hyderabad OCI instance OCID."
  }
}
