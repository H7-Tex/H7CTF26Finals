# OCI foundation stack

This root creates the dedicated finals compartment, its S$325 monthly budget with S$175/250/300/315 actual-spend alerts, the two-block VCN, gateways, base route tables, NSGs, and 36 subnets. OCI evaluates budgets in the customer's rate-card currency; subscription `100001000231795` is denominated in SGD with S$400 of Universal Credits through 31 October 2026. It runs in OCI Resource Manager and therefore has no backend block or committed OCI credentials. Supply `budget_alert_recipients` only as an untracked Resource Manager variable.

The first apply leaves `routing_private_ip_id` null. After ingress exists, set it to the ingress stack's `routing_private_ip_id` output and review a second foundation plan. That plan adds static routes for both native VCN blocks to the service, mirror and isolated route tables. OCI prioritizes these matching static routes over its implicit local routes, forcing inter-subnet traffic through the floating gateway private IP without coupling the initial foundation and ingress applies.

The isolated route table has no internet default route. Operations commissioning can temporarily use `enable_service_warmup_egress`, and cache seeding can temporarily use `enable_mirror_warmup_egress`; both safe defaults are `false`. Each warm-up change must be followed by a reviewed plan back to `false` and an on-host no-egress test before rehearsal. The mirror also has a separate host-firewall mode gate, so both the route and `finals-mirror-mode offline` must be closed.

Before the first plan, verify the stack identity is the Sahalmn tenancy in `ap-hyderabad-1`, confirm the Console credit/rate gate, and compare the plan counts against the Terraform build plan.
