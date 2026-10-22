locals {
  source_dir = "${path.module}/../../../../images/router"
  source_files = setunion(
    fileset(local.source_dir, "rootfs/**"),
    fileset(local.source_dir, "tests/**"),
    toset(["build-image", "gateway-image-seal.service", "install.sh", "seal-image"])
  )
  executable_files = toset([
    "build-image",
    "install.sh",
    "rootfs/usr/local/libexec/event-router/render_inventory.py",
    "rootfs/usr/local/sbin/event-router-addresses",
    "rootfs/usr/local/sbin/event-router-apply-inventory",
    "rootfs/usr/local/sbin/event-router-authorize-reconciler",
    "rootfs/usr/local/sbin/event-router-receive-inventory",
    "seal-image",
    "tests/network_namespace.sh",
    "tests/run.sh",
  ])
  files = [for path in local.source_files : {
    path        = path
    permissions = contains(local.executable_files, path) ? "0755" : "0644"
    content     = file("${local.source_dir}/${path}")
  }]
  cloud_init = templatefile("${path.module}/cloud-init.tftpl", {
    base_image_id   = var.base_image_id
    files           = local.files
    source_revision = var.source_revision
  })
  tags = {
    event                 = "finals-2026"
    image_source_revision = var.source_revision
    managed_by            = "terraform"
    purpose               = "gateway-image-builder"
  }
}

resource "oci_core_network_security_group" "builder" {
  compartment_id = var.compartment_id
  vcn_id         = var.vcn_id
  display_name   = "gateway-image-builder"
  freeform_tags  = local.tags
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
  availability_domain = var.availability_domain
  compartment_id      = var.compartment_id
  display_name        = "gateway-image-builder"
  shape               = "VM.Standard.E4.Flex"
  freeform_tags       = local.tags

  shape_config {
    ocpus         = 1
    memory_in_gbs = 8
  }

  availability_config {
    recovery_action = "STOP_INSTANCE"
  }

  create_vnic_details {
    assign_public_ip       = true
    display_name           = "gateway-image-builder"
    hostname_label         = "gateway-image-builder"
    nsg_ids                = [oci_core_network_security_group.builder.id]
    skip_source_dest_check = false
    subnet_id              = var.edge_subnet_id
  }

  source_details {
    source_id               = var.base_image_id
    source_type             = "image"
    boot_volume_size_in_gbs = 50
  }

  metadata = {
    user_data = base64gzip(local.cloud_init)
  }

  instance_options {
    are_legacy_imds_endpoints_disabled = true
  }
}
