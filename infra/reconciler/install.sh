#!/usr/bin/env bash
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "must run as root" >&2; exit 1; }
root=${1:-/}
source_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

for command in python3 ssh systemctl systemd-sysusers; do
  command -v "$command" >/dev/null || { echo "missing reconciler dependency: $command" >&2; exit 1; }
done

cp -a "$source_dir/rootfs/." "$root/"
install -D -m 0755 \
  "$source_dir/rootfs/usr/local/libexec/peer-reconciler/reconcile.py" \
  "$root/usr/local/libexec/peer-reconciler/reconcile.py"
systemd-sysusers --root="$root"

if [[ $root == / ]]; then
  install -d -m 0750 -o root -g peer-reconciler /etc/peer-reconciler
  install -d -m 0700 -o peer-reconciler -g peer-reconciler /var/lib/peer-reconciler
  systemctl daemon-reload
fi
