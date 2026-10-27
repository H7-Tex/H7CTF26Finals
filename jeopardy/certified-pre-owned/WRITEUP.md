# Certified Pre-Owned - staff TLDR

ECDSA (secp256k1) nonce reuse in the appliance audit log.

1. Group the signed records by `r`. seq 101 and seq 104 share the same `r`, so the appliance signed both with the same nonce `k`.
2. With `z = SHA256(message) mod n`, recover `k = (z1 - z2) / (s1 - s2) mod n`, then `d = (s1*k - z1) / r mod n`. `d*G` matches the published public key `Q`.
3. Envelope key is `SHA256(d as 32 big-endian bytes)`. AES-256-GCM decrypt `ciphertext` with `iv`/`tag` for the flag.

No plaintext flag in the handout, only the encrypted blob. `solve.py` runs the whole thing off the zip.
