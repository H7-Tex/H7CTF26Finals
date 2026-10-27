#!/usr/bin/env python3
# nonce reuse in the appliance log: two sigs share r -> same k -> recover d -> decrypt envelope
import sys, json, zipfile, hashlib
from Crypto.Cipher import AES
from ecdsa import SECP256k1

n = SECP256k1.order
G = SECP256k1.generator

path = sys.argv[1] if len(sys.argv) > 1 else "certified-pre-owned.zip"
if zipfile.is_zipfile(path):
    with zipfile.ZipFile(path) as z:
        data = json.loads(z.read(next(m for m in z.namelist() if m.endswith(".json"))))
else:
    data = json.load(open(path))

h = lambda m: int.from_bytes(hashlib.sha256(m.encode()).digest(), "big") % n

seen = {}
a = b = None
for rec in data["records"]:
    r = int(rec["signature"]["r"], 16)
    if r in seen:
        a, b = seen[r], rec
        break
    seen[r] = rec
assert a, "no reused r"

r = int(a["signature"]["r"], 16)
s1 = int(a["signature"]["s"], 16)
s2 = int(b["signature"]["s"], 16)
z1, z2 = h(a["message"]), h(b["message"])
print("reused r on seq %s / %s" % (a["seq"], b["seq"]))

# s = k^-1 (z + r d), so k = (z1-z2)/(s1-s2) and d = (s1 k - z1)/r
k = (z1 - z2) * pow(s1 - s2, -1, n) % n
d = (s1 * k - z1) * pow(r, -1, n) % n
assert (d * G).x() == int(data["public_key"]["Qx"], 16), "d does not match pubkey"
print("d =", hex(d))

key = hashlib.sha256(d.to_bytes(32, "big")).digest()
env = data["recovery_secret"]
pt = AES.new(key, AES.MODE_GCM, nonce=bytes.fromhex(env["iv"])).decrypt_and_verify(
    bytes.fromhex(env["ciphertext"]), bytes.fromhex(env["tag"]))
print(pt.decode())
