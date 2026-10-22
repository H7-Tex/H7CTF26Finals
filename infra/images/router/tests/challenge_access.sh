#!/usr/bin/env bash
set -euo pipefail

router_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
# shellcheck source=/dev/null
source "$router_dir/rootfs/usr/local/sbin/event-router-challenge-access"

test_dir=$(mktemp -d)
trap 'rm -rf -- "$test_dir"' EXIT
state_file="$test_dir/state/challenge-access"
calls="$test_dir/nft-input"
kernel_state="$test_dir/kernel-state"
printf 'closed\n' > "$kernel_state"
nft_tool="$test_dir/nft"
cat > "$nft_tool" <<EOF
#!/usr/bin/env bash
set -euo pipefail
if [[ \$1 == -f && \$2 == - ]]; then
  payload=\$(cat)
  printf '%s\n' "\$payload" > '$calls'
  if grep -Fq 'add element' <<<"\$payload"; then
    printf 'open\n' > '$kernel_state'
  else
    printf 'closed\n' > '$kernel_state'
  fi
  exit 0
fi
[[ \$1 == -j && \$2 == list && \$3 == set && \$4 == inet && \$5 == event_router ]]
state=\$(cat '$kernel_state')
case \$6 in
  released_production_addresses)
    if [[ \$state == open ]]; then
      printf '%s\n' '{"nftables":[{"set":{"name":"released_production_addresses","elem":["10.60.1.2","10.60.2.2","10.60.3.2","10.60.4.2","10.60.5.2","10.60.6.2","10.60.7.2","10.60.8.2","10.60.9.2","10.60.10.2","10.60.11.2","10.60.12.2","10.60.13.2","10.60.14.2","10.60.15.2","10.60.16.2"]}}]}'
    else
      printf '%s\n' '{"nftables":[{"set":{"name":"released_production_addresses"}}]}'
    fi
    ;;
  released_hill_services)
    if [[ \$state == open ]]; then
      printf '%s\n' '{"nftables":[{"set":{"name":"released_hill_services","elem":[{"concat":["10.60.210.11",7101]},{"concat":["10.60.210.12",7102]},{"concat":["10.60.210.13",7103]}]}}]}'
    else
      printf '%s\n' '{"nftables":[{"set":{"name":"released_hill_services"}}]}'
    fi
    ;;
esac
EOF
chmod 0755 "$nft_tool"

restore_challenge_access "$state_file" "$nft_tool" "$(id -u)"
[[ $(cat "$state_file") == closed ]]
[[ $(stat -c '%a' "$state_file") == 600 ]]
grep -Fq 'flush set inet event_router released_production_addresses' "$calls"
! grep -Fq 'add element' "$calls"

set_challenge_access open "$state_file" "$nft_tool"
[[ $(cat "$state_file") == open ]]
[[ $(cat "$kernel_state") == open ]]
grep -Fq 'add element inet event_router released_production_addresses { 10.60.1.2,10.60.2.2' "$calls"
grep -Fq '10.60.15.2,10.60.16.2 }' "$calls"
grep -Fq 'add element inet event_router released_hill_services { 10.60.210.11 . 7101,10.60.210.12 . 7102,10.60.210.13 . 7103 }' "$calls"

restore_challenge_access "$state_file" "$nft_tool"
[[ $(cat "$state_file") == closed ]]
[[ $(cat "$kernel_state") == closed ]]

printf 'invalid\n' > "$state_file"
restore_challenge_access "$state_file" "$nft_tool"
[[ $(cat "$state_file") == closed ]]
! grep -Fq 'add element' "$calls"

chmod 0644 "$state_file"
restore_challenge_access "$state_file" "$nft_tool"
[[ $(stat -c '%a' "$state_file") == 600 ]]
[[ $(cat "$state_file") == closed ]]

if set_challenge_access open /proc/event-router-challenge-access-test "$nft_tool" 2>/dev/null; then
  echo "challenge access survived a persistence failure" >&2
  exit 1
fi
[[ $(cat "$kernel_state") == closed ]]

set_challenge_access open "$state_file" "$nft_tool"
printf 'closed\n' > "$kernel_state"
if status_challenge_access "$state_file" "$nft_tool" "$(id -u)" >/dev/null 2>&1; then
  echo "kernel/file release-state drift was trusted" >&2
  exit 1
fi
[[ $(cat "$kernel_state") == closed ]]
[[ $(cat "$state_file") == closed ]]

set_challenge_access open "$state_file" "$nft_tool"
[[ $(cat "$state_file") == open ]]
persist_challenge_access() { return 1; }
if set_challenge_access open "$state_file" "$nft_tool" 2>/dev/null; then
  echo "an existing open marker survived a forced persistence failure" >&2
  exit 1
fi
[[ $(cat "$kernel_state") == closed ]]
[[ ! -e $state_file ]]

printf 'open\n' > "$state_file"
if restore_challenge_access "$state_file" "$nft_tool" 2>/dev/null; then
  echo "restore accepted a stale open marker" >&2
  exit 1
fi
[[ $(cat "$kernel_state") == closed ]]
[[ ! -e $state_file ]]
