locals {
  volumes = {
    database = {
      instance = "platform"
      size_gb  = 150
    }
    repositories = {
      instance = "repository"
      size_gb  = 100
    }
    cache = {
      instance = "mirror"
      size_gb  = 300
    }
    captures = {
      instance = "gateway-primary"
      size_gb  = 500
    }
  }

  tags = {
    event       = "finals-2026"
    managed_by  = "terraform"
    sensitivity = "operations"
  }
}

resource "oci_core_volume" "data" {
  for_each = local.volumes

  availability_domain = var.availability_domain
  compartment_id      = var.compartment_id
  display_name        = each.key
  size_in_gbs         = each.value.size_gb
  freeform_tags       = merge(local.tags, { role = each.key })

  lifecycle {
    prevent_destroy = true
  }
}

resource "oci_core_volume_attachment" "data" {
  for_each = local.volumes

  attachment_type = "paravirtualized"
  display_name    = each.key
  instance_id     = var.instance_ids[each.value.instance]
  volume_id       = oci_core_volume.data[each.key].id

  lifecycle {
    prevent_destroy = true
  }
}

resource "oci_core_volume_backup_policy" "database" {
  compartment_id = var.compartment_id
  display_name   = "database-hourly"

  schedules {
    backup_type       = "INCREMENTAL"
    offset_seconds    = 900
    offset_type       = "NUMERIC_SECONDS"
    period            = "ONE_HOUR"
    retention_seconds = 604800
    time_zone         = "UTC"
  }

  freeform_tags = merge(local.tags, { role = "database-backup" })

  lifecycle {
    prevent_destroy = true
  }
}

resource "oci_core_volume_backup_policy_assignment" "database" {
  asset_id  = oci_core_volume.data["database"].id
  policy_id = oci_core_volume_backup_policy.database.id

  lifecycle {
    prevent_destroy = true
  }
}
