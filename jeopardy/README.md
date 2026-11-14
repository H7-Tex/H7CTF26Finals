# H7CTF 2026 Finals: Jeopardy

Two offline challenges that ran alongside the attack-defense finals. All medium, 300 points, flag format `H7CTF{32 lowercase hex}`. Each one is a single zip, no instance.

| Folder | Name | Category |
|---|---|---|
| [preowned](preowned) | Certified Pre-Owned | crypto |
| [legit](legit) | Totally Legit | rev |

Each folder has the handout zip, `challenge.yml`, `flag.txt`, a solver (`solve.py`) and its captured output (`solve_output.txt`). The writeup is in the folder's README.

Solver deps: `pycryptodome` and `ecdsa` for the crypto one. The rev one is stdlib only.
