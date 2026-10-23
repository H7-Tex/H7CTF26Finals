#!/usr/bin/env bash
set -euo pipefail

[[ ${EUID} -eq 0 ]]

root=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
install -d -m 0755 /usr/local/lib/finals-model-a
install -m 0644 "$root/model_a.py" /usr/local/lib/finals-model-a/model_a.py
install -m 0755 "$root/rootfs/usr/local/sbin/finals-model-a-install" /usr/local/sbin/finals-model-a-install
install -m 0755 "$root/rootfs/usr/local/sbin/finals-model-a-control" /usr/local/sbin/finals-model-a-control
install -m 0755 "$root/rootfs/usr/local/bin/h7" /usr/local/bin/h7
install -m 0440 "$root/rootfs/etc/sudoers.d/finals-model-a" /etc/sudoers.d/finals-model-a
visudo --check --file=/etc/sudoers.d/finals-model-a
