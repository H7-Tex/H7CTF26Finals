#!/usr/bin/env bash
set -euo pipefail

router_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
# shellcheck source=/dev/null
source "$router_dir/rootfs/usr/local/sbin/event-router-restore"
# shellcheck source=/dev/null
source "$router_dir/rootfs/usr/local/sbin/event-router-activate"

test_dir=$(mktemp -d)
trap 'rm -rf -- "$test_dir"' EXIT
role_file="$test_dir/role"
private_key="$test_dir/private.key"
active_inventory="$test_dir/active.json"
calls="$test_dir/calls"

address_tool="$test_dir/addresses"
apply_tool="$test_dir/apply"
cat > "$address_tool" <<EOF
#!/usr/bin/env bash
printf 'addresses %s\n' "\$1" >> '$calls'
EOF
cat > "$apply_tool" <<EOF
#!/usr/bin/env bash
printf 'inventory %s\n' "\$1" >> '$calls'
EOF
chmod 0755 "$address_tool" "$apply_tool"

printf 'active\n' > "$role_file"
restore_state "$role_file" "$private_key" "$active_inventory" "$address_tool" "$apply_tool"
grep -Fxq 'addresses standby' "$calls"
! grep -Fq 'inventory ' "$calls"
! grep -Fq 'addresses active' "$calls"

printf 'secret\n' > "$private_key"
printf '{}\n' > "$active_inventory"
restore_state "$role_file" "$private_key" "$active_inventory" "$address_tool" "$apply_tool"
grep -Fxq "inventory $active_inventory" "$calls"

printf 'standby\n' > "$role_file"
restore_state "$role_file" "$private_key" "$active_inventory" "$address_tool" "$apply_tool"
grep -Fxq 'addresses standby' "$calls"

printf 'unknown\n' > "$role_file"
! restore_state "$role_file" "$private_key" "$active_inventory" "$address_tool" "$apply_tool"

printf 'active\n' > "$role_file"
ready_tool="$test_dir/ready"
ip_tool="$test_dir/ip"
validator="$test_dir/validator"
cat > "$ip_tool" <<'EOF'
#!/usr/bin/env bash
[[ $* == 'link show wg0' ]]
EOF
cat > "$validator" <<'EOF'
#!/usr/bin/env bash
[[ -s $1 && $2 == --active-inventory && $3 == "$1" && $4 == --wireguard-output && $6 == --nft-output ]]
EOF
printf '#!/usr/bin/env bash\nexit 1\n' > "$ready_tool"
chmod 0755 "$ready_tool" "$ip_tool" "$validator"
chmod 0600 "$private_key" "$active_inventory"

before=$(grep -c '^addresses active$' "$calls" || true)
rm -f "$private_key"
! activate_if_ready "$role_file" "$private_key" "$active_inventory" "$ready_tool" "$address_tool" "$ip_tool" "$validator" "$test_dir"
after=$(grep -c '^addresses active$' "$calls" || true)
[[ $before == "$after" ]]

printf 'secret\n' > "$private_key"
chmod 0600 "$private_key"
! activate_if_ready "$role_file" "$private_key" "$active_inventory" "$ready_tool" "$address_tool" "$ip_tool" "$validator" "$test_dir"
after=$(grep -c '^addresses active$' "$calls" || true)
[[ $before == "$after" ]]

printf '#!/usr/bin/env bash\n[[ $1 == ready ]]\n' > "$ready_tool"
activate_if_ready "$role_file" "$private_key" "$active_inventory" "$ready_tool" "$address_tool" "$ip_tool" "$validator" "$test_dir"
grep -Fxq 'addresses active' "$calls"

grep -Fq 'systemctl --no-block restart event-router-activate.service' \
  "$router_dir/rootfs/usr/local/sbin/event-router-apply-inventory"
grep -Fq '/usr/local/sbin/event-router-addresses standby' \
  "$router_dir/rootfs/usr/local/sbin/event-router-initialize"
grep -Fq 'if ! systemctl restart event-router-activate.service; then' \
  "$router_dir/rootfs/usr/local/sbin/event-router-initialize"
grep -Fq 'gateway is uncommissioned; floating addresses remain absent' \
  "$router_dir/rootfs/usr/local/sbin/event-router-initialize"
grep -Fq 'ExecStopPost=/usr/local/sbin/event-router-addresses standby' \
  "$router_dir/rootfs/etc/systemd/system/event-router-flow-log.service"
