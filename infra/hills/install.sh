#!/usr/bin/env bash
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "must run as root" >&2; exit 1; }
root=${1:-/}
source_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

install -D -o root -g root -m 0755 "$source_dir/credential_sync.py" "$root/usr/local/sbin/finals-hill-credentials"
install -D -o root -g root -m 0644 "$source_dir/credentials.compose.yaml" "$root/etc/finals-hill/credentials.compose.yaml"
install -D -o root -g root -m 0644 "$source_dir/finals-hill-credentials.service" "$root/etc/systemd/system/finals-hill-credentials.service"
install -D -o root -g root -m 0644 "$source_dir/finals-hill.conf" "$root/usr/lib/tmpfiles.d/finals-hill.conf"

if [[ $root == / ]]; then
  systemd-tmpfiles --create /usr/lib/tmpfiles.d/finals-hill.conf
  systemctl daemon-reload
  systemctl disable finals-hill-credentials.service >/dev/null 2>&1 || true
fi
