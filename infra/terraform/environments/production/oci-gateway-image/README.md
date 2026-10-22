# OCI gateway image capture

This Resource Manager stack captures the tested gateway builder as one immutable custom image. Planning fails unless the builder is stopped, belongs to the finals compartment and carries the requested full source revision.

The custom image has a Terraform deletion guard. Keep this stack and its state for the event lifetime; teardown requires a separately reviewed change that removes the guard.

The existing `gateway-5095652d3d90` image is topology evidence only and is prohibited as an ingress input. It predates the current router policy. Do not apply the pending builder plan for source `11bdcffc06c9d4d0b6f08a58b0cf34e6f1aa0d1f`, and do not update the protected evidence-image stack in place. Failed builder `ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goaceebogxa47rg74d6izhqorb2dgnjjlfsv7gupjwbevyva` is explicitly rejected by capture validation even if it is manually stopped. Build from the exact clean current `main`, verify that the builder stopped naturally with complete serial evidence, and capture it in a fresh Resource Manager stack named `router-image`.
