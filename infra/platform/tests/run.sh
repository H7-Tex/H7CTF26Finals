#!/usr/bin/env bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

platform_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
bash -n \
  "$platform_dir/install.sh" \
  "$platform_dir/prepare-anvil.sh" \
  "$platform_dir/rootfs/usr/local/sbin/finals-host-recipient" \
  "$platform_dir/rootfs/usr/local/sbin/finals-mirror-mode" \
  "$platform_dir/rootfs/usr/local/sbin/finals-operations-ssh" \
  "$platform_dir/rootfs/usr/local/sbin/finals-platform-activate" \
  "$platform_dir/rootfs/usr/local/sbin/finals-repository-commission" \
  "$platform_dir/rootfs/usr/local/libexec/finals-platform/checker-preflight" \
  "$platform_dir/rootfs/usr/local/libexec/finals-platform/repository-preflight" \
  "$platform_dir/rootfs/usr/local/libexec/finals-platform/mirror-runtime-verify" \
  "$platform_dir/tests/run.sh"
grep -Fq 'archive_egress_enabled(role)' "$platform_dir/rootfs/usr/local/libexec/finals-platform/firewall"
python3 -m unittest discover -s "$platform_dir/tests" -p 'test_*.py'
python3 -c 'import ast, pathlib, sys; [ast.parse(pathlib.Path(path).read_text()) for path in sys.argv[1:]]' \
  "$platform_dir/rootfs/usr/local/sbin/finals-mirror-manifest" \
  "$platform_dir/rootfs/usr/local/libexec/finals-platform/firewall" \
  "$platform_dir/rootfs/usr/local/libexec/finals-platform/mirror-preflight"

while IFS='=' read -r name image; do
  [[ $name =~ ^[A-Z][A-Z0-9_]*_IMAGE$ ]]
  [[ $image =~ @sha256:[0-9a-f]{64}$ ]]
done < "$platform_dir/images.env"

for role in platform operations control repository mirror production hill-01 hill-02 hill-03; do
  rules=$(mktemp)
  "$platform_dir/rootfs/usr/local/libexec/finals-platform/firewall" --render "$role" > "$rules"
  if command -v nft >/dev/null && [[ $EUID -eq 0 ]]; then
    nft --check --file "$rules"
  fi
  rm -f "$rules"
done

grep -Fq 'ConditionPathIsMountPoint=/srv/gitea' "$platform_dir/rootfs/etc/systemd/system/finals-repository.service"
grep -Fq 'WantedBy=multi-user.target' "$platform_dir/rootfs/etc/systemd/system/finals-platform.target"
[[ $(grep -hc 'restart: "on-failure:5"' "$platform_dir/rootfs/etc/finals-platform/mirror/compose.yaml" "$platform_dir/rootfs/etc/finals-platform/repository/compose.yaml" | awk '{ total += $1 } END { print total }') == 5 ]]
! grep -Eq 'restart: (unless-stopped|always)' "$platform_dir/rootfs/etc/finals-platform/mirror/compose.yaml" "$platform_dir/rootfs/etc/finals-platform/repository/compose.yaml"
grep -Fq 'ConditionPathExists=/etc/finals-platform/mirror/preseed-manifest.json' "$platform_dir/rootfs/etc/systemd/system/finals-mirror.service"
grep -Fq 'ExecStartPost=/usr/local/libexec/finals-platform/mirror-runtime-verify' "$platform_dir/rootfs/etc/systemd/system/finals-mirror.service"
grep -Fq 'systemctl restart finals-mirror.service' "$platform_dir/rootfs/usr/local/sbin/finals-mirror-mode"
grep -Fq 'FINALS_REGISTRY_MODE=offline' "$platform_dir/rootfs/usr/local/libexec/finals-platform/mirror-runtime-verify"
grep -Fq 'readonly:' "$platform_dir/rootfs/etc/finals-platform/mirror/registry-offline.yaml"
! grep -Fq 'readonly:' "$platform_dir/rootfs/etc/finals-platform/mirror/registry-warmup.yaml"
grep -Fq 'ConditionPathExists=/etc/finals-platform/checkers/artifact-manifest.json' "$platform_dir/rootfs/etc/systemd/system/finals-checkers-ready.service"
grep -Fq '/usr/local/libexec/checker-runtime/runtime.py validate-artifacts' "$platform_dir/rootfs/usr/local/libexec/finals-platform/checker-preflight"
grep -Fq 'SSH_SERVER_HOST_KEYS = /var/lib/gitea/ssh/gitea_ed25519' "$platform_dir/rootfs/usr/local/sbin/finals-repository-commission"
grep -Fq 'repository:repository)' "$platform_dir/rootfs/usr/local/sbin/finals-operations-ssh"
grep -Fq 'control:control-reconciler | control:control-checkers)' "$platform_dir/rootfs/usr/local/sbin/finals-operations-ssh"
grep -Fq 'address=10.60.201.30; port=2222' "$platform_dir/rootfs/usr/local/sbin/finals-operations-ssh"
grep -Fq 'StrictHostKeyChecking=yes' "$platform_dir/rootfs/usr/local/sbin/finals-operations-ssh"
grep -Fq '[[ $# -eq 2 ]]' "$platform_dir/rootfs/usr/local/sbin/finals-operations-ssh"
grep -Fq '"install $bundle"' "$platform_dir/rootfs/usr/local/sbin/finals-operations-ssh"
! grep -Fq '"$@"' "$platform_dir/rootfs/usr/local/sbin/finals-operations-ssh"
! grep -Eq 'mirror\)|hill-0[123]\)' "$platform_dir/rootfs/usr/local/sbin/finals-operations-ssh"
grep -Fq 'install_relay_sudoers control-reconciler control-checkers' "$platform_dir/rootfs/usr/local/sbin/finals-platform-activate"
grep -Fq 'systemctl disable peer-reconciler.timer checker-runtime.service finals-checkers-ready.service' "$platform_dir/rootfs/usr/local/sbin/finals-platform-activate"
