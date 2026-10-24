output "instance_ids" {
  value = merge(
    { for name, instance in oci_core_instance.host : name => instance.id },
    { for name, instance in oci_core_instance.host_arm : name => instance.id },
  )
}

output "private_ips" {
  value = { for name, host in local.hosts : name => host.private_ip }
}
