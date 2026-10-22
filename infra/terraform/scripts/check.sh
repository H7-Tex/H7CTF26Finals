#!/usr/bin/env bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
TF_DIR="$ROOT/infra/terraform"

terraform fmt -check -recursive "$TF_DIR"
bash -n "$TF_DIR/scripts/install-verified-build-payload"
python3 -m unittest discover -s "$TF_DIR/tests" -p 'test_*.py'

while IFS= read -r dir; do
  echo "validating ${dir#$ROOT/}"
  TF_IN_AUTOMATION=1 terraform -chdir="$dir" init \
    -backend=false \
    -input=false \
    -no-color >/dev/null
  TF_IN_AUTOMATION=1 terraform -chdir="$dir" validate -no-color
done < <(find "$TF_DIR" -type f -name '*.tf' -printf '%h\n' | sort -u)
