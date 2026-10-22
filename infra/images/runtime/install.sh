#!/usr/bin/env bash
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "must run as root" >&2; exit 1; }
role=${1:-}
case "$role" in
  platform-x86 | platform-arm | production | workbench) ;;
  *) echo "unsupported runtime image role: $role" >&2; exit 2 ;;
esac

source_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get dist-upgrade --yes
apt-get install --yes --no-install-recommends \
  auditd \
  age \
  ca-certificates \
  chrony \
  curl \
  docker-buildx \
  docker-compose-v2 \
  docker.io \
  git \
  jq \
  nftables \
  openssh-server \
  python3 \
  rsync \
  sudo \
  unzip

if [[ $role == platform-x86 || $role == platform-arm ]]; then
  apt-get install --yes --no-install-recommends certbot openssl
fi

if [[ $role == workbench ]]; then
  apt-get install --yes --no-install-recommends \
    build-essential \
    clang \
    cmake \
    gdb \
    golang-go \
    nodejs \
    npm \
    pkg-config \
    python3-pip \
    python3-venv \
    ripgrep \
    rustc \
    cargo \
    tmux \
    zip
fi

if [[ $role == production ]]; then
  apt-get install --yes --no-install-recommends haproxy xfsprogs
fi

cp --archive "$source_dir/rootfs/." /
chmod 0644 /etc/docker/daemon.json /etc/ssh/sshd_config.d/90-runtime.conf /etc/sysctl.d/90-runtime.conf
install -d -m 0755 /run/sshd
sshd -t
sysctl --system >/dev/null

systemctl enable auditd.service chrony.service docker.service ssh.service
systemctl mask apt-daily.service apt-daily-upgrade.service apt-daily.timer apt-daily-upgrade.timer

if [[ $role == workbench ]]; then
  usermod --append --groups docker ubuntu
else
  gpasswd --delete ubuntu docker >/dev/null 2>&1 || true
fi

if [[ $role == production ]]; then
  systemd-sysusers /usr/lib/sysusers.d/deployment-orchestrator.conf
  systemctl mask haproxy.service
  install -d -o root -g deploy-orchestrator -m 0700 /etc/deployment-orchestrator
  install -d -o deploy-orchestrator -g deploy-orchestrator -m 0710 /var/lib/deployment-orchestrator
fi
