#!/usr/bin/env bash
set -euo pipefail

role=${1:-}
case "$role" in
  platform-x86 | platform-arm | production | workbench) ;;
  *) echo "unsupported runtime image role: $role" >&2; exit 2 ;;
esac

for command in auditctl chronyc curl docker git jq nft python3 rsync sshd; do
  command -v "$command" >/dev/null
done
command -v age >/dev/null
docker compose version >/dev/null
sshd -t
python3 -m json.tool /etc/docker/daemon.json >/dev/null
grep -Fxq 'PasswordAuthentication no' /etc/ssh/sshd_config.d/90-runtime.conf
grep -Fxq 'PermitRootLogin no' /etc/ssh/sshd_config.d/90-runtime.conf
systemctl is-enabled docker.service >/dev/null
systemctl is-enabled ssh.service >/dev/null
systemctl is-enabled apt-daily.timer | grep -Fxq masked
systemctl is-enabled apt-daily-upgrade.timer | grep -Fxq masked

if [[ $role == workbench ]]; then
  for command in cargo clang cmake gdb go node npm rg rustc tmux; do
    command -v "$command" >/dev/null
  done
  id -nG ubuntu | tr ' ' '\n' | grep -Fxq docker
else
  ! id -nG ubuntu | tr ' ' '\n' | grep -Fxq docker
fi

if [[ $role == platform-x86 || $role == platform-arm ]]; then
  command -v certbot >/dev/null
  command -v finals-install-secret-bundle >/dev/null
  command -v finals-initialize-volume >/dev/null
  test -x /usr/local/sbin/finals-platform-activate
fi

if [[ $role == production ]]; then
  getent passwd deploy-orchestrator | grep -Fq '/usr/sbin/nologin'
  [[ $(stat -c '%U:%G:%a' /etc/deployment-orchestrator) == root:deploy-orchestrator:700 ]]
  [[ $(stat -c '%U:%G:%a' /var/lib/deployment-orchestrator) == deploy-orchestrator:deploy-orchestrator:710 ]]
  [[ $(stat -c '%U:%G:%a' /var/lib/deployment-orchestrator/repository) == deploy-orchestrator:deploy-orchestrator:750 ]]
  [[ $(stat -c '%U:%G:%a' /var/lib/deployment-orchestrator/offline.lock) == deploy-orchestrator:deploy-orchestrator:600 ]]
  [[ $(stat -c '%U:%G:%a' /etc/deployment-executor) == root:root:700 ]]
  [[ $(stat -c '%U:%G:%a' /var/lib/deployment-executor) == root:root:700 ]]
  [[ $(stat -c '%U:%G:%a' /var/lib/deployment-executor/operations) == root:root:700 ]]
  [[ $(stat -c '%U:%G:%a' /var/lib/deployment-executor/offline.lock) == root:root:600 ]]
  [[ $(stat -c '%U:%G:%a' /usr/local/libexec/deployment-executor/commands) == root:root:700 ]]
  [[ -z $(find /usr/local/libexec/deployment-executor/commands -mindepth 1 -print -quit) ]]
  test -x /usr/local/bin/deployment-orchestrator
  test -x /usr/local/libexec/deployment-orchestrator/runner
  test -x /usr/local/libexec/deployment-executor/executor
  test -x /usr/local/sbin/deployment-orchestrator-state
  ! ldd /usr/local/bin/deployment-orchestrator >/dev/null 2>&1
  ! ldd /usr/local/libexec/deployment-orchestrator/runner >/dev/null 2>&1
  ! ldd /usr/local/libexec/deployment-executor/executor >/dev/null 2>&1
  ! ldd /usr/local/sbin/deployment-orchestrator-state >/dev/null 2>&1
  [[ $(systemctl is-enabled deployment-orchestrator.service 2>/dev/null) == disabled ]]
  ! systemctl is-active --quiet deployment-orchestrator.service
  [[ $(systemctl is-enabled deployment-executor.socket 2>/dev/null) == disabled ]]
  ! systemctl is-active --quiet deployment-executor.socket
  ! systemctl is-active --quiet deployment-executor.service
  ! systemctl is-active --quiet deployment-orchestrator-backup.service
  [[ ! -e /etc/deployment-orchestrator/config.json ]]
  [[ ! -e /etc/deployment-executor/policy.json ]]
  [[ ! -e /var/backups/deployment-orchestrator ]]
  [[ ! -e /var/lib/deployment-orchestrator/state.json ]]
  [[ $(cat /etc/finals-platform/role) == '{"role":"production"}' ]]
  [[ $(grep -Ec '^10\.60\.200\.10[[:space:]]+finals\.h7tex\.com([[:space:]]|$)' /etc/hosts) == 1 ]]
  systemctl is-enabled finals-host-firewall.service >/dev/null
  /usr/local/libexec/finals-platform/firewall --render production | nft --check --file -
  ! command -v go >/dev/null
  ! command -v gcc >/dev/null
fi
