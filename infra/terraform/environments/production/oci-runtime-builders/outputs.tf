output "builder_instance_ids" {
  value = { for role, instance in oci_core_instance.builder : role => instance.id }
}

output "builder_states" {
  value = { for role, instance in oci_core_instance.builder : role => instance.state }
}
