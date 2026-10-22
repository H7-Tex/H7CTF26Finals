# OCI foundation stack

This root creates only the dedicated finals compartment, two-block VCN, gateways, base route tables, NSGs, and 36 subnets. It runs in OCI Resource Manager and therefore has no backend block or committed OCI credentials.

The isolated route table intentionally has no route rules. A later reviewed ingress/routing composition attaches game routes to the two-router design after the reserved web and VPN addresses exist. Do not run the legacy shell scripts in parallel with this stack.

The services subnet retains NAT egress for controlled platform operations. Mirror NAT egress is a separate route table controlled by `enable_mirror_warmup_egress`; its safe default is `false`. Any cache warm-up change must be followed by a reviewed plan back to `false` and an on-host no-egress test before rehearsal.

Before the first plan, verify the stack identity is the Sahalmn tenancy in `ap-hyderabad-1`, confirm the Console credit/rate gate, and compare the plan counts against the Terraform build plan.
