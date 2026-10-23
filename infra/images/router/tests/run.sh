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
  "$ROUTER_DIR/rootfs/usr/local/sbin/event-router-challenge-access" \
  "$ROUTER_DIR/rootfs/usr/local/sbin/event-router-initialize" \
  "$ROUTER_DIR/rootfs/usr/local/sbin/event-router-restore" \
  "$ROUTER_DIR/seal-image" \
  "$ROUTER_DIR/tests/challenge_access.sh" \
  "$ROUTER_DIR/tests/restore.sh" \
  "$ROUTER_DIR/tests/network_namespace.sh"
python3 -m unittest discover -s "$ROUTER_DIR/tests" -p 'test_*.py'
grep -Fq 'rm -f /etc/ssh/ssh_host_*' "$ROUTER_DIR/seal-image"
grep -Fq "until apt-get -o DPkg::Lock::Timeout=10 clean" "$ROUTER_DIR/seal-image"
grep -Fq "timeout --signal=TERM --kill-after=5s 2m bash" "$ROUTER_DIR/seal-image"
grep -Fq "dpkg-query -W" "$ROUTER_DIR/seal-image"
grep -Fq 'package_manifest_sha256' "$ROUTER_DIR/seal-image"
grep -Fq 'mask apt-daily.service apt-daily-upgrade.service apt-daily.timer apt-daily-upgrade.timer update-notifier-download.service update-notifier-download.timer' "$ROUTER_DIR/install.sh"
grep -Fq 'ssh_deletekeys: true' "$ROUTER_DIR/cloud-init.yaml"
grep -Fq "permissions: '0644'" "$ROUTER_DIR/cloud-init.yaml"
grep -Fq '["install", "-d", "-m", "0755", "/run/sshd"]' "$ROUTER_DIR/cloud-init.yaml"
grep -Fq '["systemctl", "enable", "--now", "ssh.service"]' "$ROUTER_DIR/cloud-init.yaml"
grep -Fq 'Before=event-router-flow-log.service event-router-activate.service' "$ROUTER_DIR/rootfs/etc/systemd/system/event-router-restore.service"
! grep -Fq 'Before=event-router-inventory.path' "$ROUTER_DIR/rootfs/etc/systemd/system/event-router-restore.service"
grep -Fq 'After=nftables.service event-router-restore.service' "$ROUTER_DIR/rootfs/etc/systemd/system/event-router-inventory.service"
grep -Fq 'Requires=nftables.service event-router-restore.service' "$ROUTER_DIR/rootfs/etc/systemd/system/event-router-inventory.service"
grep -Fq 'Requires=event-router-restore.service event-router-flow-log.service' "$ROUTER_DIR/rootfs/etc/systemd/system/event-router-activate.service"
! grep -Fq 'Before=event-router-inventory.path' "$ROUTER_DIR/rootfs/etc/systemd/system/event-router-activate.service"
grep -Fq '[[ ! $inventory -ef $active_inventory ]]' "$ROUTER_DIR/rootfs/usr/local/sbin/event-router-apply-inventory"
grep -Fq 'RequiresMountsFor=/srv/captures' "$ROUTER_DIR/rootfs/etc/systemd/system/event-router-flow-log.service"
grep -Fq 'ExecStart=/usr/local/sbin/event-router-capture stream' "$ROUTER_DIR/rootfs/etc/systemd/system/event-router-flow-log.service"
grep -Fq 'ip saddr { 10.60.200.10, 10.60.201.20, 10.60.201.30 } ip daddr @production_addresses tcp dport 9300 ct state new accept' "$ROUTER_DIR/rootfs/etc/nftables.conf"
grep -Fq 'ip saddr 10.60.200.10 ip daddr 10.60.201.20 tcp dport 9001-9006 ct state new accept' "$ROUTER_DIR/rootfs/etc/nftables.conf"
grep -Fq 'ip daddr @released_production_addresses tcp dport @service_ports' "$ROUTER_DIR/rootfs/etc/nftables.conf"
grep -Fq 'ip daddr . tcp dport @released_hill_services' "$ROUTER_DIR/rootfs/etc/nftables.conf"
grep -Fq 'ip saddr @workbench_addresses ip daddr @production_addresses tcp dport @service_ports jump released_production_guard' "$ROUTER_DIR/rootfs/etc/nftables.conf"
grep -Fq 'iifname "wg0" ip saddr @peer_addresses ip daddr @production_addresses tcp dport @service_ports jump released_production_guard' "$ROUTER_DIR/rootfs/etc/nftables.conf"
grep -Fq 'ip saddr @production_addresses tcp sport @service_ports ip daddr @workbench_addresses jump released_production_reply_guard' "$ROUTER_DIR/rootfs/etc/nftables.conf"
grep -Fq 'ip daddr @production_addresses tcp dport @service_ports snat to 10.60.250.120' "$ROUTER_DIR/rootfs/etc/nftables.conf"
grep -Fq 'ip daddr @staging_addresses tcp dport @service_ports snat to 10.60.250.120' "$ROUTER_DIR/rootfs/etc/nftables.conf"
grep -Fq 'set archive_https_ports {' "$ROUTER_DIR/rootfs/etc/nftables.conf"
grep -Fq 'set archive_imds_ports {' "$ROUTER_DIR/rootfs/etc/nftables.conf"
grep -Fq 'ip daddr 169.254.169.254 tcp dport 80 accept' "$ROUTER_DIR/rootfs/etc/nftables.conf"
grep -Fq 'ip daddr 169.254.169.254 tcp dport @archive_imds_ports accept' "$ROUTER_DIR/rootfs/etc/nftables.conf"
grep -Fq 'tcp dport @archive_https_ports accept' "$ROUTER_DIR/rootfs/etc/nftables.conf"
grep -Fq 'tcp dport @archive_https_ports snat ip to 10.60.250.101' "$ROUTER_DIR/rootfs/etc/nftables.conf"
"$ROUTER_DIR/tests/challenge_access.sh"
"$ROUTER_DIR/tests/restore.sh"
"$ROUTER_DIR/tests/network_namespace.sh"
