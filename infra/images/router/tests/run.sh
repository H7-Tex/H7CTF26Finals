#!/usr/bin/env bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)

bash -n \
  "$ROOT/infra/images/router/install.sh" \
  "$ROOT/infra/images/router/rootfs/usr/local/sbin/event-router-addresses" \
  "$ROOT/infra/images/router/rootfs/usr/local/sbin/event-router-apply-inventory" \
  "$ROOT/infra/images/router/tests/network_namespace.sh"
python3 -m unittest discover -s "$ROOT/infra/images/router/tests" -p 'test_*.py'
"$ROOT/infra/images/router/tests/network_namespace.sh"
