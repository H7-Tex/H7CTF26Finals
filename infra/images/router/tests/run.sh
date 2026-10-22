#!/usr/bin/env bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

ROUTER_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

bash -n \
  "$ROUTER_DIR/build-image" \
  "$ROUTER_DIR/install.sh" \
  "$ROUTER_DIR/rootfs/usr/local/sbin/event-router-addresses" \
  "$ROUTER_DIR/rootfs/usr/local/sbin/event-router-apply-inventory" \
  "$ROUTER_DIR/seal-image" \
  "$ROUTER_DIR/tests/network_namespace.sh"
python3 -m unittest discover -s "$ROUTER_DIR/tests" -p 'test_*.py'
"$ROUTER_DIR/tests/network_namespace.sh"
