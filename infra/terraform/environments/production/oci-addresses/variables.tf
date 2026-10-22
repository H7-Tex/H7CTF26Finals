variable "region" {
  type    = string
  default = "ap-hyderabad-1"

  validation {
    condition     = var.region == "ap-hyderabad-1"
    error_message = "The finals live data plane is locked to ap-hyderabad-1."
  }
}

variable "compartment_id" {
  description = "Compartment output from the foundation stack."
  type        = string
}

variable "private_ip_ids" {
  description = "Optional floating private IP assignments keyed by vpn and web."
  type        = map(string)
  default     = {}
}
