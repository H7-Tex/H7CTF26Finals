# OCI runtime image builders

This temporary Resource Manager stack creates four outbound-only builders in the public edge subnet. The builders accept no ingress or SSH key. Each installs and tests one runtime role from the reviewed repository revision, seals its state and powers off.

The exact first plan is one NSG, one egress rule and four builder instances with no replacements or deletes. A stopped instance is the success signal. Do not capture a running builder.
