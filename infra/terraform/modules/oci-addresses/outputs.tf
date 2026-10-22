output "ids" {
  value = { for name, address in oci_core_public_ip.ingress : name => address.id }
}

output "addresses" {
  value = { for name, address in oci_core_public_ip.ingress : name => address.ip_address }
}
