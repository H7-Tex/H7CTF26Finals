output "finals_compartment_id" {
  value = oci_identity_compartment.finals.id
}

output "vcn_id" {
  value = module.network.vcn_id
}

output "subnet_ids" {
  value = module.network.subnet_ids
}

output "route_table_ids" {
  value = module.network.route_table_ids
}

output "network_security_group_ids" {
  value = module.network.network_security_group_ids
}
