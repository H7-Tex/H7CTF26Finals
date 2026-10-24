#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cache=$(mktemp -d)
trap 'rm -rf "$cache"' EXIT
PYTHONPYCACHEPREFIX="$cache" python3 -m py_compile \
  "$root/model_a.py" \
  "$root/sign-service-update.py" \
  "$root/prepare-release.py" \
  "$root/write-volume-policy.py" \
  "$root/tests/firewall-path.py" \
  "$root/tests/local-acceptance.py" \
  "$root/rootfs/usr/local/sbin/finals-model-a-install" \
  "$root/rootfs/usr/local/sbin/finals-model-a-control"
bash -n \
  "$root/install.sh" \
  "$root/rootfs/usr/local/sbin/finals-model-a-firstboot"
grep -Fq 'Requires=finals-volume@production.service docker.service finals-host-firewall.service' \
  "$root/rootfs/etc/systemd/system/finals-model-a-firstboot.service"
sh -n "$root/rootfs/usr/local/bin/h7"
if command -v visudo >/dev/null; then
  visudo --check --file="$root/rootfs/etc/sudoers.d/finals-model-a"
fi
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s "$root/tests" -p 'test_*.py' -v
