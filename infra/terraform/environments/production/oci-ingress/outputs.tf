output "router_instance_ids" {
  value = module.ingress.router_instance_ids
}

output "ingress_private_ip_ids" {
  value = module.ingress.ingress_private_ip_ids
}

output "web_public_ip" {
  value = module.ingress.web_public_ip
}

output "vpn_public_ip" {
  value = module.ingress.vpn_public_ip
}
