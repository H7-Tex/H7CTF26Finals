# OCI runtime image capture

This Resource Manager stack captures the four stopped, tested runtime builders as protected custom images. Planning fails unless every builder belongs to the finals compartment and carries the requested role and full source revision.

Feed the resulting `platform-x86` and `platform-arm` OCIDs to the platform stack, and the `production` and `workbench` OCIDs to the fleet stack. Keep this state for the event lifetime; image teardown requires a separate reviewed change that removes the deletion guards.
