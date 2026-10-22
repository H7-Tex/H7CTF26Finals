# OCI production fleet

This Resource Manager root owns 16 isolated production hosts, including the organizer reference host, and 15 team workbenches. Each production host also receives the fixed `.3` staging address used by the Deployment Gate.

Only organizer break-glass keys are installed on production hosts. Each workbench receives the organizer key and that team's public keys. The root requires reviewed immutable production and workbench image OCIDs; it never resolves a mutable base image.

Apply only an exact saved plan from a reviewed commit. Set `production_numbers = [16]` and `workbench_numbers = []` for the NOP canary, then add team 01 and expand both sets monotonically in reviewed batches. Never remove an applied number: deletion guards intentionally reject a shrinking rollout. The final full-fleet plan has 31 instances, 16 staging private addresses, 16 production data volumes and 16 production volume attachments with no replacements or deletes.
