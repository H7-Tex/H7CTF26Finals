#include <stdio.h>
#include <string.h>

static const unsigned char SCHED[16] = {0x3f,0xa1,0x5c,0x08,0xd7,0x62,0x9e,0x4b,0x11,0xf0,0x7a,0x2d,0xc4,0x86,0x53,0xb9};
static const unsigned char ADDK[16] = {0x17,0x2c,0x41,0x6d,0x05,0x8a,0x3b,0x9f,0x50,0xe2,0x74,0x18,0xa6,0x33,0xcf,0x61};
static const unsigned char TARGET[16] = {0xd8,0xcb,0x2d,0x02,0xf1,0xc1,0xef,0xb4,0x1e,0x6f,0x3f,0xfc,0x49,0x85,0x11,0x39};
static const unsigned char BLOB[39] = {0x2b,0x27,0x3b,0x5c,0x1c,0x42,0x4e,0x85,0xa7,0x98,0x8d,0x8e,0xb6,0xe8,0xf0,0x8f,0xd2,0xc3,0xae,0x3a,0x48,0x2d,0x4f,0x65,0x43,0x48,0x21,0x0b,0x66,0x5d,0xf7,0xde,0xf7,0xc7,0xa0,0x8d,0xca,0xad,0xf5};
static const unsigned int BLOB_LEN = 39;

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
        buf[strcspn(buf, "\r\n")] = 0;
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
    printf("%s\n", flag);
    return 0;
}
