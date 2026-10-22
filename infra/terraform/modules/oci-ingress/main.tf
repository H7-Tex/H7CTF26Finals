locals {
  routers = {
    r1 = {
      private_ip = "10.60.250.10"
      ocpus      = 4
      memory_gb  = 16
    }
    r2 = {
      private_ip = "10.60.250.11"
      ocpus      = 2
      memory_gb  = 16
    }
  }

  ingress = {
    vpn = {
      private_ip   = "10.60.250.100"
      display_name = "h7f-vpn-ingress"
    }
    web = {
      private_ip   = "10.60.250.101"
      display_name = "h7f-web-ingress"
    }
  }

  tags = {
    event      = "h7ctf26-finals"
    managed_by = "terraform"
  }
}

resource "oci_core_instance" "router" {
  for_each = local.routers

  availability_domain = var.availability_domain
  compartment_id      = var.compartment_id
  display_name        = "h7f-${each.key}"
  shape               = "VM.Standard.E4.Flex"
  freeform_tags       = merge(local.tags, { role = "router" })

  shape_config {
    ocpus         = each.value.ocpus
    memory_in_gbs = each.value.memory_gb
  }

  create_vnic_details {
    assign_public_ip       = false
    display_name           = "h7f-${each.key}-primary"
    hostname_label         = "h7f-${each.key}"
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
    ssh_authorized_keys = var.ssh_authorized_keys
    user_data           = base64encode(var.cloud_init)
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
}

resource "oci_core_public_ip" "ingress" {
  for_each = local.ingress

  compartment_id = var.compartment_id
  display_name   = each.value.display_name
  lifetime       = "RESERVED"
  private_ip_id  = oci_core_private_ip.ingress[each.key].id
  freeform_tags  = merge(local.tags, { ingress = each.key })

  lifecycle {
    prevent_destroy = true
  }
}
