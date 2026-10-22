output "router_instance_ids" {
  value = { for name, instance in oci_core_instance.router : name => instance.id }
}

output "ingress_private_ip_ids" {
  value = { for name, address in oci_core_private_ip.ingress : name => address.id }
}

output "web_public_ip" {
  value = oci_core_public_ip.ingress["web"].ip_address
}

output "vpn_public_ip" {
  value = oci_core_public_ip.ingress["vpn"].ip_address
}
