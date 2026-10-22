#!/usr/bin/env bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

ROUTER_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

bash -n \
  "$ROUTER_DIR/build-image" \
  "$ROUTER_DIR/install.sh" \
  "$ROUTER_DIR/rootfs/usr/local/sbin/event-router-addresses" \
  "$ROUTER_DIR/rootfs/usr/local/sbin/event-router-activate" \
  "$ROUTER_DIR/rootfs/usr/local/sbin/event-router-apply-inventory" \
  "$ROUTER_DIR/rootfs/usr/local/sbin/event-router-authorize-reconciler" \
  "$ROUTER_DIR/rootfs/usr/local/sbin/event-router-capture" \
  "$ROUTER_DIR/rootfs/usr/local/sbin/event-router-initialize" \
  "$ROUTER_DIR/rootfs/usr/local/sbin/event-router-restore" \
  "$ROUTER_DIR/seal-image" \
  "$ROUTER_DIR/tests/restore.sh" \
  "$ROUTER_DIR/tests/network_namespace.sh"
python3 -m unittest discover -s "$ROUTER_DIR/tests" -p 'test_*.py'
grep -Fq 'rm -f /etc/ssh/ssh_host_*' "$ROUTER_DIR/seal-image"
grep -Fq "dpkg-query -W" "$ROUTER_DIR/seal-image"
grep -Fq 'package_manifest_sha256' "$ROUTER_DIR/seal-image"
grep -Fq 'ssh_deletekeys: true' "$ROUTER_DIR/cloud-init.yaml"
grep -Fq 'Before=event-router-flow-log.service event-router-activate.service event-router-inventory.path' "$ROUTER_DIR/rootfs/etc/systemd/system/event-router-restore.service"
grep -Fq 'Requires=event-router-restore.service event-router-flow-log.service' "$ROUTER_DIR/rootfs/etc/systemd/system/event-router-activate.service"
grep -Fq '[[ ! $inventory -ef $active_inventory ]]' "$ROUTER_DIR/rootfs/usr/local/sbin/event-router-apply-inventory"
grep -Fq 'RequiresMountsFor=/srv/captures' "$ROUTER_DIR/rootfs/etc/systemd/system/event-router-flow-log.service"
grep -Fq 'ExecStart=/usr/local/sbin/event-router-capture stream' "$ROUTER_DIR/rootfs/etc/systemd/system/event-router-flow-log.service"
"$ROUTER_DIR/tests/restore.sh"
"$ROUTER_DIR/tests/network_namespace.sh"
