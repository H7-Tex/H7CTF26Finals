locals {
  production = {
    for team in range(1, 17) : format("production-%02d", team) => {
      private_ip = format("10.60.%d.2", team)
      staging_ip = format("10.60.%d.3", team)
      subnet     = format("p%02d", team)
      team       = team
    }
  }

  workbenches = {
    for team in range(1, 16) : format("workbench-%02d", team) => {
      private_ip = format("10.61.%d.2", team)
      subnet     = format("w%02d", team)
      team       = team
    }
  }

  tags = {
    event      = "finals-2026"
    managed_by = "terraform"
  }
}

resource "oci_core_instance" "production" {
  for_each = local.production

  availability_domain = var.availability_domain
  compartment_id      = var.compartment_id
  display_name        = each.key
  shape               = "VM.Standard.E4.Flex"
  freeform_tags = merge(local.tags, {
    role = "production"
    team = each.value.team == 16 ? "reference" : format("team-%02d", each.value.team)
  })

  shape_config {
    ocpus         = 2
    memory_in_gbs = 12
  }

  create_vnic_details {
    assign_public_ip = false
    display_name     = each.key
    hostname_label   = replace(each.key, "-", "")
    nsg_ids          = [var.game_nsg_id]
    private_ip       = each.value.private_ip
    subnet_id        = var.production_subnet_ids[each.value.subnet]
  }

  source_details {
    source_id               = var.production_image_id
    source_type             = "image"
    boot_volume_size_in_gbs = 150
  }

  metadata = {
    ssh_authorized_keys = var.organizer_ssh_authorized_keys
    user_data           = base64encode(var.production_cloud_init)
  }

  instance_options {
    are_legacy_imds_endpoints_disabled = true
  }

  lifecycle {
    prevent_destroy = true
  }
}

data "oci_core_vnic_attachments" "production" {
  for_each = local.production

  compartment_id = var.compartment_id
  instance_id    = oci_core_instance.production[each.key].id
}

resource "oci_core_private_ip" "staging" {
  for_each = local.production

  vnic_id      = data.oci_core_vnic_attachments.production[each.key].vnic_attachments[0].vnic_id
  display_name = "${each.key}-staging"
  ip_address   = each.value.staging_ip

  lifecycle {
    prevent_destroy = true
  }
}

resource "oci_core_instance" "workbench" {
  for_each = local.workbenches

  availability_domain = var.availability_domain
  compartment_id      = var.compartment_id
  display_name        = each.key
  shape               = "VM.Standard.E4.Flex"
  freeform_tags = merge(local.tags, {
    role = "workbench"
    team = format("team-%02d", each.value.team)
  })

  shape_config {
    ocpus         = 2
    memory_in_gbs = 16
  }

  create_vnic_details {
    assign_public_ip = false
    display_name     = each.key
    hostname_label   = replace(each.key, "-", "")
    nsg_ids          = [var.game_nsg_id]
    private_ip       = each.value.private_ip
    subnet_id        = var.workbench_subnet_ids[each.value.subnet]
  }

  source_details {
    source_id               = var.workbench_image_id
    source_type             = "image"
    boot_volume_size_in_gbs = 100
  }

  metadata = {
    ssh_authorized_keys = join("\n", compact([
      var.organizer_ssh_authorized_keys,
      var.team_workbench_ssh_authorized_keys[format("team-%02d", each.value.team)]
    ]))
    user_data = base64encode(var.workbench_cloud_init)
  }

  instance_options {
    are_legacy_imds_endpoints_disabled = true
  }

  lifecycle {
    prevent_destroy = true
  }
}
