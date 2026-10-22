#!/usr/bin/env bash
set -euo pipefail

runtime_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
deployment_dir=$(cd "$runtime_dir/../../deployment" && pwd)

bash -n \
  "$runtime_dir/build-image" \
  "$runtime_dir/install.sh" \
  "$runtime_dir/seal-image" \
  "$runtime_dir/tests/run.sh" \
  "$runtime_dir/tests/static.sh"
python3 -m json.tool "$runtime_dir/rootfs/etc/docker/daemon.json" >/dev/null
grep -Fxq 'PasswordAuthentication no' "$runtime_dir/rootfs/etc/ssh/sshd_config.d/90-runtime.conf"
grep -Fq 'docker-compose-v2' "$runtime_dir/install.sh"
grep -Fq 'cloud-init clean --logs --machine-id' "$runtime_dir/seal-image"
grep -Fq 'rm -f /etc/ssh/ssh_host_*' "$runtime_dir/seal-image"
grep -Fq 'age' "$runtime_dir/install.sh"
grep -Fq 'certbot' "$runtime_dir/install.sh"
grep -Fq 'deploy-orchestrator' "$runtime_dir/rootfs/usr/lib/sysusers.d/deployment-orchestrator.conf"
grep -Fq "dpkg-query -W" "$runtime_dir/seal-image"
grep -Fq 'package_manifest_sha256' "$runtime_dir/seal-image"
grep -Fq 'CGO_ENABLED=0 go build' "$runtime_dir/build-image"
grep -Fq 'apt-get purge --yes --auto-remove build-essential golang-go' "$runtime_dir/build-image"
grep -Fq 'deployment/install.sh' "$runtime_dir/build-image"
grep -Fq 'systemctl enable finals-host-firewall.service' "$runtime_dir/build-image"
grep -Fq '10.60.200.10 finals.h7tex.com' "$runtime_dir/build-image"
grep -Fq 'find "$source_dir" -mindepth 1 -delete' "$runtime_dir/seal-image"
grep -Fq 'ConditionPathExists=/etc/deployment-orchestrator/config.json' "$deployment_dir/rootfs/usr/lib/systemd/system/deployment-orchestrator.service"
grep -Fq 'ConditionPathExists=/var/lib/deployment-orchestrator/state.json' "$deployment_dir/rootfs/usr/lib/systemd/system/deployment-orchestrator.service"
grep -Fq 'ConditionFileIsExecutable=/usr/local/libexec/deployment-orchestrator/runner' "$deployment_dir/rootfs/usr/lib/systemd/system/deployment-orchestrator.service"
grep -Fq 'Requires=deployment-executor.socket finals-volume@production.service' "$deployment_dir/rootfs/usr/lib/systemd/system/deployment-orchestrator.service"
grep -Fq 'Requires=deployment-executor.socket finals-volume@production.service' "$deployment_dir/rootfs/usr/lib/systemd/system/deployment-executor.service"
! grep -Eq 'systemctl[[:space:]].*enable.*deployment-orchestrator' "$deployment_dir/install.sh" "$runtime_dir/build-image"
grep -Fq './cmd/deployment-runner' "$runtime_dir/build-image"
grep -Fq './cmd/deployment-executor' "$runtime_dir/build-image"
grep -Fq './cmd/deployment-state' "$runtime_dir/build-image"
grep -Fq 'SocketMode=0660' "$deployment_dir/rootfs/usr/lib/systemd/system/deployment-executor.socket"
! grep -Fq 'ConditionPathExists=/etc/deployment-executor/policy.json' "$deployment_dir/rootfs/usr/lib/systemd/system/deployment-executor.socket"
! grep -Eq 'systemctl[[:space:]].*enable.*deployment-executor' "$deployment_dir/install.sh" "$runtime_dir/build-image"
! grep -Eq 'systemctl[[:space:]].*enable.*deployment-orchestrator-backup' "$deployment_dir/install.sh" "$runtime_dir/build-image"
