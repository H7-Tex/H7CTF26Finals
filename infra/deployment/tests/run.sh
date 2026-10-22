#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$root"

gofmt -d . | tee /tmp/deployment-orchestrator-gofmt.$$
[[ ! -s /tmp/deployment-orchestrator-gofmt.$$ ]]
rm -f /tmp/deployment-orchestrator-gofmt.$$

go vet ./...
go test -race ./...
build_dir=$(mktemp -d)
trap 'rm -rf "$build_dir"' EXIT
for command in deployment-orchestrator deployment-runner deployment-executor deployment-state; do
  CGO_ENABLED=0 go build -trimpath -ldflags='-s -w' -o "$build_dir/$command" "./cmd/$command"
  ! ldd "$build_dir/$command" >/dev/null 2>&1
done

grep -Fq 'ConditionFileIsExecutable=/usr/local/libexec/deployment-orchestrator/runner' rootfs/usr/lib/systemd/system/deployment-orchestrator.service
grep -Fq 'ExecStartPre=+/usr/local/bin/deployment-orchestrator host-preflight' rootfs/usr/lib/systemd/system/deployment-orchestrator.service
grep -Fq 'Requires=deployment-executor.socket finals-volume@production.service' rootfs/usr/lib/systemd/system/deployment-orchestrator.service
grep -Fq 'After=deployment-executor.socket finals-volume@production.service' rootfs/usr/lib/systemd/system/deployment-orchestrator.service
grep -Fq 'IPAddressAllow=10.60.200.10/32' rootfs/usr/lib/systemd/system/deployment-orchestrator.service
grep -Fq 'IPAddressAllow=10.60.201.20/32' rootfs/usr/lib/systemd/system/deployment-orchestrator.service
grep -Fq 'IPAddressAllow=10.60.201.30/32' rootfs/usr/lib/systemd/system/deployment-orchestrator.service
grep -Fxq 'CapabilityBoundingSet=' rootfs/usr/lib/systemd/system/deployment-orchestrator.service
! grep -Eq 'SupplementaryGroups=.*docker|Group=docker' rootfs/usr/lib/systemd/system/deployment-orchestrator.service
grep -Fxq 'UMask=0027' rootfs/usr/lib/systemd/system/deployment-orchestrator.service
! grep -Eq 'IPAddressAllow=10\.6[01]\.[0-9]+\.0/' rootfs/usr/lib/systemd/system/deployment-orchestrator.service
! grep -Eq 'systemctl[[:space:]].*enable.*deployment-orchestrator' install.sh
! grep -Eq 'systemctl[[:space:]].*enable.*deployment-executor' install.sh
grep -Fq 'SocketMode=0660' rootfs/usr/lib/systemd/system/deployment-executor.socket
grep -Fq 'SocketGroup=deploy-orchestrator' rootfs/usr/lib/systemd/system/deployment-executor.socket
grep -Fq 'ExecStartPre=/usr/local/libexec/deployment-executor/executor validate' rootfs/usr/lib/systemd/system/deployment-executor.socket
! grep -Fq 'ConditionPathExists=/etc/deployment-executor/policy.json' rootfs/usr/lib/systemd/system/deployment-executor.socket
grep -Fq 'RestrictAddressFamilies=AF_UNIX' rootfs/usr/lib/systemd/system/deployment-executor.service
grep -Fq 'User=root' rootfs/usr/lib/systemd/system/deployment-executor.service
grep -Fq 'Requires=deployment-executor.socket finals-volume@production.service' rootfs/usr/lib/systemd/system/deployment-executor.service
grep -Fq 'After=deployment-executor.socket docker.service finals-volume@production.service' rootfs/usr/lib/systemd/system/deployment-executor.service
grep -Fxq 'SupplementaryGroups=deploy-orchestrator' rootfs/usr/lib/systemd/system/deployment-executor.service
grep -Fxq 'CapabilityBoundingSet=' rootfs/usr/lib/systemd/system/deployment-executor.service
! grep -Fq 'WantedBy=' rootfs/usr/lib/systemd/system/deployment-executor.service
! grep -Fq '[Install]' rootfs/usr/lib/systemd/system/deployment-orchestrator-backup.service
grep -Fq 'Conflicts=deployment-orchestrator.service' rootfs/usr/lib/systemd/system/deployment-orchestrator-backup.service
grep -Fq 'ConditionPathIsMountPoint=/var/backups/deployment-orchestrator' rootfs/usr/lib/systemd/system/deployment-orchestrator-backup.service

verify_dir=$(mktemp -d)
cp rootfs/usr/lib/systemd/system/deployment-orchestrator.service "$verify_dir/"
cp rootfs/usr/lib/systemd/system/deployment-executor.service "$verify_dir/"
cp rootfs/usr/lib/systemd/system/deployment-executor.socket "$verify_dir/"
cp rootfs/usr/lib/systemd/system/deployment-orchestrator-backup.service "$verify_dir/"
cp ../volumes/finals-volume@.service "$verify_dir/"
sed -i 's#/usr/local/bin/deployment-orchestrator#/bin/true#g' "$verify_dir/deployment-orchestrator.service"
sed -i 's#/usr/local/libexec/deployment-executor/executor#/bin/true#g' "$verify_dir/deployment-executor.service" "$verify_dir/deployment-executor.socket"
sed -i 's#/usr/local/sbin/deployment-orchestrator-state#/bin/true#g' "$verify_dir/deployment-orchestrator-backup.service"
sed -i 's#/usr/local/sbin/finals-initialize-volume#/bin/true#g' "$verify_dir/finals-volume@.service"
systemd-analyze verify "$verify_dir"/*.service "$verify_dir"/*.socket
rm -rf "$verify_dir"

if grep -RniE 'h7d|:latest|docker[[:space:]]+tag|exec\.Command\([^,]+,[[:space:]]*"(sh|bash)"' --include='*.go' --include='*.service' --include='*.md' .; then
  echo "legacy branding, mutable tags or shell execution found" >&2
  exit 1
fi
