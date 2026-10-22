output "router_instance_ids" {
  value = module.ingress.router_instance_ids
}

output "ingress_private_ip_ids" {
  value = module.ingress.ingress_private_ip_ids
}

output "ingress_private_ips" {
  value = module.ingress.ingress_private_ips
}

output "team_egress_private_ip_ids" {
  value = module.ingress.team_egress_private_ip_ids
}

output "team_egress_private_ips" {
  value = module.ingress.team_egress_private_ips
}
