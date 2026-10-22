#!/usr/bin/env bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

RECONCILER_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
bash -n "$RECONCILER_DIR/install.sh" "$RECONCILER_DIR/tests/run.sh"
python3 -m unittest discover -s "$RECONCILER_DIR/tests" -p 'test_*.py'
