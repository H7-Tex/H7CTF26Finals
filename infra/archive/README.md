# OCI-to-GCP archive transport

This is a post-event archive path, never a scoring dependency. It exchanges the source OCI instance's two-hour instance-identity certificate for a short-lived Google token, writes content-addressed objects with a create-only generation precondition, verifies Cloud Storage's MD5 and custom SHA-256 metadata, and leaves a root-only receipt. No Google service-account key exists.

The Terraform trust is narrower than the regional OCI CA: the X.509 provider accepts only the reviewed instance OCIDs, and each bucket grants only its source identity object create/read. Sources cannot overwrite or delete objects. The operations identity has read-only access to all four buckets for a recovery drill. Replacing any source instance changes its certificate subject and intentionally stops archive access until a reviewed Terraform update.

Official trust references:

- [Google X.509 workload federation](https://cloud.google.com/iam/docs/workload-identity-federation-with-x509-certificates)
- [OCI instance identity root retrieval](https://docs.oracle.com/en-us/iaas/Content/Identity/defaultsettings/overview-retrieve-instance-identity-root-ca-certificate.htm)
- [Cloud Storage generation preconditions](https://cloud.google.com/storage/docs/request-preconditions)
- [Cloud Storage write checksum validation](https://cloud.google.com/storage/docs/data-validation)

## Commissioning

Immediately before the reviewed GCP plan, retrieve the current Hyderabad root set through an authenticated OCI request and convert each returned DER value to PEM. Supply the PEM list only through an ignored `.tfvars` file. Also supply the current instance OCIDs for platform, repository, active gateway and operations. A root refresh or instance replacement requires a new reviewed plan.

Keep source artifacts split into immutable files no larger than 8 GiB. The expected source roots are `/srv/anvil/backups` for database and score exports, `/srv/gitea/backups` for an offline Gitea archive, and `/srv/captures` for stopped capture segments. Preparation is deliberately separate: stop the writer, produce its native verified backup or export, and preserve its own manifest/checksums before upload.

After every owning service is stopped, apply a separately reviewed `oci-foundation` plan with `enable_service_warmup_egress=true`. This restores the service-subnet NAT route used during commissioning; host firewalls still keep public egress closed except for operations and an explicitly opened archive window. Do not open the route during play.

On platform, repository or the active gateway, stop the owning service and open the fail-closed HTTPS window. The window permits OCI IMDSv2 HTTP only to `169.254.169.254` and public TCP 443, and its `/run` marker disappears on reboot. For the gateway, stop `event-router.target`, `event-router-flow-log.service`, `event-router-activate.service` and `event-router-inventory.path`; enabling archive egress empties the forwarding gate, removes every gameplay address, then restores only the public-web private address as the upload source. Incoming traffic remains blocked by the empty forwarding gate:

```bash
sudo finals-archive-egress enable
sudo finals-archive upload database /srv/anvil/backups/FINAL/database.dump
sudo finals-archive-egress disable
```

Use `scores`, `gitea` or `pcaps` only on its fixed source host. Always disable egress after the batch. The marker is under `/run`, so reboot closes the window. The gateway additionally requires capture and the event router target to be stopped.

On operations, verify metadata or perform a byte-for-byte recovery download without overwrite:

```bash
sudo finals-archive-egress enable
sudo finals-archive verify database SHA256
sudo install -d -o root -g root -m 0700 /srv/finals-archive/restore
sudo finals-archive download database SHA256 /srv/finals-archive/restore/database.dump
sudo finals-archive-egress disable
```

The bucket retention policy is 30 days and intentionally unlocked until the pre-event upload/download drill passes. Locking is irreversible; lock it only as a separate reviewed production decision. Bucket versioning and `prevent_destroy` remain enabled.

After all uploads and recovery checks, disable every archive window, apply a reviewed `oci-foundation` plan with `enable_service_warmup_egress=false`, and prove the service route table again has no `0.0.0.0/0` route. Keep services stopped until that proof is recorded.

## Required evidence

For every purpose, retain the local receipt, object generation, source-native checksum manifest, successful operations-host verification, and at least one download whose SHA-256 matches its content-addressed name. GCP is recovery/archive capacity only; OCI remains authoritative during play.
