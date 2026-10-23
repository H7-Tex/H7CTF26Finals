output "canary_instance_ids" {
  value = { for role, instance in oci_core_instance.canary : role => instance.id }
}

output "canary_states" {
  value = { for role, instance in oci_core_instance.canary : role => instance.state }
}

output "canary_private_ips" {
  value = { for role, instance in oci_core_instance.canary : role => instance.private_ip }
}
