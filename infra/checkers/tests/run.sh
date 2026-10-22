#!/usr/bin/env bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

checker_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
runtime="$checker_dir/rootfs/usr/local/libexec/checker-runtime/runtime.py"

bash -n \
  "$checker_dir/install.sh" \
  "$checker_dir/rootfs/usr/local/sbin/checker-runtime-commission" \
  "$checker_dir/tests/egress_isolation.sh" \
  "$checker_dir/tests/run.sh"
python3 -m json.tool "$checker_dir/artifact-manifest.example.json" >/dev/null
python3 -c 'import ast, pathlib, sys; ast.parse(pathlib.Path(sys.argv[1]).read_text())' "$runtime"
python3 -m unittest discover -s "$checker_dir/tests" -p 'test_*.py'
"$checker_dir/tests/egress_isolation.sh"

grep -Fq 'ConditionPathExists=/etc/checker-runtime/enabled' "$checker_dir/rootfs/etc/systemd/system/checker-runtime.service"
grep -Fq 'ExecStartPre=/usr/local/libexec/checker-runtime/runtime.py import' "$checker_dir/rootfs/etc/systemd/system/checker-runtime.service"
grep -Fq 'systemctl disable --now checker-runtime.service' "$checker_dir/rootfs/usr/local/sbin/checker-runtime-commission"
grep -Fq 'rm -f /etc/checker-runtime/enabled' "$checker_dir/rootfs/usr/local/sbin/checker-runtime-commission"
grep -Fq '"$runtime" stop' "$checker_dir/rootfs/usr/local/sbin/checker-runtime-commission"
grep -Fq '10.60.201.20' "$runtime"
grep -Fq '127.0.0.1' "$runtime"
! grep -Eq '0\.0\.0\.0:[0-9]+:8000|:latest(["[:space:]]|$)' "$runtime" "$checker_dir/artifact-manifest.example.json"
! grep -RIEq --exclude=run.sh 'H7CTF\{[0-9a-f]{32}\}|BEGIN (OPENSSH |RSA )?PRIVATE KEY|ANVIL_JWT_SECRET=' "$checker_dir"
