# Challenge integration gate

Run the closed static contract gate before building staging images:

```text
infra/integration/run.sh /path/to/H7CTF26Finals-challenges
```

It requires Docker Compose for canonical Compose rendering. The gate compares all six private AD manifests to the checker and deployment contracts, including identity, ports, stores, checker schema, patch paths, runtime limits, quotas, lifecycle generations, pinned build inputs and private attack/patch fixtures. It also validates the three five-door Hill manifests and their process-scoped file-secret boundaries after the platform credential override is applied.

A green result proves that the two repositories agree statically. It does not replace immutable image creation, secret delivery, controller commissioning, real ingress, promotion and rollback, load, soak, recovery or the closed player-journey rehearsal.
