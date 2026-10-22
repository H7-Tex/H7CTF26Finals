#!/usr/bin/env bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

volume_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
python3 -m unittest discover -s "$volume_dir/tests" -p 'test_*.py'
python3 -c 'import ast, pathlib, sys; ast.parse(pathlib.Path(sys.argv[1]).read_text())' \
  "$volume_dir/initialize-volume.py"
unit=$(mktemp --suffix=.service)
trap 'rm -f "$unit"' EXIT
sed 's#ExecStart=/usr/local/sbin/finals-initialize-volume %i#ExecStart=/usr/bin/true#' \
  "$volume_dir/finals-volume@.service" > "$unit"
systemd-analyze verify "$unit"
