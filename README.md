`H7CTF 2026 Finals`

- quick fun fact: `OCI Hyderabad` carried the whole live event, GCP only ever saw state and archives

`legit` also ships the binary's source in `src/` (rebuild with `src/build.sh`).

[infra/](infra) is the terraform, images and host tooling we used for the event: OCI for the live boxes, GCP for state and post-event archives, cloudflare for DNS. [infra/README.md](infra/README.md) has the layout, the network map and the order we brought things up in. CI that built the images and ran the Terraform checks lives in [.github/workflows/](.github/workflows).

nothing secret is committed (no state, no real `.tfvars`, no keys), the `*.example` files show the shape.
