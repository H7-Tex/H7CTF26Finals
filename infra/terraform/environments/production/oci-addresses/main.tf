module "addresses" {
  source = "../../../modules/oci-addresses"

  compartment_id = var.compartment_id
  private_ip_ids = var.private_ip_ids
}
