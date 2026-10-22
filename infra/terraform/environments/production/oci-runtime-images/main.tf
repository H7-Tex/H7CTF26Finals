locals {
  roles = toset(["platform-x86", "platform-arm", "production", "workbench"])
}

data "oci_core_instance" "builder" {
  for_each = local.roles

  instance_id = var.builder_instance_ids[each.key]
}

resource "oci_core_image" "runtime" {
  for_each = local.roles

  compartment_id = var.compartment_id
  display_name   = "${each.key}-${substr(var.source_revision, 0, 12)}"
  instance_id    = var.builder_instance_ids[each.key]
  freeform_tags = {
    event                 = "finals-2026"
    image_role            = each.key
    image_source_revision = var.source_revision
    managed_by            = "terraform"
  }

  lifecycle {
    prevent_destroy = true

    precondition {
      condition     = data.oci_core_instance.builder[each.key].state == "STOPPED"
      error_message = "Every runtime image builder must finish testing and stop before capture."
    }

    precondition {
      condition = (
        data.oci_core_instance.builder[each.key].compartment_id == var.compartment_id &&
        lookup(data.oci_core_instance.builder[each.key].freeform_tags, "image_role", "") == each.key &&
        lookup(data.oci_core_instance.builder[each.key].freeform_tags, "image_source_revision", "") == var.source_revision
      )
      error_message = "Builder compartment, role and source revision must match the capture request."
    }
  }

  timeouts {
    create = "90m"
  }
}
