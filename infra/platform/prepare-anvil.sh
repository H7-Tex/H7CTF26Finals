#!/usr/bin/env bash
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "must run as root" >&2; exit 1; }
revision=${1:-}
[[ $revision =~ ^[0-9a-f]{40}$ ]] || { echo "exact 40-character Anvil revision is required" >&2; exit 2; }

release=/opt/anvil/releases/$revision
[[ ! -e $release ]] || { echo "Anvil release path already exists" >&2; exit 1; }
install -d -m 0755 /opt/anvil/releases
temporary=$(mktemp -d /opt/anvil/releases/.build.XXXXXX)
trap 'rm -rf -- "$temporary"' EXIT
git -C "$temporary" init --quiet
git -C "$temporary" remote add origin https://github.com/AbuCTF/Anvil.git
git -C "$temporary" fetch --quiet --depth 1 origin "$revision"
git -C "$temporary" checkout --quiet --detach FETCH_HEAD
[[ $(git -C "$temporary" rev-parse HEAD) == "$revision" ]] || { echo "Anvil revision mismatch" >&2; exit 1; }
TMPDIR=/run "$temporary/deployments/finals/test.sh"
docker build --file "$temporary/deployments/docker/Dockerfile.api" --tag "anvil-finals-api:$revision" "$temporary"
docker build --file "$temporary/deployments/docker/Dockerfile.web" --target production --tag "anvil-finals-web:$revision" "$temporary/web"
while read -r image; do
  docker pull "$image"
done < <(awk '$1 == "image:" && $2 ~ /@sha256:[0-9a-f]{64}$/ { print $2 }' \
  "$temporary/deployments/finals/compose.yaml")
find "$temporary" -type d -exec chmod go-w {} +
find "$temporary" -type f -exec chmod go-w {} +
mv "$temporary" "$release"
trap - EXIT
ln -sfn "releases/$revision" /opt/anvil/current
