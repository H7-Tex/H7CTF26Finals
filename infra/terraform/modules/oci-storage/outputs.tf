output "volume_ids" {
  value = { for name, volume in oci_core_volume.data : name => volume.id }
}

output "database_backup_policy_id" {
  value = oci_core_volume_backup_policy.database.id
}
