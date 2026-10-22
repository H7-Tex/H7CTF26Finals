# OCI gateway image builder

This temporary Resource Manager stack creates one outbound-only E4 Flex builder in the public edge subnet. Compressed cloud-init installs the gateway runtime directly from the reviewed repository bundle, runs its inventory and network-namespace tests, removes build state, resets cloud-init identity and powers off.

The builder has no ingress rule or SSH key. A stopped instance is the success signal; a running instance after the build window is a failed build and must not be captured. Use the separate `oci-gateway-image` stack to capture only the stopped, revision-tagged builder.

After the custom image is verified and consumed by ingress, destroy this temporary builder only through a reviewed Resource Manager destroy plan.
