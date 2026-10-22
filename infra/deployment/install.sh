#!/usr/bin/env bash
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "must run as root" >&2; exit 1; }
[[ $# -ge 1 && $# -le 2 ]] || { echo "usage: install.sh BINARY [ROOT]" >&2; exit 1; }

binary=$1
root=${2:-/}
source_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

[[ -f $binary && -x $binary ]] || { echo "binary is not executable: $binary" >&2; exit 1; }
for command in install cp systemd-sysusers systemd-tmpfiles systemctl; do
  command -v "$command" >/dev/null || { echo "missing dependency: $command" >&2; exit 1; }
done

cp -a "$source_dir/rootfs/." "$root/"
install -D -m 0755 "$binary" "$root/usr/local/bin/deployment-orchestrator"
systemd-sysusers --root="$root"

if [[ $root == / ]]; then
  systemd-tmpfiles --create /usr/lib/tmpfiles.d/deployment-orchestrator.conf
  systemctl daemon-reload
fi
