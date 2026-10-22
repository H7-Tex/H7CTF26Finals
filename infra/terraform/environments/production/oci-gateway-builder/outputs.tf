output "instance_id" {
  value = oci_core_instance.builder.id
}

output "instance_state" {
  value = oci_core_instance.builder.state
}

output "public_ip" {
  value = oci_core_instance.builder.public_ip
}
