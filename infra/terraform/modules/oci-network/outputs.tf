output "vcn_id" {
  value = oci_core_vcn.finals.id
}

output "internet_gateway_id" {
  value = oci_core_internet_gateway.edge.id
}

output "nat_gateway_id" {
  value = oci_core_nat_gateway.warmup.id
}

output "subnet_ids" {
  value = { for name, subnet in oci_core_subnet.finals : name => subnet.id }
}

output "route_table_ids" {
  value = {
    edge     = oci_core_route_table.edge.id
    service  = oci_core_route_table.service.id
    mirror   = oci_core_route_table.mirror.id
    isolated = oci_core_route_table.isolated.id
  }
}

output "network_security_group_ids" {
  value = {
    router = oci_core_network_security_group.router.id
    game   = oci_core_network_security_group.game.id
    infra  = oci_core_network_security_group.infra.id
  }
}
