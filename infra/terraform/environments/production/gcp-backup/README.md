# GCP archive

This root owns the four private archive buckets, their 30-day unlocked retention policy, and a keyless X.509 workload identity pool. It does not run a service and is not on the scoring path.

Before planning, collect the current OCI Hyderabad instance-identity root set from the authenticated OCI endpoint and the exact instance OCIDs for platform, repository, the active gateway and operations. Put them in an ignored tfvars file based on `terraform.tfvars.example`. Database and scores bind to platform, Gitea binds to repository, captures bind to the active gateway, and operations receives read-only recovery access.

Review a plan expecting API enablement, one workload identity pool/provider, additive bucket IAM members and in-place bucket retention updates. It must contain no service account, key, bucket replacement or destroy. The 30-day policy remains unlocked until the upload, verify and download rehearsal passes because locking it is irreversible.

See [the transport runbook](../../../../archive/README.md) for the host workflow and remaining artifact-preparation inputs.

The GCP root does not add an OCI route. Post-event transfer also requires a separately reviewed, temporary `oci-foundation` change to `enable_service_warmup_egress=true`; turn it off and verify route removal before restarting any event service.
