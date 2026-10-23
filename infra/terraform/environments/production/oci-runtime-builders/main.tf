locals {
  packaged_source_revision = trimspace(file("${path.module}/packaged-source-revision"))
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
  runtime_dir = "${path.module}/../../../../images/runtime"
  runtime_files = setunion(
    fileset(local.runtime_dir, "rootfs/**"),
    fileset(local.runtime_dir, "tests/**"),
    toset(["build-image", "fetch-model-a-release", "install.sh", "runtime-image-seal.service", "seal-image"])
  )
  auxiliary_sources = {
    archive          = "${path.module}/../../../../archive"
    checkers         = "${path.module}/../../../../checkers"
    deployment       = "${path.module}/../../../../deployment"
    hills            = "${path.module}/../../../../hills"
    model-a-runtime  = "${path.module}/../../../../model-a-runtime"
    platform         = "${path.module}/../../../../platform"
    reconciler       = "${path.module}/../../../../reconciler"
    secret-bootstrap = "${path.module}/../../../../secrets"
    team-access      = "${path.module}/../../../../team-access"
    volumes          = "${path.module}/../../../../volumes"
  }
  executable_files = toset([
    "build-image",
    "fetch-model-a-release",
    "install.sh",
    "seal-image",
    "tests/run.sh",
    "tests/static.sh",
    "archive/finals-archive.py",
    "archive/finals-archive-egress",
    "archive/install.sh",
    "archive/tests/run.sh",
    "deployment/compile-release.py",
    "deployment/install.sh",
    "deployment/tests/service_proxy_smoke.py",
    "deployment/tests/run.sh",
    "hills/credential_sync.py",
    "hills/finals-hill-compose",
    "hills/install.sh",
    "hills/tests/run.sh",
    "model-a-runtime/install.sh",
    "model-a-runtime/prepare-release.py",
    "model-a-runtime/rootfs/usr/local/bin/h7",
    "model-a-runtime/rootfs/usr/local/sbin/finals-model-a-control",
    "model-a-runtime/rootfs/usr/local/sbin/finals-model-a-firstboot",
    "model-a-runtime/rootfs/usr/local/sbin/finals-model-a-install",
    "model-a-runtime/tests/firewall-path.py",
    "model-a-runtime/tests/local-acceptance.py",
    "model-a-runtime/tests/run.sh",
    "checkers/install.sh",
    "checkers/rootfs/usr/local/libexec/checker-runtime/runtime.py",
    "checkers/rootfs/usr/local/sbin/checker-runtime-commission",
    "checkers/tests/egress_isolation.sh",
    "checkers/tests/run.sh",
    "platform/install.sh",
    "platform/prepare-anvil.sh",
    "platform/rootfs/usr/local/libexec/finals-platform/checker-preflight",
    "platform/rootfs/usr/local/libexec/finals-platform/firewall",
    "platform/rootfs/usr/local/libexec/finals-platform/mirror-preflight",
    "platform/rootfs/usr/local/libexec/finals-platform/mirror-runtime-verify",
    "platform/rootfs/usr/local/libexec/finals-platform/repository-preflight",
    "platform/rootfs/usr/local/sbin/finals-host-recipient",
    "platform/rootfs/usr/local/sbin/finals-mirror-manifest",
    "platform/rootfs/usr/local/sbin/finals-mirror-mode",
    "platform/rootfs/usr/local/sbin/finals-operations-ssh",
    "platform/rootfs/usr/local/sbin/finals-platform-activate",
    "platform/rootfs/usr/local/sbin/finals-repository-commission",
    "platform/tests/run.sh",
    "reconciler/install.sh",
    "reconciler/rootfs/usr/local/libexec/peer-reconciler/reconcile.py",
    "reconciler/tests/run.sh",
    "secret-bootstrap/finals-secret-relay-receive",
    "secret-bootstrap/install-secret-bundle.py",
    "secret-bootstrap/tests/run.sh",
    "secret-bootstrap/tests/test_relay_receiver.sh",
    "team-access/install.sh",
    "team-access/team-access.py",
    "team-access/tests/run.sh",
    "volumes/initialize-volume.py",
    "volumes/rehearse-production-quota",
    "volumes/tests/run.sh",
  ])
  router_validator_file = [{
    path           = "images/router/rootfs/usr/local/libexec/event-router/render_inventory.py"
    permissions    = "0755"
    content_base64 = filebase64("${path.module}/../../../../images/router/rootfs/usr/local/libexec/event-router/render_inventory.py")
  }]
  files = concat([for path in local.runtime_files : {
    path           = path
    permissions    = contains(local.executable_files, path) ? "0755" : "0644"
    content_base64 = filebase64("${local.runtime_dir}/${path}")
    }], local.router_validator_file, flatten([for prefix, directory in local.auxiliary_sources : [for path in fileset(directory, "**") : {
      path           = "${prefix}/${path}"
      permissions    = contains(local.executable_files, "${prefix}/${path}") ? "0755" : "0644"
      content_base64 = filebase64("${directory}/${path}")
    } if !endswith(path, ".pyc") && !contains(split("/", path), "__pycache__") && !(prefix == "model-a-runtime" && startswith(path, "evidence/"))]
  ]))
  # production bakes the model a release; the par lives only in this one payload file
  model_a_release_file = [{
    path        = "model-a-release.json"
    permissions = "0600"
    content_base64 = base64encode(jsonencode({
      base_url       = var.model_a_release_url
      release_sha256 = var.model_a_release.release_sha256
      objects        = var.model_a_release.objects
    }))
  }]
  payload_files = {
    for role, profile in local.profiles : role => concat(local.files, role == "production" ? local.model_a_release_file : [], [{
      path        = "image-manifest.json"
      permissions = "0644"
      content_base64 = base64encode(jsonencode({
        anvil_revision  = var.anvil_revision
        base_image_id   = profile.base_image_id
        role            = role
        source_revision = var.source_revision
      }))
    }])
  }
  build_payload = {
    for role in keys(local.profiles) : role => templatefile("${path.module}/build-payload.tftpl", {
      anvil_revision  = var.anvil_revision
      files           = local.payload_files[role]
      role            = role
      source_revision = var.source_revision
    })
  }
  expanded_base64 = {
    for role, content in local.build_payload : role => base64encode(content)
  }
  expanded_size = {
    for role, content in local.expanded_base64 : role => (length(content) / 4 * 3) - (endswith(content, "==") ? 2 : endswith(content, "=") ? 1 : 0)
  }
  bootstrap_user_data = {
    for role in keys(local.profiles) : role => base64gzip(templatefile("${path.module}/bootstrap-cloud-init.tftpl", {
      installer_base64 = filebase64("${path.module}/../../../scripts/install-verified-build-payload")
      source_sha256    = sha256(local.build_payload[role])
      source_size      = local.expanded_size[role]
      source_url_json  = jsonencode(sensitive("https://objectstorage.${var.region}.oraclecloud.com${oci_objectstorage_preauthrequest.source[role].access_uri}"))
      role             = role
      anvil_revision   = var.anvil_revision
    }))
  }
}

check "model_a_release" {
  assert {
    condition     = var.model_a_release_url != "" && var.model_a_release.objects["release.json"].sha256 == var.model_a_release.release_sha256
    error_message = "production images bake the model a release: set model_a_release_url and keep release.json pinned to release_sha256."
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
    condition     = alltrue([for content in values(local.bootstrap_user_data) : length(content) < 16384])
    error_message = "Every encoded runtime builder user_data payload must remain below the 16 KiB OCI metadata limit."
  }
}

check "fixed_payload_paths" {
  assert {
    condition = (
      alltrue([for file in local.files : can(regex("^[A-Za-z0-9._/@-]+$", file.path)) && !contains(split("/", file.path), "..")]) &&
      length(distinct([for file in local.files : file.path])) == length(local.files)
    )
    error_message = "Runtime build payload paths must be unique, relative repository paths with a fixed safe character set."
  }
}

data "oci_objectstorage_namespace" "current" {
  compartment_id = var.compartment_id
}

resource "oci_objectstorage_bucket" "source" {
  compartment_id = var.compartment_id
  namespace      = data.oci_objectstorage_namespace.current.namespace
  name           = "finals-runtime-source-${substr(var.source_revision, 0, 12)}"
  access_type    = "NoPublicAccess"
  auto_tiering   = "Disabled"
  storage_tier   = "Standard"
  versioning     = "Disabled"

  freeform_tags = {
    event      = "finals-2026"
    managed_by = "terraform"
    purpose    = "transient-runtime-image-source"
  }
}

resource "oci_objectstorage_object" "source" {
  for_each = local.profiles

  bucket       = oci_objectstorage_bucket.source.name
  namespace    = data.oci_objectstorage_namespace.current.namespace
  object       = "${each.key}.build-payload.sh"
  content      = sensitive(local.build_payload[each.key])
  content_type = "text/x-shellscript"
}

resource "oci_objectstorage_preauthrequest" "source" {
  for_each = local.profiles

  namespace    = data.oci_objectstorage_namespace.current.namespace
  bucket       = oci_objectstorage_bucket.source.name
  name         = "runtime-builder-${each.key}-${substr(var.source_revision, 0, 12)}"
  access_type  = "ObjectRead"
  object_name  = oci_objectstorage_object.source[each.key].object
  time_expires = var.source_bundle_expires_at
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

resource "terraform_data" "builder_generation" {
  for_each = local.profiles

  triggers_replace = [
    oci_objectstorage_preauthrequest.source[each.key].id,
    sha256(local.bootstrap_user_data[each.key]),
  ]
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
    anvil_source_revision = var.anvil_revision
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
    user_data = local.bootstrap_user_data[each.key]
  }

  instance_options {
    are_legacy_imds_endpoints_disabled = true
  }

  lifecycle {
    replace_triggered_by = [
      oci_objectstorage_object.source[each.key],
      terraform_data.builder_generation[each.key],
    ]

    precondition {
      condition     = length(local.bootstrap_user_data[each.key]) < 16384
      error_message = "Encoded runtime builder user_data must remain below the 16 KiB OCI metadata limit."
    }

    precondition {
      condition     = var.source_revision == local.packaged_source_revision
      error_message = "source_revision must match the clean Git HEAD recorded in the packaged builder root."
    }
  }
}
