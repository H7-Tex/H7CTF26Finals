#!/usr/bin/env bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

archive_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
bash -n "$archive_dir/install.sh" "$archive_dir/finals-archive-egress" "$archive_dir/tests/run.sh"
python3 -m unittest discover -s "$archive_dir/tests" -p 'test_*.py'
python3 -c 'import ast,pathlib; ast.parse(pathlib.Path("'$archive_dir'/finals-archive.py").read_text())'
! grep -E 'service_account.*key|private_key_data|credentials[[:space:]]*=' \
  "$archive_dir/finals-archive.py" \
  "$archive_dir/finals-archive-egress" \
  "$archive_dir/install.sh"
