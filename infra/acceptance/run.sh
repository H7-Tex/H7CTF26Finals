#!/usr/bin/env bash
set -euo pipefail

acceptance_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
evidence=${1:-}
[[ -n $evidence ]] || { echo "usage: $0 EVIDENCE.json" >&2; exit 2; }

python3 -m py_compile "$acceptance_dir/validate-evidence.py"
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s "$acceptance_dir/tests" -p 'test_*.py'
python3 "$acceptance_dir/validate-evidence.py" "$evidence"
