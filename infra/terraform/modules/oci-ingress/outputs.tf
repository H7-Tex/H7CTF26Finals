output "router_instance_ids" {
  value = { for name, instance in oci_core_instance.router : name => instance.id }
}

output "ingress_private_ip_ids" {
  value = { for name, address in oci_core_private_ip.ingress : name => address.id }
}

output "ingress_private_ips" {
  value = { for name, address in oci_core_private_ip.ingress : name => address.ip_address }
}

output "routing_private_ip_id" {
  value = oci_core_private_ip.ingress["vpn"].id
}

output "team_egress_private_ip_ids" {
  value = { for name, address in oci_core_private_ip.team_egress : name => address.id }
}

output "team_egress_private_ips" {
  value = { for name, address in oci_core_private_ip.team_egress : name => address.ip_address }
}
