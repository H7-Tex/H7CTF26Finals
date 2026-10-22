output "image_id" {
  value = oci_core_image.gateway.id
}

output "image_name" {
  value = oci_core_image.gateway.display_name
}

output "image_state" {
  value = oci_core_image.gateway.state
}
