# OCI gateway image capture

This Resource Manager stack captures the tested gateway builder as one immutable custom image. Planning fails unless the builder is stopped, belongs to the finals compartment and carries the requested full source revision.

The custom image has a Terraform deletion guard. Keep this stack and its state for the event lifetime; teardown requires a separately reviewed change that removes the guard.
