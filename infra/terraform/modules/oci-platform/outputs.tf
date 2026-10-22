output "instance_ids" {
  value = { for name, instance in oci_core_instance.host : name => instance.id }
}

output "private_ips" {
  value = { for name, host in local.hosts : name => host.private_ip }
}
