#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$root"

gofmt -d . | tee /tmp/deployment-orchestrator-gofmt.$$
[[ ! -s /tmp/deployment-orchestrator-gofmt.$$ ]]
rm -f /tmp/deployment-orchestrator-gofmt.$$

go vet ./...
go test -race ./...
CGO_ENABLED=0 go build -trimpath -ldflags='-s -w' -o /tmp/deployment-orchestrator.$$ ./cmd/deployment-orchestrator
! ldd /tmp/deployment-orchestrator.$$ >/dev/null 2>&1
rm -f /tmp/deployment-orchestrator.$$

grep -Fq 'ConditionFileIsExecutable=/usr/local/libexec/deployment-orchestrator/runner' rootfs/usr/lib/systemd/system/deployment-orchestrator.service
grep -Fq 'ExecStartPre=+/usr/local/bin/deployment-orchestrator host-preflight' rootfs/usr/lib/systemd/system/deployment-orchestrator.service
grep -Fq 'IPAddressAllow=10.60.200.10/32' rootfs/usr/lib/systemd/system/deployment-orchestrator.service
grep -Fq 'IPAddressAllow=10.60.201.20/32' rootfs/usr/lib/systemd/system/deployment-orchestrator.service
grep -Fq 'IPAddressAllow=10.60.201.30/32' rootfs/usr/lib/systemd/system/deployment-orchestrator.service
! grep -Eq 'IPAddressAllow=10\.6[01]\.[0-9]+\.0/' rootfs/usr/lib/systemd/system/deployment-orchestrator.service
! grep -Eq 'systemctl[[:space:]].*enable.*deployment-orchestrator' install.sh

verify_unit=$(mktemp --suffix=.service)
cp rootfs/usr/lib/systemd/system/deployment-orchestrator.service "$verify_unit"
sed -i 's#/usr/local/bin/deployment-orchestrator#/bin/true#g' "$verify_unit"
systemd-analyze verify "$verify_unit"
rm -f "$verify_unit"

if grep -RniE 'h7d|:latest|docker[[:space:]]+tag|exec\.Command\([^,]+,[[:space:]]*"(sh|bash)"' --include='*.go' --include='*.service' --include='*.md' .; then
  echo "legacy branding, mutable tags or shell execution found" >&2
  exit 1
fi
