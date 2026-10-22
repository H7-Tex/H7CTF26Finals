#!/usr/bin/env bash
set -euo pipefail

image='mongo@sha256:c53852c00c23ca9f23fc39690350ffa9a80e3642fe8f96879726d8da0abe80a7'
if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1 || ! docker image inspect "$image" >/dev/null 2>&1; then
  echo "checker egress isolation test skipped: pinned image or container engine is unavailable"
  exit 0
fi

suffix="$$-${RANDOM}"
network="checker-icc-test-${suffix}"
target="checker-icc-target-${suffix}"
source="checker-icc-source-${suffix}"
cleanup() {
  docker container rm --force "$source" "$target" >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker network create \
  --driver bridge \
  --opt com.docker.network.bridge.enable_icc=false \
  "$network" >/dev/null
[[ $(docker network inspect --format '{{index .Options "com.docker.network.bridge.enable_icc"}}' "$network") == false ]]

docker run --detach --name "$target" --network "$network" "$image" \
  mongod --bind_ip_all --quiet >/dev/null
docker run --detach --name "$source" --network "$network" --entrypoint /bin/sh "$image" \
  -c 'sleep 120' >/dev/null

ready=false
for _ in $(seq 1 30); do
  if docker exec "$target" mongosh --quiet --eval 'quit(db.runCommand({ping:1}).ok ? 0 : 1)' >/dev/null 2>&1; then
    ready=true
    break
  fi
  sleep 1
done
[[ $ready == true ]] || { echo "checker egress isolation target did not become ready" >&2; exit 1; }

if docker exec "$source" mongosh --quiet "mongodb://${target}:27017/?serverSelectionTimeoutMS=2000&connectTimeoutMS=2000" --eval 'quit(db.runCommand({ping:1}).ok ? 0 : 1)' >/dev/null 2>&1; then
  echo "checker egress bridge permits inter-container traffic" >&2
  exit 1
fi

echo "checker egress isolation test passed"
