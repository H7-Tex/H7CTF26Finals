variable "region" {
  type    = string
  default = "ap-hyderabad-1"

  validation {
    condition     = var.region == "ap-hyderabad-1"
    error_message = "The finals live data plane is locked to ap-hyderabad-1."
  }
}

variable "finals_compartment_id" {
  description = "Compartment output from the reviewed oci-foundation stack."
  type        = string
}

variable "availability_domain" {
  description = "Hyderabad availability-domain name verified during preflight."
  type        = string
}

variable "edge_subnet_id" {
  description = "Edge subnet output from the reviewed oci-foundation stack."
  type        = string
}

variable "router_nsg_id" {
  description = "Router NSG output from the reviewed oci-foundation stack."
  type        = string
}

variable "router_image_id" {
  description = "Immutable reviewed router golden-image OCID."
  type        = string
}

variable "ssh_authorized_keys" {
  description = "Organizer public SSH keys."
  type        = string
}

variable "router_cloud_init" {
  description = "Reviewed non-secret router cloud-init with destination-IP-separated nftables policy."
  type        = string
}

variable "active_router" {
  description = "Router that owns both ingress IP pairs."
  type        = string
  default     = "r1"
}
