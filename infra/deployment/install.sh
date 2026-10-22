#!/usr/bin/env bash
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "must run as root" >&2; exit 1; }
[[ $# -ge 4 && $# -le 5 ]] || { echo "usage: install.sh ORCHESTRATOR RUNNER EXECUTOR STATE_HELPER [ROOT]" >&2; exit 1; }

orchestrator_binary=$1
runner_binary=$2
executor_binary=$3
state_binary=$4
root=${5:-/}
source_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

for binary in "$orchestrator_binary" "$runner_binary" "$executor_binary" "$state_binary"; do
  [[ -f $binary && -x $binary ]] || { echo "binary is not executable: $binary" >&2; exit 1; }
done
for command in install cp systemd-sysusers systemd-tmpfiles systemctl; do
  command -v "$command" >/dev/null || { echo "missing dependency: $command" >&2; exit 1; }
done

cp -a "$source_dir/rootfs/." "$root/"
install -D -m 0755 "$source_dir/compile-release.py" "$root/usr/local/sbin/finals-compile-release"
install -D -m 0755 "$source_dir/tests/service_proxy_smoke.py" "$root/usr/local/libexec/finals-service-proxy-smoke"
install -D -m 0755 "$orchestrator_binary" "$root/usr/local/bin/deployment-orchestrator"
install -D -m 0755 "$runner_binary" "$root/usr/local/libexec/deployment-orchestrator/runner"
install -D -m 0755 "$executor_binary" "$root/usr/local/libexec/deployment-executor/executor"
install -d -o root -g root -m 0700 "$root/usr/local/libexec/deployment-executor/commands"
install -D -m 0700 "$state_binary" "$root/usr/local/sbin/deployment-orchestrator-state"
systemd-sysusers --root="$root"

if [[ $root == / ]]; then
  systemd-tmpfiles --create /usr/lib/tmpfiles.d/deployment-orchestrator.conf
  systemd-tmpfiles --create /usr/lib/tmpfiles.d/deployment-executor.conf
  systemd-tmpfiles --create /usr/lib/tmpfiles.d/finals-release.conf
  systemctl daemon-reload
fi
