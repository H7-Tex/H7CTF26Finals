#!/usr/bin/env bash
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "must run as root" >&2; exit 1; }
source_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
install -D -o root -g root -m 0755 "$source_dir/finals-archive.py" /usr/local/sbin/finals-archive
install -D -o root -g root -m 0755 "$source_dir/finals-archive-egress" /usr/local/sbin/finals-archive-egress
