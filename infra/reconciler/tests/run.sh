#!/usr/bin/env bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

RECONCILER_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
bash -n "$RECONCILER_DIR/install.sh" "$RECONCILER_DIR/tests/run.sh"
grep -Fq '../images/router/rootfs/usr/local/libexec/event-router/render_inventory.py' "$RECONCILER_DIR/install.sh"
grep -Fq 'usr/local/libexec/event-router/render_inventory.py' "$RECONCILER_DIR/install.sh"
test -x "$RECONCILER_DIR/../images/router/rootfs/usr/local/libexec/event-router/render_inventory.py"
python3 -m unittest discover -s "$RECONCILER_DIR/tests" -p 'test_*.py'
