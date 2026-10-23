#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
STACK=${1:-}

case "$STACK" in
  oci-addresses | oci-foundation | oci-gateway-builder | oci-gateway-image | oci-ingress | oci-platform | oci-fleet | oci-runtime-builders | oci-runtime-canaries | oci-runtime-images) ;;
  *)
    echo "usage: $0 {oci-addresses|oci-foundation|oci-gateway-builder|oci-gateway-image|oci-ingress|oci-platform|oci-fleet|oci-runtime-builders|oci-runtime-canaries|oci-runtime-images}" >&2
    exit 2
    ;;
esac
[[ $# -eq 1 ]] || { echo "packages are created only from the clean current HEAD" >&2; exit 2; }

[[ -z $(git -C "$ROOT" status --porcelain --untracked-files=normal) ]] || { echo "refusing to package a dirty worktree" >&2; exit 1; }
COMMIT=$(git -C "$ROOT" rev-parse --verify 'HEAD^{commit}')
SHORT_COMMIT=$(git -C "$ROOT" rev-parse --short=12 "$COMMIT")
COMMIT_EPOCH=$(git -C "$ROOT" show -s --format=%ct "$COMMIT")
OUTPUT_DIR="$ROOT/build/terraform"
OUTPUT="$OUTPUT_DIR/${STACK}-${SHORT_COMMIT}.zip"
TEMP_DIR=$(mktemp -d)
trap 'rm -rf "$TEMP_DIR"' EXIT
PACKAGE_DIR="$TEMP_DIR/package"
PATHS=(infra/terraform)

case "$STACK" in
  oci-gateway-builder) PATHS+=(infra/archive infra/images/router infra/platform infra/secrets infra/volumes) ;;
  oci-ingress) PATHS+=(infra/images/router) ;;
  oci-platform) PATHS+=(infra/platform/rootfs/usr/local/libexec/finals-platform/firewall) ;;
  oci-runtime-builders) PATHS+=(infra/archive infra/checkers infra/deployment infra/hills infra/images/runtime infra/platform infra/reconciler infra/secrets infra/team-access infra/volumes) ;;
esac

mkdir -p "$OUTPUT_DIR"
mkdir -p "$PACKAGE_DIR"
git -C "$ROOT" archive --format=tar "$COMMIT" "${PATHS[@]}" | tar -xf - -C "$PACKAGE_DIR"
case "$STACK" in
  oci-gateway-builder | oci-runtime-builders | oci-runtime-canaries)
    printf '%s\n' "$COMMIT" > "$PACKAGE_DIR/infra/terraform/environments/production/$STACK/packaged-source-revision"
    touch --date="@$COMMIT_EPOCH" "$PACKAGE_DIR/infra/terraform/environments/production/$STACK/packaged-source-revision"
    ;;
esac
rm -f -- "$OUTPUT"
(cd "$PACKAGE_DIR" && zip -X -q -r "$OUTPUT" .)
sha256sum "$OUTPUT" >"$OUTPUT.sha256"

echo "$OUTPUT"
echo "working directory: infra/terraform/environments/production/$STACK"
echo "commit: $COMMIT"
