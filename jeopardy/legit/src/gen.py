#!/usr/bin/env python3
# generator for keymaster.c. not shipped. single source of truth for the
# embedded TARGET array and the encrypted flag blob. edit the knobs, run,
# then build with build.sh.

KEY = b"TR5P9WQ2K7MX4JD6"          # 16 license chars -> shown as TR5P-9WQ2-K7MX-4JD6
FLAG = b"H7CTF{f3c5ef9deeacfbbd7c75939a2d478e04}"
SEED = 0x5A

SCHED = [0x3f,0xa1,0x5c,0x08,0xd7,0x62,0x9e,0x4b,
         0x11,0xf0,0x7a,0x2d,0xc4,0x86,0x53,0xb9]
ADDK  = [0x17,0x2c,0x41,0x6d,0x05,0x8a,0x3b,0x9f,
         0x50,0xe2,0x74,0x18,0xa6,0x33,0xcf,0x61]

assert len(KEY) == 16 and len(SCHED) == 16 and len(ADDK) == 16

def rol8(x, r):
    r &= 7
    return ((x << r) | (x >> (8 - r))) & 0xff

# forward transform: cbc-style feedback chain, four ops per byte
target = []
acc = SEED
for i in range(16):
    c = KEY[i]
    c ^= SCHED[i]
    c = rol8(c, i & 7)
    c = (c + ADDK[i]) & 0xff
    c ^= acc
    target.append(c)
    acc = c

# flag blob: xor with keystream derived from the license bytes
blob = []
for j in range(len(FLAG)):
    ks = KEY[j & 15] ^ ((j * 0x0b + 0x37) & 0xff)
    blob.append(FLAG[j] ^ ks)

def carr(name, vals):
    body = ",".join("0x%02x" % v for v in vals)
    return "static const unsigned char %s[%d] = {%s};" % (name, len(vals), body)

src = '''#include <stdio.h>
#include <string.h>

%s
%s
%s
%s
static const unsigned int BLOB_LEN = %d;

static unsigned char rol8(unsigned char x, int r)
{
    r &= 7;
    return (unsigned char)((x << r) | (x >> (8 - r)));
}

int main(int argc, char **argv)
{
    char buf[128];
    const char *in;

    if (argc >= 2) {
        in = argv[1];
    } else {
        fputs("key: ", stdout);
        fflush(stdout);
        if (!fgets(buf, sizeof(buf), stdin)) {
            puts("no key");
            return 1;
        }
        buf[strcspn(buf, "\\r\\n")] = 0;
        in = buf;
    }

    if (strlen(in) != 19 || in[4] != '-' || in[9] != '-' || in[14] != '-') {
        puts("license rejected");
        return 1;
    }

    unsigned char key[16];
    int k = 0;
    for (int i = 0; i < 19; i++) {
        if (i == 4 || i == 9 || i == 14)
            continue;
        key[k++] = (unsigned char)in[i];
    }

    unsigned char out[16];
    unsigned char acc = 0x5a;
    for (int i = 0; i < 16; i++) {
        unsigned char c = key[i];
        c ^= SCHED[i];
        c = rol8(c, i & 7);
        c = (unsigned char)(c + ADDK[i]);
        c ^= acc;
        out[i] = c;
        acc = c;
    }

    unsigned char diff = 0;
    for (int i = 0; i < 16; i++)
        diff |= (unsigned char)(out[i] ^ TARGET[i]);
    if (diff) {
        puts("license rejected");
        return 1;
    }

    unsigned char flag[80];
    for (unsigned int j = 0; j < BLOB_LEN; j++) {
        unsigned char ks = (unsigned char)(key[j & 15] ^ (unsigned char)(j * 0x0b + 0x37));
        flag[j] = (unsigned char)(BLOB[j] ^ ks);
    }
    flag[BLOB_LEN] = 0;

    puts("license accepted");
    printf("%%s\\n", flag);
    return 0;
}
''' % (
    carr("SCHED", SCHED),
    carr("ADDK", ADDK),
    carr("TARGET", target),
    carr("BLOB", blob),
    len(blob),
)

import os
here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(here, "keymaster.c"), "w") as f:
    f.write(src)

print("wrote keymaster.c")
print("license key:", "-".join([KEY[i:i+4].decode() for i in range(0, 16, 4)]))
print("TARGET:", " ".join("%02x" % v for v in target))
print("BLOB:  ", " ".join("%02x" % v for v in blob))
