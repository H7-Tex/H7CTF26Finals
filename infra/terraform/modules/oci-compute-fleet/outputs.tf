output "production_instance_ids" {
  value = { for name, instance in oci_core_instance.production : name => instance.id }
}

output "production_private_ips" {
  value = { for name, host in local.production : name => host.private_ip }
}

output "staging_private_ip_ids" {
  value = { for name, private_ip in oci_core_private_ip.staging : name => private_ip.id }
}

output "staging_private_ips" {
  value = { for name, host in local.production : name => host.staging_ip }
}

output "workbench_instance_ids" {
  value = { for name, instance in oci_core_instance.workbench : name => instance.id }
}

output "workbench_private_ips" {
  value = { for name, host in local.workbenches : name => host.private_ip }
}
