output "volume_ids" {
  value = { for name, volume in oci_core_volume.data : name => volume.id }
}
