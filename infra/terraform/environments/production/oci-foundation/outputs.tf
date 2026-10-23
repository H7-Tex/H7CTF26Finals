output "finals_compartment_id" {
  value = oci_identity_compartment.finals.id
}

output "run_command_dynamic_group_id" {
  value = oci_identity_dynamic_group.finals_run_command.id
}

output "run_command_policy_id" {
  value = oci_identity_policy.finals_run_command.id
}

output "vcn_id" {
  value = module.network.vcn_id
}

output "service_gateway_id" {
  value = module.network.service_gateway_id
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
