locals {
  routers = {
    primary = {
      private_ip = "10.60.250.10"
      ocpus      = 4
      memory_gb  = 16
    }
    standby = {
      private_ip = "10.60.250.11"
      ocpus      = 2
      memory_gb  = 16
    }
  }

  ingress = {
    vpn = {
      private_ip   = "10.60.250.100"
      display_name = "vpn"
    }
    web = {
      private_ip   = "10.60.250.101"
      display_name = "web"
    }
  }

  team_egress = {
    for team in range(1, 16) : format("team-%02d", team) => {
      private_ip   = format("10.60.250.%d", 120 + team)
      display_name = format("team-%02d-egress", team)
    }
  }

  tags = {
    event      = "finals-2026"
    managed_by = "terraform"
  }


  operations_relay_authorized_key = "restrict,command=\"/usr/local/sbin/finals-secret-relay-receive\" ${var.operations_relay_ssh_public_key}"
}

resource "oci_core_instance" "router" {
  for_each = local.routers

  availability_domain = var.availability_domain
  compartment_id      = var.compartment_id
  display_name        = "gateway-${each.key}"
  shape               = "VM.Standard.E4.Flex"
  freeform_tags       = merge(local.tags, { role = "gateway" })

  shape_config {
    ocpus         = each.value.ocpus
    memory_in_gbs = each.value.memory_gb
  }

  create_vnic_details {
    assign_public_ip       = false
    display_name           = "gateway-${each.key}"
    hostname_label         = "gateway-${each.key}"
    nsg_ids                = [var.router_nsg_id]
    private_ip             = each.value.private_ip
    skip_source_dest_check = true
    subnet_id              = var.edge_subnet_id
  }

  source_details {
    source_id               = var.router_image_id
    source_type             = "image"
    boot_volume_size_in_gbs = 50
  }

  metadata = {
    ssh_authorized_keys = join("\n", [
      trimspace(var.organizer_ssh_authorized_keys),
      local.operations_relay_authorized_key,
    ])
    user_data = base64encode(replace(
      var.cloud_init,
      "__ROUTER_STATE__",
      each.key == var.active_router ? "active" : "standby"
    ))
  }

  instance_options {
    are_legacy_imds_endpoints_disabled = true
  }

  lifecycle {
    prevent_destroy = true
  }
}

data "oci_core_vnic_attachments" "router" {
  for_each = local.routers

  compartment_id = var.compartment_id
  instance_id    = oci_core_instance.router[each.key].id
}

resource "oci_core_private_ip" "ingress" {
  for_each = local.ingress

  vnic_id      = data.oci_core_vnic_attachments.router[var.active_router].vnic_attachments[0].vnic_id
  display_name = each.value.display_name
  ip_address   = each.value.private_ip

  lifecycle {
    prevent_destroy = true
  }
}

resource "oci_core_private_ip" "service_ingress" {
  vnic_id      = data.oci_core_vnic_attachments.router[var.active_router].vnic_attachments[0].vnic_id
  display_name = "service-ingress"
  ip_address   = "10.60.250.120"

  lifecycle {
    prevent_destroy = true
  }
}

resource "oci_core_private_ip" "team_egress" {
  for_each = local.team_egress

  vnic_id      = data.oci_core_vnic_attachments.router[var.active_router].vnic_attachments[0].vnic_id
  display_name = each.value.display_name
  ip_address   = each.value.private_ip

  lifecycle {
    prevent_destroy = true
  }
}
