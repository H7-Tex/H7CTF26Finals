#!/usr/bin/env bash
set -euo pipefail

router_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
tool="$router_dir/rootfs/usr/local/sbin/event-router-public-ingress"
ruleset="$router_dir/rootfs/etc/nftables.conf"

if [[ ${EVENT_ROUTER_PUBLIC_TEST_NAMESPACE:-0} != 1 ]]; then
  if [[ $EUID -eq 0 ]]; then
    exec unshare --net --mount env EVENT_ROUTER_PUBLIC_TEST_NAMESPACE=1 "$0"
  fi
  exec unshare --user --map-root-user --net --mount env EVENT_ROUTER_PUBLIC_TEST_NAMESPACE=1 "$0"
fi

mount -t tmpfs tmpfs /etc
install -d -m 0755 /etc/event-router
printf 'active\n' > /etc/event-router/role
mount -t tmpfs tmpfs /run
nft -f "$ruleset"

expected='public-ingress=complete hill-dnat=45 service-dnat=96 ssh-dnat=15 hill-snat=45 ssh-snat=15'
[[ $("$tool" open) == "$expected" ]]
[[ $("$tool" status) == "$expected" ]]
[[ $("$tool" open) == "$expected" ]]
[[ $("$tool" status) == "$expected" ]]

nft delete element inet finals_public hill_dnat '{ 20011 }'
nft add element inet finals_public hill_dnat '{ 20011 : 10.60.210.12 . 7102 }'
if "$tool" status >/dev/null 2>&1; then
  echo "public ingress status trusted a wrong map destination" >&2
  exit 1
fi
[[ $("$tool" open) == "$expected" ]]

printf '%s\n' 'public ingress namespace tests passed'
