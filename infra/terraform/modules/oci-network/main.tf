locals {
  fixed_subnets = {
    edge = {
      cidr         = "10.60.250.0/24"
      dns_label    = "edge"
      display_name = "edge"
      route_class  = "edge"
      public       = true
    }
    services = {
      cidr         = "10.60.200.0/24"
      dns_label    = "services"
      display_name = "services"
      route_class  = "service"
      public       = false
    }
    core = {
      cidr         = "10.60.201.0/24"
      dns_label    = "core"
      display_name = "core"
      route_class  = "isolated"
      public       = false
    }
    mirror = {
      cidr         = "10.60.202.0/24"
      dns_label    = "mirror"
      display_name = "mirror"
      route_class  = "mirror"
      public       = false
    }
    hills = {
      cidr         = "10.60.210.0/24"
      dns_label    = "hills"
      display_name = "hills"
      route_class  = "isolated"
      public       = false
    }
  }

  production_subnets = {
    for team in range(1, var.team_count + 2) : format("p%02d", team) => {
      cidr         = format("10.60.%d.0/24", team)
      dns_label    = format("production%02d", team)
      display_name = format("production-%02d", team)
      route_class  = "isolated"
      public       = false
    }
  }

  workbench_subnets = {
    for team in range(1, var.team_count + 1) : format("w%02d", team) => {
      cidr         = format("10.61.%d.0/24", team)
      dns_label    = format("workbench%02d", team)
      display_name = format("workbench-%02d", team)
      route_class  = "isolated"
      public       = false
    }
  }

  subnets = merge(local.fixed_subnets, local.production_subnets, local.workbench_subnets)

  route_tables = {
    edge     = oci_core_route_table.edge.id
    service  = oci_core_route_table.service.id
    mirror   = oci_core_route_table.mirror.id
    isolated = oci_core_route_table.isolated.id
  }

  tags = {
    event      = "finals-2026"
    managed_by = "terraform"
  }
}

resource "oci_core_vcn" "finals" {
  compartment_id = var.compartment_id
  cidr_blocks    = var.vcn_cidrs
  display_name   = "arena"
  dns_label      = "arena"
  freeform_tags  = local.tags

  lifecycle {
    prevent_destroy = true
  }
}

resource "oci_core_internet_gateway" "edge" {
  compartment_id = var.compartment_id
  vcn_id         = oci_core_vcn.finals.id
  display_name   = "internet"
  enabled        = true
  freeform_tags  = local.tags
}

resource "oci_core_nat_gateway" "warmup" {
  compartment_id = var.compartment_id
  vcn_id         = oci_core_vcn.finals.id
  display_name   = "egress"
  freeform_tags  = local.tags
}

resource "oci_core_security_list" "empty" {
  compartment_id = var.compartment_id
  vcn_id         = oci_core_vcn.finals.id
  display_name   = "deny-all"
  freeform_tags  = local.tags
}

resource "oci_core_route_table" "edge" {
  compartment_id = var.compartment_id
  vcn_id         = oci_core_vcn.finals.id
  display_name   = "edge"
  freeform_tags  = local.tags

  route_rules {
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
    network_entity_id = oci_core_internet_gateway.edge.id
  }
}

resource "oci_core_route_table" "service" {
  compartment_id = var.compartment_id
  vcn_id         = oci_core_vcn.finals.id
  display_name   = "services"
  freeform_tags  = local.tags

  dynamic "route_rules" {
    for_each = var.routing_private_ip_id == null ? [] : var.vcn_cidrs

    content {
      destination       = route_rules.value
      destination_type  = "CIDR_BLOCK"
      network_entity_id = var.routing_private_ip_id
    }
  }

  dynamic "route_rules" {
    for_each = var.enable_service_warmup_egress ? [true] : []

    content {
      destination       = "0.0.0.0/0"
      destination_type  = "CIDR_BLOCK"
      network_entity_id = oci_core_nat_gateway.warmup.id
    }
  }
}

resource "oci_core_route_table" "mirror" {
  compartment_id = var.compartment_id
  vcn_id         = oci_core_vcn.finals.id
  display_name   = "mirror"
  freeform_tags  = local.tags

  dynamic "route_rules" {
    for_each = var.routing_private_ip_id == null ? [] : var.vcn_cidrs

    content {
      destination       = route_rules.value
      destination_type  = "CIDR_BLOCK"
      network_entity_id = var.routing_private_ip_id
    }
  }

  dynamic "route_rules" {
    for_each = var.enable_mirror_warmup_egress ? [true] : []

    content {
      destination       = "0.0.0.0/0"
      destination_type  = "CIDR_BLOCK"
      network_entity_id = oci_core_nat_gateway.warmup.id
    }
  }
}

resource "oci_core_route_table" "isolated" {
  compartment_id = var.compartment_id
  vcn_id         = oci_core_vcn.finals.id
  display_name   = "isolated"
  freeform_tags  = local.tags

  dynamic "route_rules" {
    for_each = var.routing_private_ip_id == null ? [] : var.vcn_cidrs

    content {
      destination       = route_rules.value
      destination_type  = "CIDR_BLOCK"
      network_entity_id = var.routing_private_ip_id
    }
  }
}

resource "oci_core_network_security_group" "router" {
  compartment_id = var.compartment_id
  vcn_id         = oci_core_vcn.finals.id
  display_name   = "ingress"
  freeform_tags  = local.tags
}

resource "oci_core_network_security_group" "game" {
  compartment_id = var.compartment_id
  vcn_id         = oci_core_vcn.finals.id
  display_name   = "workloads"
  freeform_tags  = local.tags
}

resource "oci_core_network_security_group" "infra" {
  compartment_id = var.compartment_id
  vcn_id         = oci_core_vcn.finals.id
  display_name   = "platform"
  freeform_tags  = local.tags
}

resource "oci_core_network_security_group_security_rule" "router_game_ingress" {
  for_each = toset(var.vcn_cidrs)

  network_security_group_id = oci_core_network_security_group.router.id
  direction                 = "INGRESS"
  protocol                  = "all"
  source                    = each.value
  source_type               = "CIDR_BLOCK"
  stateless                 = true
  description               = "Routed finals traffic"
}

resource "oci_core_network_security_group_security_rule" "router_vpn_ingress" {
  network_security_group_id = oci_core_network_security_group.router.id
  direction                 = "INGRESS"
  protocol                  = "17"
  source                    = "0.0.0.0/0"
  source_type               = "CIDR_BLOCK"
  stateless                 = true
  description               = "WireGuard UDP 443"

  udp_options {
    destination_port_range {
      min = 443
      max = 443
    }
  }
}

resource "oci_core_network_security_group_security_rule" "router_web_ingress" {
  network_security_group_id = oci_core_network_security_group.router.id
  direction                 = "INGRESS"
  protocol                  = "6"
  source                    = "0.0.0.0/0"
  source_type               = "CIDR_BLOCK"
  stateless                 = true
  description               = "Finals web TCP 443"

  tcp_options {
    destination_port_range {
      min = 443
      max = 443
    }
  }
}

resource "oci_core_network_security_group_security_rule" "router_egress" {
  network_security_group_id = oci_core_network_security_group.router.id
  direction                 = "EGRESS"
  protocol                  = "all"
  destination               = "0.0.0.0/0"
  destination_type          = "CIDR_BLOCK"
  stateless                 = true
  description               = "Router forwarding egress"
}

resource "oci_core_network_security_group_security_rule" "game_ingress" {
  for_each = toset(var.vcn_cidrs)

  network_security_group_id = oci_core_network_security_group.game.id
  direction                 = "INGRESS"
  protocol                  = "all"
  source                    = each.value
  source_type               = "CIDR_BLOCK"
  stateless                 = true
  description               = "Finals VCN ingress"
}

resource "oci_core_network_security_group_security_rule" "game_egress" {
  for_each = toset(var.vcn_cidrs)

  network_security_group_id = oci_core_network_security_group.game.id
  direction                 = "EGRESS"
  protocol                  = "all"
  destination               = each.value
  destination_type          = "CIDR_BLOCK"
  stateless                 = true
  description               = "Finals VCN egress only"
}

resource "oci_core_network_security_group_security_rule" "infra_ingress" {
  for_each = toset(var.vcn_cidrs)

  network_security_group_id = oci_core_network_security_group.infra.id
  direction                 = "INGRESS"
  protocol                  = "all"
  source                    = each.value
  source_type               = "CIDR_BLOCK"
  stateless                 = true
  description               = "Finals VCN infrastructure ingress"
}

resource "oci_core_network_security_group_security_rule" "infra_egress" {
  network_security_group_id = oci_core_network_security_group.infra.id
  direction                 = "EGRESS"
  protocol                  = "all"
  destination               = "0.0.0.0/0"
  destination_type          = "CIDR_BLOCK"
  stateless                 = false
  description               = "Infrastructure egress where a route exists"
}

resource "oci_core_subnet" "finals" {
  for_each = local.subnets

  compartment_id             = var.compartment_id
  vcn_id                     = oci_core_vcn.finals.id
  cidr_block                 = each.value.cidr
  display_name               = each.value.display_name
  dns_label                  = each.value.dns_label
  route_table_id             = local.route_tables[each.value.route_class]
  security_list_ids          = [oci_core_security_list.empty.id]
  prohibit_public_ip_on_vnic = !each.value.public
  freeform_tags              = merge(local.tags, { subnet_role = each.key })
}
