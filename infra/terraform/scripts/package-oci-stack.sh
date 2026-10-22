#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
STACK=${1:-}
REVISION=${2:-HEAD}

case "$STACK" in
  oci-addresses | oci-foundation | oci-gateway-builder | oci-gateway-image | oci-ingress | oci-platform | oci-fleet) ;;
  *)
    echo "usage: $0 {oci-addresses|oci-foundation|oci-gateway-builder|oci-gateway-image|oci-ingress|oci-platform|oci-fleet} [git-revision]" >&2
    exit 2
    ;;
esac

COMMIT=$(git -C "$ROOT" rev-parse --verify "${REVISION}^{commit}")
SHORT_COMMIT=$(git -C "$ROOT" rev-parse --short=12 "$COMMIT")
OUTPUT_DIR="$ROOT/build/terraform"
OUTPUT="$OUTPUT_DIR/${STACK}-${SHORT_COMMIT}.zip"
TEMP_DIR=$(mktemp -d)
trap 'rm -rf "$TEMP_DIR"' EXIT
PATHS=(infra/terraform)

if [[ $STACK == oci-gateway-builder ]]; then
  PATHS+=(infra/images/router)
fi

mkdir -p "$OUTPUT_DIR"
git -C "$ROOT" archive --format=zip --output "$TEMP_DIR/stack.zip" "$COMMIT" "${PATHS[@]}"
mv "$TEMP_DIR/stack.zip" "$OUTPUT"
sha256sum "$OUTPUT" >"$OUTPUT.sha256"

echo "$OUTPUT"
echo "working directory: infra/terraform/environments/production/$STACK"
echo "commit: $COMMIT"
