output "router_instance_ids" {
  value = module.ingress.router_instance_ids
}

output "ingress_private_ip_ids" {
  value = module.ingress.ingress_private_ip_ids
}

output "ingress_private_ips" {
  value = module.ingress.ingress_private_ips
}

output "routing_private_ip_id" {
  value = module.ingress.routing_private_ip_id
}

output "service_ingress_private_ip_id" {
  value = module.ingress.service_ingress_private_ip_id
}

output "service_ingress_private_ip" {
  value = module.ingress.service_ingress_private_ip
}

output "team_egress_private_ip_ids" {
  value = module.ingress.team_egress_private_ip_ids
}

output "team_egress_private_ips" {
  value = module.ingress.team_egress_private_ips
}
