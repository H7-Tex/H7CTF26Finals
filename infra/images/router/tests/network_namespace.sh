#!/usr/bin/env bash
set -euo pipefail

ROUTER_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
RULESET="$ROUTER_DIR/rootfs/etc/nftables.conf"
ADDRESS_TOOL="$ROUTER_DIR/rootfs/usr/local/sbin/event-router-addresses"

if [[ ${EVENT_ROUTER_TEST_NAMESPACE:-0} != 1 ]]; then
  if [[ $EUID -eq 0 ]]; then
    exec unshare --net env EVENT_ROUTER_TEST_NAMESPACE=1 "$0"
  fi
  exec unshare --user --map-root-user --net env EVENT_ROUTER_TEST_NAMESPACE=1 "$0"
fi

children=()
servers=()
test_tmp=$(mktemp -d)
cleanup() {
  ((${#servers[@]} == 0)) || kill "${servers[@]}" 2>/dev/null || true
  ((${#children[@]} == 0)) || kill "${children[@]}" 2>/dev/null || true
  rm -rf -- "$test_tmp"
}
trap cleanup EXIT

spawn_namespace() {
  unshare --net sleep 300 &
  SPAWNED_PID=$!
  children+=("$SPAWNED_PID")
  for _ in $(seq 1 50); do
    [[ $(readlink "/proc/$SPAWNED_PID/ns/net") != "$(readlink /proc/self/ns/net)" ]] && return
    sleep 0.02
  done
  echo "network namespace failed to start" >&2
  exit 1
}

attach() {
  local router_name=$1 peer_name=$2 pid=$3 router_address=$4 peer_address=$5
  ip link add "$router_name" type veth peer name "$peer_name"
  ip link set "$peer_name" netns "$pid"
  ip address add "$router_address" dev "$router_name"
  ip link set "$router_name" up
  nsenter --target "$pid" --net ip link set lo up
  nsenter --target "$pid" --net ip address add "$peer_address" dev "$peer_name"
  nsenter --target "$pid" --net ip link set "$peer_name" up
}

start_tcp_server() {
  local pid=$1 address=$2 port=$3
  local marker="$test_tmp/server-${#servers[@]}.ready"
  local code='import pathlib,socket,sys;s=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);s.bind((sys.argv[1],int(sys.argv[2])));s.listen();pathlib.Path(sys.argv[3]).touch();c,a=s.accept();c.sendall(a[0].encode());c.close()'
  if [[ $pid == self ]]; then
    python3 -c "$code" "$address" "$port" "$marker" &
  else
    nsenter --target "$pid" --net python3 -c "$code" "$address" "$port" "$marker" &
  fi
  servers+=("$!")
  for _ in $(seq 1 50); do
    [[ -e $marker ]] && return
    sleep 0.02
  done
  echo "TCP test server failed to start" >&2
  exit 1
}

start_udp_server() {
  local pid=$1 address=$2 port=$3
  local marker="$test_tmp/server-${#servers[@]}.ready"
  local code='import pathlib,socket,sys;s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.bind((sys.argv[1],int(sys.argv[2])));pathlib.Path(sys.argv[3]).touch();d,a=s.recvfrom(64);s.sendto(b"ok",a)'
  if [[ $pid == self ]]; then
    python3 -c "$code" "$address" "$port" "$marker" &
  else
    nsenter --target "$pid" --net python3 -c "$code" "$address" "$port" "$marker" &
  fi
  servers+=("$!")
  for _ in $(seq 1 50); do
    [[ -e $marker ]] && return
    sleep 0.02
  done
  echo "UDP test server failed to start" >&2
  exit 1
}

tcp_client() {
  local pid=$1 address=$2 port=$3 source=${4:-}
  local code='import socket,sys;s=socket.socket();s.settimeout(0.5);src=sys.argv[3];src and s.bind((src,0));s.connect((sys.argv[1],int(sys.argv[2])));print(s.recv(64).decode())'
  nsenter --target "$pid" --net python3 -c "$code" "$address" "$port" "$source"
}

udp_client() {
  local pid=$1 address=$2 port=$3
  local code='import socket,sys;s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.settimeout(0.5);s.sendto(b"probe",(sys.argv[1],int(sys.argv[2])));print(s.recvfrom(64)[0].decode())'
  nsenter --target "$pid" --net python3 -c "$code" "$address" "$port"
}

spawn_namespace
WAN_PID=$SPAWNED_PID
spawn_namespace
LAN_PID=$SPAWNED_PID
spawn_namespace
PEER_PID=$SPAWNED_PID
spawn_namespace
WORKBENCH_PID=$SPAWNED_PID
spawn_namespace
WORKBENCH_TWO_PID=$SPAWNED_PID
spawn_namespace
PRODUCTION_PID=$SPAWNED_PID
spawn_namespace
PRODUCTION_TWO_PID=$SPAWNED_PID
spawn_namespace
CORE_PID=$SPAWNED_PID
spawn_namespace
MIRROR_PID=$SPAWNED_PID

attach wan-r wan-c "$WAN_PID" 192.0.2.1/24 192.0.2.2/24
attach lan-r lan-c "$LAN_PID" 10.60.200.1/24 10.60.200.10/24
attach wg0 peer-c "$PEER_PID" 10.80.255.1/16 10.80.1.200/16
attach wb-r wb-c "$WORKBENCH_PID" 10.61.1.1/24 10.61.1.2/24
attach wb2-r wb2-c "$WORKBENCH_TWO_PID" 10.61.2.1/24 10.61.2.2/24
attach prod-r prod-c "$PRODUCTION_PID" 10.60.1.1/24 10.60.1.2/24
attach prod2-r prod2-c "$PRODUCTION_TWO_PID" 10.60.2.1/24 10.60.2.2/24
attach core-r core-c "$CORE_PID" 10.60.201.1/24 10.60.201.20/24
attach mirror-r mirror-c "$MIRROR_PID" 10.60.202.1/24 10.60.202.10/24

nsenter --target "$LAN_PID" --net ip address add 10.60.200.5/24 dev lan-c
nsenter --target "$PRODUCTION_PID" --net ip address add 10.60.1.3/24 dev prod-c
nsenter --target "$CORE_PID" --net ip address add 10.60.201.30/24 dev core-c

nsenter --target "$WAN_PID" --net ip route add default via 192.0.2.1
nsenter --target "$LAN_PID" --net ip route add default via 10.60.200.1
nsenter --target "$PEER_PID" --net ip route add default via 10.80.255.1
nsenter --target "$WORKBENCH_PID" --net ip route add default via 10.61.1.1
nsenter --target "$WORKBENCH_TWO_PID" --net ip route add default via 10.61.2.1
nsenter --target "$PRODUCTION_PID" --net ip route add default via 10.60.1.1
nsenter --target "$PRODUCTION_TWO_PID" --net ip route add default via 10.60.2.1
nsenter --target "$CORE_PID" --net ip route add default via 10.60.201.1
nsenter --target "$MIRROR_PID" --net ip route add default via 10.60.202.1

EVENT_ROUTER_INTERFACE=wan-r "$ADDRESS_TOOL" active
ip address add 10.60.250.10/24 dev wan-r
nsenter --target "$WAN_PID" --net ip address add 10.60.250.11/24 dev wan-c
ip address show dev wan-r | grep -Fq '10.60.250.100/24'
ip address show dev wan-r | grep -Fq '10.60.250.101/24'
ip address show dev wan-r | grep -Fq '10.60.250.121/24'
ip address show dev wan-r | grep -Fq '10.60.250.135/24'

sysctl -q -w net.ipv4.ip_forward=1
sysctl -q -w net.ipv4.conf.all.rp_filter=0
nft -f "$RULESET"
nft add element inet event_router peer_addresses '{ 10.80.1.200 }'
nft add element inet event_router peer_snat '{ 10.80.1.200 : 10.60.250.121 }'
nft add element inet event_router peer_workbench_access '{ 10.80.1.200 . 10.61.1.2 }'

start_udp_server self 10.60.250.100 443
[[ $(udp_client "$WAN_PID" 10.60.250.100 443) == ok ]]

start_tcp_server self 10.60.250.100 443
if tcp_client "$WAN_PID" 10.60.250.100 443 >/dev/null 2>&1; then
  echo "TCP reached the VPN address" >&2
  exit 1
fi

start_udp_server self 10.60.250.101 443
if udp_client "$WAN_PID" 10.60.250.101 443 >/dev/null 2>&1; then
  echo "UDP reached the web address" >&2
  exit 1
fi

start_tcp_server "$LAN_PID" 10.60.200.10 443
[[ $(tcp_client "$WAN_PID" 10.60.250.101 443) == 10.60.200.1 ]]

start_tcp_server "$LAN_PID" 10.60.200.10 443
[[ $(tcp_client "$PEER_PID" 10.60.200.10 443) == 10.60.250.121 ]]

start_tcp_server "$LAN_PID" 10.60.200.10 4141
[[ $(tcp_client "$PEER_PID" 10.60.200.10 4141) == 10.60.250.121 ]]

start_tcp_server "$LAN_PID" 10.60.200.10 4141
[[ $(tcp_client "$WORKBENCH_PID" 10.60.200.10 4141) == 10.60.250.121 ]]

start_tcp_server self 10.60.250.101 4141
if tcp_client "$WAN_PID" 10.60.250.101 4141 >/dev/null 2>&1; then
  echo "the public web address exposed the VPN-only submission port" >&2
  exit 1
fi

start_tcp_server "$PRODUCTION_PID" 10.60.1.2 7001
[[ $(tcp_client "$PEER_PID" 10.60.1.2 7001) == 10.60.250.121 ]]

start_tcp_server "$PRODUCTION_PID" 10.60.1.2 7002
[[ $(tcp_client "$WORKBENCH_PID" 10.60.1.2 7002) == 10.60.250.121 ]]

start_tcp_server "$MIRROR_PID" 10.60.202.10 3141
[[ $(tcp_client "$WORKBENCH_PID" 10.60.202.10 3141) == 10.60.250.121 ]]

start_tcp_server "$MIRROR_PID" 10.60.202.10 22
if tcp_client "$WORKBENCH_PID" 10.60.202.10 22 >/dev/null 2>&1; then
  echo "a workbench reached a non-mirror port" >&2
  exit 1
fi

start_tcp_server "$WORKBENCH_PID" 10.61.1.2 2222
[[ $(tcp_client "$PEER_PID" 10.61.1.2 2222) == 10.60.250.121 ]]

start_tcp_server "$WORKBENCH_TWO_PID" 10.61.2.2 22
if tcp_client "$PEER_PID" 10.61.2.2 22 >/dev/null 2>&1; then
  echo "a peer reached another team's workbench" >&2
  exit 1
fi

start_tcp_server "$CORE_PID" 10.60.201.20 443
if tcp_client "$PEER_PID" 10.60.201.20 443 >/dev/null 2>&1; then
  echo "a peer reached the checker control host" >&2
  exit 1
fi

start_tcp_server "$LAN_PID" 10.60.200.5 22
if tcp_client "$PEER_PID" 10.60.200.5 22 >/dev/null 2>&1; then
  echo "a peer reached the operations host" >&2
  exit 1
fi

start_tcp_server "$PRODUCTION_PID" 10.60.1.2 9100
[[ $(tcp_client "$WORKBENCH_PID" 10.60.1.2 9100) == 10.60.250.121 ]]

start_tcp_server "$PRODUCTION_TWO_PID" 10.60.2.2 9100
if tcp_client "$WORKBENCH_PID" 10.60.2.2 9100 >/dev/null 2>&1; then
  echo "a workbench reached another team's management endpoint" >&2
  exit 1
fi

start_tcp_server "$PRODUCTION_PID" 10.60.1.2 7003
[[ $(tcp_client "$CORE_PID" 10.60.1.2 7003 10.60.201.20) == 10.60.201.20 ]]

start_tcp_server "$LAN_PID" 10.60.200.10 443
[[ $(tcp_client "$CORE_PID" 10.60.200.10 443 10.60.201.20) == 10.60.201.20 ]]

start_tcp_server "$LAN_PID" 10.60.200.10 443
if tcp_client "$CORE_PID" 10.60.200.10 443 10.60.201.30 >/dev/null 2>&1; then
  echo "a non-control core host reached Anvil" >&2
  exit 1
fi
kill "${servers[-1]}" 2>/dev/null || true

start_tcp_server self 10.60.250.10 22
[[ $(tcp_client "$CORE_PID" 10.60.250.10 22 10.60.201.20) == 10.60.201.20 ]]

start_tcp_server self 10.60.250.10 22
if tcp_client "$CORE_PID" 10.60.250.10 22 10.60.201.30 >/dev/null 2>&1; then
  echo "a non-control core host reached gateway SSH" >&2
  exit 1
fi

start_tcp_server "$WAN_PID" 10.60.250.11 22
[[ $(tcp_client "$CORE_PID" 10.60.250.11 22 10.60.201.20) == 10.60.201.20 ]]

start_tcp_server "$PRODUCTION_PID" 10.60.1.3 7004
[[ $(tcp_client "$CORE_PID" 10.60.1.3 7004 10.60.201.20) == 10.60.201.20 ]]

start_tcp_server "$PRODUCTION_PID" 10.60.1.2 9300
[[ $(tcp_client "$CORE_PID" 10.60.1.2 9300 10.60.201.30) == 10.60.201.30 ]]

start_tcp_server "$CORE_PID" 10.60.201.30 443
[[ $(tcp_client "$PRODUCTION_PID" 10.60.201.30 443) == 10.60.1.2 ]]

start_tcp_server "$MIRROR_PID" 10.60.202.10 5000
[[ $(tcp_client "$PRODUCTION_PID" 10.60.202.10 5000) == 10.60.1.2 ]]

start_tcp_server "$MIRROR_PID" 10.60.202.10 4873
[[ $(tcp_client "$PRODUCTION_PID" 10.60.202.10 4873) == 10.60.1.2 ]]

start_tcp_server "$MIRROR_PID" 10.60.202.10 443
if tcp_client "$PRODUCTION_PID" 10.60.202.10 443 >/dev/null 2>&1; then
  echo "a production host reached a non-mirror port" >&2
  exit 1
fi

start_tcp_server "$CORE_PID" 10.60.201.20 9300
[[ $(tcp_client "$PRODUCTION_PID" 10.60.201.20 9300) == 10.60.1.2 ]]

start_tcp_server "$LAN_PID" 10.60.200.10 443
[[ $(tcp_client "$PRODUCTION_PID" 10.60.200.10 443) == 10.60.1.2 ]]

start_tcp_server "$LAN_PID" 10.60.200.10 4141
if tcp_client "$PRODUCTION_PID" 10.60.200.10 4141 >/dev/null 2>&1; then
  echo "a production host reached the VPN-only submission port" >&2
  exit 1
fi

nsenter --target "$PEER_PID" --net ip address add 10.80.2.200/16 dev peer-c
start_tcp_server "$PRODUCTION_PID" 10.60.1.2 7005
if tcp_client "$PEER_PID" 10.60.1.2 7005 10.80.2.200 >/dev/null 2>&1; then
  echo "an unmapped peer address was forwarded" >&2
  exit 1
fi

start_tcp_server "$WAN_PID" 192.0.2.2 9443
if tcp_client "$PEER_PID" 192.0.2.2 9443 >/dev/null 2>&1; then
  echo "a peer reached the public network through the router" >&2
  exit 1
fi

EVENT_ROUTER_INTERFACE=wan-r "$ADDRESS_TOOL" standby
if ip address show dev wan-r | grep -Fq '10.60.250.100/24'; then
  echo "standby retained ingress addresses" >&2
  exit 1
fi

echo "router namespace tests passed"
