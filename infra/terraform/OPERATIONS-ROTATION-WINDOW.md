# Operations rotation window

This temporary reviewed window permits replacement of only the stateless operations host at its fixed private address `10.60.200.5`. The replacement keeps the current reviewed AArch64 image and receives a narrow cloud-init commissioning wrapper because the existing instance predates the fixed Run Command sudo matrix.

The saved plan must replace only `module.platform.oci_core_instance.host["operations"]`. It must not change or destroy platform, control, repository, mirror, Hill, gateway, public-address, volume, backup, network or fleet resources. Close this window and restore the instance deletion guard immediately after the replacement host recipient, relay commissioning and fixed volume recovery actions pass.
