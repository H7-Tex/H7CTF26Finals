#!/usr/bin/env bash
set -euo pipefail

runtime_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

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
