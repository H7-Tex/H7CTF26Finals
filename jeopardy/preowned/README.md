# Certified Pre-Owned

**Category:** crypto  **Difficulty:** medium  **Author:** abu

> A custody desk retired one of its offline transaction-signing appliances and pulled the device's audit log before the unit went back to the vendor for a wipe. The datasheet calls the signing module tamper-proof and field-certified, and every withdrawal in the log checks out against the device key.
>
> The appliance is gone. Its paperwork is not, and it still answers to the keys it was built to protect.

Handout: `certified-pre-owned.zip` (contains `cs7_audit_export.json`)

## Solution

The export is a JSON audit log from the appliance: the secp256k1 public key, a list of signed withdrawal records, and a `recovery_secret` envelope encrypted with AES-256-GCM. The envelope note even tells you the key is `SHA256(private_key)`, so the whole challenge is getting `d`.

Every signature is ECDSA over SHA-256 of the `message` string. When we grouped the records by `r`, seq 101 and seq 104 had the same value. Same `r` means the appliance used the same nonce `k` twice, and that's game over for ECDSA.

With `z = SHA256(message) mod n` for both messages:

```
k = (z1 - z2) / (s1 - s2)  mod n
d = (s1*k - z1) / r        mod n
```

`d*G` matches the published `Qx`, so the key is right. Then the envelope key is `SHA256(d as 32 big-endian bytes)` and AES-GCM decrypting `ciphertext` with the given `iv` and `tag` gives the flag.

```
$ python3 solve.py certified-pre-owned.zip
reused r on seq 101 / 104
d = 0xde88f605b8aaf7a655b06a7af2427923b2f9c401aeba90c95115de240b7833c4
H7CTF{9c89c6a49f992e4931a88a3b89546228}
```

`solve.py` needs `pycryptodome` and `ecdsa`.

Flag: `H7CTF{9c89c6a49f992e4931a88a3b89546228}`
