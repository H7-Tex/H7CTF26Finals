#!/usr/bin/env bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

secret_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
bash -n "$secret_dir/finals-secret-relay-receive" "$secret_dir/tests/test_relay_receiver.sh"
"$secret_dir/tests/test_relay_receiver.sh"
python3 -m unittest discover -s "$secret_dir/tests" -p 'test_*.py'
python3 -c 'import ast, pathlib, sys; ast.parse(pathlib.Path(sys.argv[1]).read_text())' \
  "$secret_dir/install-secret-bundle.py"
grep -Fq 'Path("/etc/ssh/ssh_host_ed25519_key")' "$secret_dir/install-secret-bundle.py"
! grep -Eq 'extractall|tarfile|destination[[:space:]]*=' "$secret_dir/install-secret-bundle.py"
