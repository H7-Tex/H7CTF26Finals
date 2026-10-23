#!/usr/bin/env bash
set -euo pipefail

integration_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
challenge_root=${1:-}
[[ -n $challenge_root ]] || { echo "usage: $0 CHALLENGE_ROOT" >&2; exit 2; }

python3 -m py_compile "$integration_dir/validate-challenge-contract.py"
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s "$integration_dir/tests" -p 'test_*.py'
python3 "$integration_dir/validate-challenge-contract.py" "$challenge_root"
