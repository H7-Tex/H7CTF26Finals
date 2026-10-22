output "instance_ids" {
  value = module.platform.instance_ids
}

output "private_ips" {
  value = module.platform.private_ips
}

output "volume_ids" {
  value = module.storage.volume_ids
}
