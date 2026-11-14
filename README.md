# H7CTF 2026 Finals

Everything we ran the H7CTF 2026 finals on, plus the two jeopardy challenges that went out with it.

- 24 hours of attack-defense, King of the Hill rounds running alongside
- 15 teams over a WireGuard VPN, `Anvil` as the scoreboard
- flags look like `H7CTF{32 lowercase hex}`
- quick fun fact: OCI Hyderabad carried the whole live event, GCP only ever saw state and archives

#### **Challenges**

- crypto
  - [Certified Pre-Owned](jeopardy/preowned) by `abu`
- rev
  - [Totally Legit](jeopardy/legit) by `abu`

both `medium`, 300 points, handout only (no instance needed).

#### **Layout**

each challenge folder is roughly:

```
challenge.yml     name, author, description, flag, handout
<name>.zip        what players got
solve.py          solver, solve_output.txt is what it printed
README.md         description and writeup
```

`legit` also ships the binary's source in `src/` (rebuild with `src/build.sh`).

#### **Solving**

```
cd jeopardy/preowned
pip install pycryptodome ecdsa
python3 solve.py certified-pre-owned.zip
```

```
cd jeopardy/legit
python3 solve.py
```

#### **Infra**

[infra/](infra) is the Terraform, images and host tooling we used for the event: OCI for the live boxes, GCP for state and post-event archives, Cloudflare for DNS. [infra/README.md](infra/README.md) has the layout, the network map and the order we brought things up in. CI that built the images and ran the Terraform checks lives in [.github/workflows/](.github/workflows).

nothing secret is committed (no state, no real `.tfvars`, no keys), the `*.example` files show the shape.

#### Post Credits

- last year's infra writeup: [H7CTF 2025 Infrastructure](https://www.abu.rocks/docs/dev/h7ctf25-infrastructure/)
- more writeups over at [abu.rocks](https://www.abu.rocks/)
