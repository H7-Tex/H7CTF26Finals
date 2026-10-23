locals {
  packaged_source_revision = trimspace(file("${path.module}/packaged-source-revision"))
  profiles = {
    platform-x86 = {
      shape       = "VM.Standard.E4.Flex"
      boot_volume = 50
    }
    platform-arm = {
      shape       = "VM.Standard.A1.Flex"
      boot_volume = 50
    }
    production = {
      shape       = "VM.Standard.E4.Flex"
      boot_volume = 50
    }
    workbench = {
      shape       = "VM.Standard.E4.Flex"
      boot_volume = 80
    }
  }
  canary_scripts = {
    for role in keys(local.profiles) : role => templatefile("${path.module}/canary-check.sh.tftpl", {
      anvil_revision        = var.anvil_revision
      image_source_revision = var.image_source_revision
      role                  = role
    })
  }
  cloud_init = {
    for role, script in local.canary_scripts : role => base64gzip(templatefile("${path.module}/canary-cloud-init.tftpl", {
      canary_script_base64 = base64encode(script)
    }))
  }
}

check "packaged_source_revision" {
  assert {
    condition     = can(regex("^[0-9a-f]{40}$", local.packaged_source_revision)) && var.package_source_revision == local.packaged_source_revision
    error_message = "package_source_revision must match the clean Git HEAD recorded by package-oci-stack.sh."
  }
}

check "metadata_limit" {
  assert {
    condition     = alltrue([for content in values(local.cloud_init) : length(content) < 16384])
    error_message = "Every encoded runtime canary user_data payload must remain below the 16 KiB OCI metadata limit."
  }
}

data "oci_core_services" "regional" {
  filter {
    name   = "name"
    values = ["All HYD Services In Oracle Services Network"]
  }
}

check "regional_service" {
  assert {
    condition     = length(data.oci_core_services.regional.services) == 1
    error_message = "The Hyderabad regional OCI service network must resolve exactly once."
  }
}

data "oci_core_image" "runtime" {
  for_each = local.profiles

  image_id = var.image_ids[each.key]
}

resource "oci_core_network_security_group" "canary" {
  compartment_id = var.compartment_id
  vcn_id         = var.vcn_id
  display_name   = "runtime-image-canaries"
  freeform_tags = {
    event      = "finals-2026"
    managed_by = "terraform"
    purpose    = "runtime-image-canary"
  }
}

resource "oci_core_network_security_group_security_rule" "oracle_services" {
  network_security_group_id = oci_core_network_security_group.canary.id
  direction                 = "EGRESS"
  protocol                  = "6"
  destination               = data.oci_core_services.regional.services[0].cidr_block
  destination_type          = "SERVICE_CIDR_BLOCK"
  stateless                 = false
  description               = "OCI Run Command acknowledgement only"

  tcp_options {
    destination_port_range {
      min = 443
      max = 443
    }
  }
}

resource "oci_core_instance" "canary" {
  for_each = local.profiles

  availability_domain = var.availability_domain
  compartment_id      = var.compartment_id
  display_name        = "runtime-canary-${each.key}"
  shape               = each.value.shape
  freeform_tags = {
    event                  = "finals-2026"
    image_role             = each.key
    image_source_revision  = var.image_source_revision
    canary_source_revision = var.package_source_revision
    managed_by             = "terraform"
    purpose                = "runtime-image-canary"
  }

  shape_config {
    ocpus         = 1
    memory_in_gbs = 8
  }

  availability_config {
    recovery_action = "STOP_INSTANCE"
  }

  create_vnic_details {
    assign_public_ip       = false
    display_name           = "runtime-canary-${each.key}"
    hostname_label         = replace("canary-${each.key}", "-", "")
    nsg_ids                = [oci_core_network_security_group.canary.id]
    skip_source_dest_check = false
    subnet_id              = var.service_subnet_id
  }

  source_details {
    source_id               = var.image_ids[each.key]
    source_type             = "image"
    boot_volume_size_in_gbs = each.value.boot_volume
  }

  metadata = {
    user_data = local.cloud_init[each.key]
  }

  instance_options {
    are_legacy_imds_endpoints_disabled = true
  }

  lifecycle {
    precondition {
      condition = (
        data.oci_core_image.runtime[each.key].state == "AVAILABLE" &&
        data.oci_core_image.runtime[each.key].compartment_id == var.compartment_id &&
        lookup(data.oci_core_image.runtime[each.key].freeform_tags, "image_role", "") == each.key &&
        lookup(data.oci_core_image.runtime[each.key].freeform_tags, "image_source_revision", "") == var.image_source_revision
      )
      error_message = "Every canary image must be AVAILABLE and match its reviewed compartment, role and source revision."
    }

    precondition {
      condition     = length(local.cloud_init[each.key]) < 16384
      error_message = "Encoded runtime canary user_data must remain below the OCI metadata limit."
    }
  }
}
