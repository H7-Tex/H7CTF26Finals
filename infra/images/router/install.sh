#!/usr/bin/env bash
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "must run as root" >&2; exit 1; }
root=${1:-/}
source_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

for command in age nft ip wg conntrack python3 sshd ssh-keygen sudo systemd-sysusers; do
  command -v "$command" >/dev/null || { echo "missing image dependency: $command" >&2; exit 1; }
done

cp -a "$source_dir/rootfs/." "$root/"
chmod 0755 \
  "$root/usr/local/sbin/event-router-addresses" \
  "$root/usr/local/sbin/event-router-activate" \
  "$root/usr/local/sbin/event-router-apply-inventory" \
  "$root/usr/local/sbin/event-router-authorize-reconciler" \
  "$root/usr/local/sbin/event-router-capture" \
  "$root/usr/local/sbin/event-router-receive-inventory" \
  "$root/usr/local/sbin/event-router-initialize" \
  "$root/usr/local/sbin/event-router-restore" \
  "$root/usr/local/libexec/event-router/render_inventory.py"
chmod 0440 "$root/etc/sudoers.d/peer-reconciler"
install -d -m 0700 "$root/etc/event-router" "$root/etc/wireguard" "$root/var/lib/event-router"
systemd-sysusers --root="$root"
systemctl --root="$root" enable nftables.service systemd-timesyncd.service event-router.target
