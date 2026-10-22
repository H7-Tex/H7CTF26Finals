#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
TF_DIR="$ROOT/infra/terraform"

terraform fmt -check -recursive "$TF_DIR"

while IFS= read -r dir; do
  echo "validating ${dir#$ROOT/}"
  TF_IN_AUTOMATION=1 terraform -chdir="$dir" init \
    -backend=false \
    -input=false \
    -no-color >/dev/null
  TF_IN_AUTOMATION=1 terraform -chdir="$dir" validate -no-color
done < <(find "$TF_DIR" -type f -name '*.tf' -printf '%h\n' | sort -u)
