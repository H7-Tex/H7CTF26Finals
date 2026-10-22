# OCI production platform

This Resource Manager root owns the eight private shared platform hosts and four durable data volumes. Gateways remain in the independent ingress stack; the 31 team hosts remain in the independent fleet stack.

The root requires reviewed immutable x86_64 and AArch64 image OCIDs. Do not substitute a mutable operating-system image lookup. Runtime secrets are installed after provisioning by the audited bootstrap process and never enter Terraform state.

Apply only an exact saved plan from a reviewed commit. The expected first plan is eight instances, four block volumes and four attachments with no replacements or deletes.
