# OCI production fleet

This Resource Manager root owns 16 isolated production hosts, including the organizer reference host, 15 team workbenches, one organizer workbench and one unassigned hot spare. Each production host also receives the fixed `.3` staging address used by the Deployment Gate.

Only organizer break-glass keys are installed on production hosts. Each team workbench receives the organizer key and that team's public keys. The organizer and spare workbenches remain organizer-only until the spare is explicitly reassigned. The root requires reviewed immutable production and workbench image OCIDs; it never resolves a mutable base image.

Apply only an exact saved plan from a reviewed commit. Set `production_numbers = [16]` and `workbench_numbers = [16, 17]` for the NOP and support canary, then add team 01 and expand both sets monotonically in reviewed batches. Never remove an applied number: deletion guards intentionally reject a shrinking rollout. The final full-fleet plan has 33 instances, 16 staging private addresses, 16 production data volumes and 16 production volume attachments with no replacements or deletes.

When expanding teams on a newer reviewed image while preserving the existing reference host, set `reference_production_image_id` to production-16's current immutable image. Leave it null when all production hosts use `production_image_id`.

Staging private addresses ignore provider refresh churn on `vnic_id`. New addresses still consume the VNIC at creation, while existing production instances and staging addresses are both protected from replacement by `prevent_destroy`.
