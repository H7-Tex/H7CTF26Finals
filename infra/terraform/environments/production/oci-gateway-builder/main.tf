locals {
  packaged_source_revision = trimspace(file("${path.module}/packaged-source-revision"))
  source_dir               = "${path.module}/../../../../images/router"
  source_files = setunion(
    fileset(local.source_dir, "rootfs/**"),
    fileset(local.source_dir, "tests/**"),
    toset(["build-image", "cloud-init.yaml", "gateway-image-seal.service", "install.sh", "seal-image"])
  )
  auxiliary_sources = {
    archive          = "${path.module}/../../../../archive"
    secret-bootstrap = "${path.module}/../../../../secrets"
    volumes          = "${path.module}/../../../../volumes"
  }
  executable_files = toset([
    "build-image",
    "install.sh",
    "rootfs/usr/local/libexec/event-router/render_inventory.py",
    "rootfs/usr/local/sbin/event-router-addresses",
    "rootfs/usr/local/sbin/event-router-activate",
    "rootfs/usr/local/sbin/event-router-apply-inventory",
    "rootfs/usr/local/sbin/event-router-authorize-reconciler",
    "rootfs/usr/local/sbin/event-router-capture",
    "rootfs/usr/local/sbin/event-router-initialize",
    "rootfs/usr/local/sbin/event-router-receive-inventory",
    "rootfs/usr/local/sbin/event-router-restore",
    "seal-image",
    "tests/challenge_access.sh",
    "tests/network_namespace.sh",
    "tests/restore.sh",
    "tests/run.sh",
    "archive/finals-archive.py",
    "archive/finals-archive-egress",
    "archive/install.sh",
    "archive/tests/run.sh",
    "secret-bootstrap/finals-secret-relay-receive",
    "secret-bootstrap/install-secret-bundle.py",
    "secret-bootstrap/tests/run.sh",
    "secret-bootstrap/tests/test_relay_receiver.sh",
    "volumes/initialize-volume.py",
    "volumes/tests/run.sh",
  ])
  files = concat([for path in local.source_files : {
    path           = path
    permissions    = contains(local.executable_files, path) ? "0755" : "0644"
    content_base64 = filebase64("${local.source_dir}/${path}")
    }], flatten([for prefix, directory in local.auxiliary_sources : [for path in fileset(directory, "**") : {
      path           = "${prefix}/${path}"
      permissions    = contains(local.executable_files, "${prefix}/${path}") ? "0755" : "0644"
      content_base64 = filebase64("${directory}/${path}")
    } if !endswith(path, ".pyc") && !contains(split("/", path), "__pycache__")]
    ]), [{
    path           = "platform/finals-host-recipient"
    permissions    = "0755"
    content_base64 = filebase64("${path.module}/../../../../platform/rootfs/usr/local/sbin/finals-host-recipient")
    }, {
    path        = "image-manifest.json"
    permissions = "0644"
    content_base64 = base64encode(jsonencode({
      base_image_id   = var.base_image_id
      source_revision = var.source_revision
    }))
  }])
  build_payload = templatefile("${path.module}/build-payload.tftpl", {
    files           = local.files
    source_revision = var.source_revision
  })
  payload_base64 = base64encode(local.build_payload)
  payload_size   = (length(local.payload_base64) / 4 * 3) - (endswith(local.payload_base64, "==") ? 2 : endswith(local.payload_base64, "=") ? 1 : 0)
  bootstrap_user_data = base64gzip(templatefile("${path.module}/bootstrap-cloud-init.tftpl", {
    installer_base64 = filebase64("${path.module}/../../../scripts/install-verified-build-payload")
    source_sha256    = sha256(local.build_payload)
    source_size      = local.payload_size
    source_url_json  = jsonencode(sensitive("https://objectstorage.${var.region}.oraclecloud.com${oci_objectstorage_preauthrequest.source.access_uri}"))
  }))
  tags = {
    event                 = "finals-2026"
    image_source_revision = var.source_revision
    managed_by            = "terraform"
    purpose               = "gateway-image-builder"
  }
}

check "packaged_source_revision" {
  assert {
    condition     = can(regex("^[0-9a-f]{40}$", local.packaged_source_revision)) && var.source_revision == local.packaged_source_revision
    error_message = "source_revision must match the clean Git HEAD recorded by package-oci-stack.sh."
  }
}

check "bootstrap_metadata_limit" {
  assert {
    condition     = length(local.bootstrap_user_data) < 16384
    error_message = "Encoded gateway builder user_data must remain below the 16 KiB OCI metadata limit."
  }
}

check "fixed_payload_paths" {
  assert {
    condition = (
      alltrue([for file in local.files : can(regex("^[A-Za-z0-9._/-]+$", file.path)) && !contains(split("/", file.path), "..")]) &&
      length(distinct([for file in local.files : file.path])) == length(local.files)
    )
    error_message = "Gateway build payload paths must be unique, relative repository paths with a fixed safe character set."
  }
}

data "oci_objectstorage_namespace" "current" {
  compartment_id = var.compartment_id
}

resource "oci_objectstorage_bucket" "source" {
  compartment_id = var.compartment_id
  namespace      = data.oci_objectstorage_namespace.current.namespace
  name           = "finals-gateway-source-${substr(var.source_revision, 0, 12)}"
  access_type    = "NoPublicAccess"
  auto_tiering   = "Disabled"
  storage_tier   = "Standard"
  versioning     = "Disabled"

  freeform_tags = {
    event      = "finals-2026"
    managed_by = "terraform"
    purpose    = "transient-gateway-image-source"
  }
}

resource "oci_objectstorage_object" "source" {
  bucket       = oci_objectstorage_bucket.source.name
  namespace    = data.oci_objectstorage_namespace.current.namespace
  object       = "gateway.build-payload.sh"
  content      = sensitive(local.build_payload)
  content_type = "text/x-shellscript"
}

resource "oci_objectstorage_preauthrequest" "source" {
  namespace    = data.oci_objectstorage_namespace.current.namespace
  bucket       = oci_objectstorage_bucket.source.name
  name         = "gateway-builder-${substr(var.source_revision, 0, 12)}"
  access_type  = "ObjectRead"
  object_name  = oci_objectstorage_object.source.object
  time_expires = var.source_bundle_expires_at
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
    user_data = local.bootstrap_user_data
  }

  instance_options {
    are_legacy_imds_endpoints_disabled = true
  }

  lifecycle {
    replace_triggered_by = [oci_core_network_security_group.builder.freeform_tags, oci_objectstorage_object.source]

    precondition {
      condition     = length(local.bootstrap_user_data) < 16384
      error_message = "Encoded gateway builder user_data must remain below the 16 KiB OCI metadata limit."
    }

    precondition {
      condition     = var.source_revision == local.packaged_source_revision
      error_message = "source_revision must match the clean Git HEAD recorded in the packaged builder root."
    }
  }
}
