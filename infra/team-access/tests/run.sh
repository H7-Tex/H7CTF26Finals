#!/usr/bin/env bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cache=$(mktemp -d)
trap 'rm -rf -- "$cache"' EXIT
python3 -m unittest discover -s "$root/tests" -p 'test_*.py'
PYTHONPYCACHEPREFIX=$cache python3 -m py_compile "$root/team-access.py"
bash -n "$root/install.sh" "$root/tests/run.sh"
grep -Fxq 'ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-team-access apply' "$root/install.sh"
grep -Fxq 'ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-team-access rollback' "$root/install.sh"
