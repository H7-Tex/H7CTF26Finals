# OCI gateway image builder

This temporary Resource Manager stack creates one outbound-only E4 Flex builder in the public edge subnet. It runs inventory and network-namespace tests, removes build state and SSH host keys, resets cloud-init identity and powers off.

The fixed-path build payload lives in one transient no-public-access Object Storage object. Its object-read PAR has an explicit reviewed RFC3339 expiry no more than 24 hours away. Instance metadata contains only the PAR, exact byte length and SHA-256 plus a small bounded downloader, and Terraform asserts that encoded user data remains below 16 KiB. The verified payload writes only Terraform-generated repository paths and invokes the builder directly; it never recursively invokes cloud-init. No GitHub credential or private repository token is used.

The builder has no ingress rule or SSH key. A stopped instance is the success signal; a running instance after the build window is a failed build and must not be captured. Use the separate `oci-gateway-image` stack to capture only the stopped, revision-tagged builder.

The first plan includes one private bucket, one object and one PAR in addition to the NSG, egress rule and builder. After the custom image is verified and consumed by ingress, destroy this temporary builder through a reviewed Resource Manager destroy plan; this also revokes the PAR and removes the source object.

The existing `gateway-5095652d3d90` image and the pending builder plan for source `11bdcffc06c9d4d0b6f08a58b0cf34e6f1aa0d1f` are prohibited for production. Replace that plan with a package from the exact clean current `main`; after the new builder passes and stops, capture it in a fresh Resource Manager stack named `router-image`.
