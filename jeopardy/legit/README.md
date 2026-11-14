# Totally Legit

**Category:** rev  **Difficulty:** medium  **Author:** abu

> We seized an activation tool from a vendor that sold more licenses than it ever owned. It stays quiet until you hand it a key it approves of, and the sales rep who kept the keys is no longer taking calls.
>
> Produce one it accepts and recover what it has been sitting on.

Handout: `totally-legit.zip` (contains the stripped `keymaster` binary). Source is in `src/`, rebuild with `src/build.sh`.

## Solution

The binary takes a key as an argument and prints `license rejected` for anything wrong. The flag isn't in the binary as plaintext.

The first check is the format: `XXXX-XXXX-XXXX-XXXX`, with dashes at index 4, 9 and 14. The 16 characters between them are the actual license.

Each of those 16 bytes goes through a small feedback chain:

```
c ^= SCHED[i]
c  = rol8(c, i & 7)
c += ADDK[i]
c ^= acc        # acc = 0x5a for byte 0, then the previous output byte
```

and the output is compared against a 16-byte `TARGET`. `SCHED`, `ADDK` and `TARGET` all sit in `.rodata`.

It looks like a chained check, but since `acc` at step i is just `TARGET[i-1]`, every byte can be inverted on its own. Undo each op in reverse (xor, subtract, rotate right, xor) and you get the key with no solver needed:

```
TR5P-9WQ2-K7MX-4JD6
```

With a valid key the tool XORs an embedded blob with `key[j & 15] ^ (j*0x0b + 0x37)` and prints the flag.

```
$ python3 solve.py
key  : TR5P-9WQ2-K7MX-4JD6
flag : H7CTF{f3c5ef9deeacfbbd7c75939a2d478e04}
```

`solve.py` pulls the tables straight from the ELF, inverts them, and runs the binary to confirm.

Flag: `H7CTF{f3c5ef9deeacfbbd7c75939a2d478e04}`
