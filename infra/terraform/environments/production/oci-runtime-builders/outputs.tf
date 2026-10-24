output "builder_instance_ids" {
  value = { for role, instance in oci_core_instance.builder : role => instance.id }
}

output "builder_states" {
  value = { for role, instance in oci_core_instance.builder : role => instance.state }
}

output "build_payload_sha256" {
  value = {
    platform-arm = sha256(local.build_payload["platform-arm"])
    platform-x86 = sha256(local.build_payload["platform-x86"])
    production   = nonsensitive(sha256(local.build_payload["production"]))
    workbench    = sha256(local.build_payload["workbench"])
  }
}
