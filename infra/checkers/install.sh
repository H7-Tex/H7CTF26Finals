#!/usr/bin/env bash
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "must run as root" >&2; exit 1; }
source_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

cp -a "$source_dir/rootfs/." /
chmod 0755 \
  /usr/local/libexec/checker-runtime/runtime.py \
  /usr/local/sbin/checker-runtime-commission
install -d -o root -g root -m 0700 \
  /etc/checker-runtime \
  /etc/finals-platform/checkers \
  /opt/finals-checkers \
  /run/checker-runtime \
  /var/lib/checker-runtime
systemctl daemon-reload
systemctl disable checker-runtime.service finals-checkers-ready.service >/dev/null 2>&1 || true
