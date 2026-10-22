output "image_ids" {
  value = { for role, image in oci_core_image.runtime : role => image.id }
}

output "image_states" {
  value = { for role, image in oci_core_image.runtime : role => image.state }
}
