# OCI production platform

This Resource Manager root owns the eight private shared platform hosts, four durable data volumes and the database backup policy. Gateways remain in the independent ingress stack; the 31 team hosts remain in the independent fleet stack.

The root requires reviewed immutable x86_64 and AArch64 image OCIDs. Do not substitute a mutable operating-system image lookup. Supply organizer break-glass public key lines through `organizer_ssh_authorized_keys` and one raw event-only Ed25519 relay key through `operations_relay_ssh_public_key`; never supply either private half. Terraform installs the relay key only on platform, control and repository with a fixed forced command, while operations, mirror and hills receive organizer keys only. Each fixed role receives committed minimal cloud-init that regenerates a unique Ed25519 host key, prints its recipient and fingerprint to console history, applies its host firewall and invokes only its idempotent fixed-role activation. There is no blank or free-form role map. Runtime secrets are installed after provisioning by the audited age bootstrap and never enter Terraform state or user data.

The database volume receives an incremental backup every hour at 15 minutes past the hour. Each recovery point is retained for seven days. The deployment gate includes a restore into a disposable validation volume before the event; creating backups alone does not prove recovery.

Apply only an exact saved plan from a reviewed commit. The expected first plan is eight instances, four block volumes, four attachments, one backup policy and one policy assignment with no replacements or deletes.
