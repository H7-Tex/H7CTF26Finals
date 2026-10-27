# Totally Legit (rev, 300) - staff TLDR

- Input must be `XXXX-XXXX-XXXX-XXXX` (dashes at index 4/9/14); the 16 inner chars are the license.
- A feedback chain runs over the 16 bytes, four ops each: `c ^= SCHED[i]; c = rol8(c, i&7); c += ADDK[i]; c ^= acc` where `acc` is seed `0x5a` for byte 0 and the previous output byte after that. The result is compared to the embedded `TARGET`.
- Each op inverts trivially and `acc` at step i is just `TARGET[i-1]`, so read `SCHED`/`ADDK`/`TARGET` from `.rodata` and invert by hand (no solver). Valid key: `TR5P-9WQ2-K7MX-4JD6`.
- On a match the tool XORs an embedded blob with keystream `key[j&15] ^ (j*0x0b + 0x37)` to print the flag; wrong keys print `license rejected` and the flag is never in the binary as plaintext.
- `solve.py` extracts the tables from the ELF, inverts to the key, derives the flag, and confirms by running the binary. Flag: `H7CTF{f3c5ef9deeacfbbd7c75939a2d478e04}`.
