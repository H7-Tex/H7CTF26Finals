output "instance_ids" {
  value = module.platform.instance_ids
}

output "private_ips" {
  value = module.platform.private_ips
}

output "volume_ids" {
  value = module.storage.volume_ids
}

output "database_backup_policy_id" {
  value = module.storage.database_backup_policy_id
}

output "operations_bastion_id" {
  value = oci_bastion_bastion.operations.id
}

output "operations_bastion_private_endpoint_ip" {
  value = oci_bastion_bastion.operations.private_endpoint_ip_address
}
