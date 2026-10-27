# H7CTF'26 Finals - Jeopardy (offline, static)

PRIVATE. Contains live-event flags and full solutions. Do not make this repo public or share it outside the team until after the event.

4 offline/static challenges. All medium, 300 points, flag format `H7CTF{32 lowercase hex}`. No VPN, no instance - each is a single downloadable zip solved on a laptop.

| folder | name | category |
|---|---|---|
| certified-pre-owned | Certified Pre-Owned | crypto |
| looks-clean-to-me | Looks Clean to Me | forensics |
| totally-legit | Totally Legit | rev |
| takeout | Takeout | misc |

Each folder has:
- `challenge.yml` - name, category, difficulty, description, points, static flag
- `<slug>.zip` - the player handout (what gets attached on the platform)
- `flag.txt` - the flag
- `solve.py` - reference solver
- `solve_output.txt` - a captured solver run
- `WRITEUP.md` - staff TLDR of the intended solve

## How to verify one

```sh
cd <folder>
python3 solve.py            # some accept: python3 solve.py <slug>.zip
# confirm it prints the flag in flag.txt
```

Deps a few solvers need: `pycryptodome` and `ecdsa` (crypto), `scapy` (forensics). The rev/misc solvers are standard library only.
