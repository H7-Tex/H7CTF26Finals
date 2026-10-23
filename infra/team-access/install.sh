#!/usr/bin/env bash
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "must run as root" >&2; exit 1; }
source_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
install -D -o root -g root -m 0755 "$source_dir/team-access.py" /usr/local/sbin/finals-team-access
temporary=$(mktemp /etc/sudoers.d/.finals-team-access.XXXXXX)
trap 'rm -f -- "$temporary"' EXIT
cat > "$temporary" <<'EOF'
ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-team-access apply
ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-team-access rollback
EOF
chmod 0440 "$temporary"
visudo -cf "$temporary" >/dev/null
mv "$temporary" /etc/sudoers.d/finals-team-access
trap - EXIT
