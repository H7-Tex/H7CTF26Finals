output "builder_instance_ids" {
  value = { for role, instance in oci_core_instance.builder : role => instance.id }
}

output "builder_states" {
  value = { for role, instance in oci_core_instance.builder : role => instance.state }
}

output "build_payload_sha256" {
  value = {
    for role, content in local.build_payload : role => nonsensitive(sha256(content))
  }
}
