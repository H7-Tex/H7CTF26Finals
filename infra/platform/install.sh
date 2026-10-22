#!/usr/bin/env bash
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "must run as root" >&2; exit 1; }
role=${1:-}
anvil_revision=${2:-}
case "$role" in
  platform-x86 | platform-arm) ;;
  *) echo "unsupported platform image role: $role" >&2; exit 2 ;;
esac

source_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
install -d -m 0755 /opt/finals-platform
cp -a "$source_dir/rootfs/." /
install -D -m 0644 "$source_dir/images.env" /etc/finals-platform/images.env
chmod 0755 \
  /usr/local/libexec/finals-platform/checker-preflight \
  /usr/local/libexec/finals-platform/firewall \
  /usr/local/libexec/finals-platform/mirror-preflight \
  /usr/local/libexec/finals-platform/mirror-runtime-verify \
  /usr/local/libexec/finals-platform/repository-preflight \
  /usr/local/sbin/finals-host-recipient \
  /usr/local/sbin/finals-mirror-manifest \
  /usr/local/sbin/finals-mirror-mode \
  /usr/local/sbin/finals-operations-ssh \
  /usr/local/sbin/finals-platform-activate \
  /usr/local/sbin/finals-repository-commission

if [[ $role == platform-arm ]]; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get install --yes --no-install-recommends apt-cacher-ng
  systemctl disable --now apt-cacher-ng.service || true
  # shellcheck disable=SC1091
  source /etc/finals-platform/images.env
  docker pull "$GITEA_IMAGE"
  docker pull "$VERDACCIO_IMAGE"
  docker pull "$REGISTRY_IMAGE"
  docker pull "$NGINX_IMAGE"
fi

if [[ $role == platform-x86 ]]; then
  [[ $anvil_revision =~ ^[0-9a-f]{40}$ ]] || { echo "exact 40-character Anvil revision is required" >&2; exit 1; }
  "$source_dir/prepare-anvil.sh" "$anvil_revision"
  # shellcheck disable=SC1091
  source /etc/finals-platform/images.env
  docker pull "$MONGO_IMAGE"
fi

systemctl daemon-reload
