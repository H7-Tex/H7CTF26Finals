#!/usr/bin/env python3
# invert the keygen chain out of the stripped elf, then confirm against the binary
import struct, subprocess, sys, os

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.join(HERE, "keymaster")
SEED = 0x5a
BLOB, ADDK, SCHED, TARGET = 0x2040, 0x2070, 0x2080, 0x2090


def rodata(path):
    data = open(path, "rb").read()
    shoff, shent, shnum, shstr = (struct.unpack_from(f, data, o)[0]
        for f, o in (("<Q", 0x28), ("<H", 0x3a), ("<H", 0x3c), ("<H", 0x3e)))
    sh = lambda i: struct.unpack_from("<IIQQQQ", data, shoff + i * shent)
    stroff = sh(shstr)[4]
    for i in range(shnum):
        name, _, _, addr, off, size = sh(i)
        if data[stroff + name:data.index(b"\x00", stroff + name)] == b".rodata":
            return lambda va, n: data[off + va - addr: off + va - addr + n]
    raise RuntimeError(".rodata not found")


def ror8(x, r):
    r &= 7
    return ((x >> r) | (x << (8 - r))) & 0xff


read = rodata(BIN)
sched, addk, target = read(SCHED, 16), read(ADDK, 16), read(TARGET, 16)
blob = read(BLOB, ADDK - BLOB)

# chain: out[i] = ((rol8(key[i]^sched[i], i) + addk[i]) ^ acc), acc = out[i-1] (SEED at 0)
key = bytearray(16)
for i in range(16):
    c = target[i] ^ (SEED if i == 0 else target[i - 1])
    c = ror8((c - addk[i]) & 0xff, i)
    key[i] = c ^ sched[i]
key_str = "-".join(key[j:j + 4].decode() for j in range(0, 16, 4))

dec = bytes(blob[j] ^ key[j & 15] ^ ((j * 0x0b + 0x37) & 0xff) for j in range(len(blob)))
flag = dec[:dec.index(ord("}")) + 1].decode()

run = subprocess.run([BIN, key_str], capture_output=True, text=True).stdout.strip()
print("key  :", key_str)
print("flag :", flag)
print("binary:", run.splitlines()[-1])
expected = open(os.path.join(HERE, "flag.txt")).read().strip()
ok = flag == run.splitlines()[-1] == expected
print("match:", ok)
sys.exit(0 if ok else 1)
