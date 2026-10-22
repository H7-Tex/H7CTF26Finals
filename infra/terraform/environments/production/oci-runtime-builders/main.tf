locals {
  profiles = {
    platform-x86 = {
      shape         = "VM.Standard.E4.Flex"
      base_image_id = var.x86_base_image_id
    }
    platform-arm = {
      shape         = "VM.Standard.A1.Flex"
      base_image_id = var.arm_base_image_id
    }
    production = {
      shape         = "VM.Standard.E4.Flex"
      base_image_id = var.x86_base_image_id
    }
    workbench = {
      shape         = "VM.Standard.E4.Flex"
      base_image_id = var.x86_base_image_id
    }
  }
  source_dir = "${path.module}/../../../../images/runtime"
  source_files = setunion(
    fileset(local.source_dir, "rootfs/**"),
    fileset(local.source_dir, "tests/**"),
    toset(["build-image", "install.sh", "runtime-image-seal.service", "seal-image"])
  )
  executable_files = toset([
    "build-image",
    "install.sh",
    "seal-image",
    "tests/run.sh",
    "tests/static.sh",
  ])
  files = [for path in local.source_files : {
    path        = path
    permissions = contains(local.executable_files, path) ? "0755" : "0644"
    content     = file("${local.source_dir}/${path}")
  }]
}

resource "oci_core_network_security_group" "builder" {
  compartment_id = var.compartment_id
  vcn_id         = var.vcn_id
  display_name   = "runtime-image-builders"
  freeform_tags = {
    event      = "finals-2026"
    managed_by = "terraform"
    purpose    = "runtime-image-build"
  }
}

resource "oci_core_network_security_group_security_rule" "builder_egress" {
  network_security_group_id = oci_core_network_security_group.builder.id
  direction                 = "EGRESS"
  protocol                  = "all"
  destination               = "0.0.0.0/0"
  destination_type          = "CIDR_BLOCK"
  stateless                 = false
  description               = "Package installation during image build"
}

resource "oci_core_instance" "builder" {
  for_each = local.profiles

  availability_domain = var.availability_domain
  compartment_id      = var.compartment_id
  display_name        = "runtime-builder-${each.key}"
  shape               = each.value.shape
  freeform_tags = {
    event                 = "finals-2026"
    image_role            = each.key
    image_source_revision = var.source_revision
    managed_by            = "terraform"
    purpose               = "runtime-image-builder"
  }

  shape_config {
    ocpus         = 1
    memory_in_gbs = 8
  }

  availability_config {
    recovery_action = "STOP_INSTANCE"
  }

  create_vnic_details {
    assign_public_ip       = true
    display_name           = "runtime-builder-${each.key}"
    hostname_label         = replace("builder-${each.key}", "-", "")
    nsg_ids                = [oci_core_network_security_group.builder.id]
    skip_source_dest_check = false
    subnet_id              = var.edge_subnet_id
  }

  source_details {
    source_id               = each.value.base_image_id
    source_type             = "image"
    boot_volume_size_in_gbs = each.key == "workbench" ? 80 : 50
  }

  metadata = {
    user_data = base64gzip(templatefile("${path.module}/cloud-init.tftpl", {
      base_image_id   = each.value.base_image_id
      files           = local.files
      role            = each.key
      source_revision = var.source_revision
    }))
  }

  instance_options {
    are_legacy_imds_endpoints_disabled = true
  }
}
