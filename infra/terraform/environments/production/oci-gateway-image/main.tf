data "oci_core_instance" "builder" {
  instance_id = var.builder_instance_id
}

resource "oci_core_image" "gateway" {
  compartment_id = var.compartment_id
  display_name   = "gateway-${substr(var.source_revision, 0, 12)}"
  instance_id    = var.builder_instance_id
  freeform_tags = {
    event                 = "finals-2026"
    image_source_revision = var.source_revision
    managed_by            = "terraform"
    purpose               = "gateway"
  }

  lifecycle {
    prevent_destroy = true

    precondition {
      condition     = data.oci_core_instance.builder.state == "STOPPED"
      error_message = "The gateway image builder must finish testing and stop before capture."
    }

    precondition {
      condition = (
        data.oci_core_instance.builder.compartment_id == var.compartment_id &&
        lookup(data.oci_core_instance.builder.freeform_tags, "image_source_revision", "") == var.source_revision
      )
      error_message = "The builder compartment and source revision must match the capture request."
    }
  }

  timeouts {
    create = "90m"
  }
}
