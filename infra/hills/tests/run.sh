#!/usr/bin/env bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

hill_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
bash -n "$hill_dir/install.sh" "$hill_dir/tests/run.sh" "$hill_dir/finals-hill-compose"
python3 -m unittest discover -s "$hill_dir/tests" -p 'test_*.py'
python3 -m py_compile "$hill_dir/credential_sync.py"

grep -Fq 'ANVIL_ADDRESS = "10.60.200.10"' "$hill_dir/credential_sync.py"
grep -Fq 'PrivateHTTPSConnection(ANVIL_HOST, 443' "$hill_dir/credential_sync.py"
grep -Fq 'Authorization": "Bearer " + token' "$hill_dir/credential_sync.py"
grep -Fq 'ReadWritePaths=/run/finals-hill' "$hill_dir/finals-hill-credentials.service"
! grep -Eq 'Environment=.*(TOKEN|SECRET|CREDENTIAL)' "$hill_dir/finals-hill-credentials.service"
[[ $(grep -Ec '^  hill_(reset|teams):$' "$hill_dir/credentials.compose.yaml") == 2 ]]
[[ $(grep -Ec '^    file: /run/finals-hill/credentials/current/hill_(reset|teams)$' "$hill_dir/credentials.compose.yaml") == 2 ]]
[[ $(grep -Fhc 'subnet: 172.31.41.0/24' "$hill_dir/hill-01.networks.compose.yaml") == 1 ]]
[[ $(grep -Ec 'subnet: 172\.31\.(42|43)\.0/24' "$hill_dir/hill-02.networks.compose.yaml") == 2 ]]
[[ $(grep -Fhc 'subnet: 172.31.44.0/24' "$hill_dir/hill-03.networks.compose.yaml") == 1 ]]
for n in 1 2 3; do
  [[ $(grep -c '^    internal: false$' "$hill_dir/hill-0$n.networks.compose.yaml") == 1 ]]
  [[ $(grep -c '^      com.docker.network.bridge.enable_ip_masquerade: "false"$' "$hill_dir/hill-0$n.networks.compose.yaml") == 1 ]]
done
# each hill publishes exactly its own fixed listener, and the launcher always uses all four files
for n in 1 2 3; do
  [[ $(grep -Ec '^      - "10\.60\.210\.1'"$n"':710'"$n"':710'"$n"'"$' "$hill_dir/hill-0$n.endpoint.compose.yaml") == 1 ]]
  [[ $(grep -c '^      - ' "$hill_dir/hill-0$n.endpoint.compose.yaml") == 1 ]]
done
for file in /opt/finals-hill/compose.yaml /etc/finals-hill/credentials.compose.yaml '/etc/finals-hill/$role.networks.compose.yaml' '/etc/finals-hill/$role.endpoint.compose.yaml'; do
  grep -Fq -- "--file $file" "$hill_dir/finals-hill-compose" || grep -Fq -- "--file \"$file\"" "$hill_dir/finals-hill-compose"
done
! grep -Eq 'down (-v|--volumes)' "$hill_dir/finals-hill-compose"
[[ $(grep -Ec '^    file: /run/finals-hill/evm/mnemonic$' "$hill_dir/hill-02.evm.compose.yaml") == 1 ]]
[[ $(grep -Fc -- '--file /etc/finals-hill/hill-02.evm.compose.yaml' "$hill_dir/finals-hill-compose") == 1 ]]
grep -Fq 'hill-02.evm.compose.yaml' "$hill_dir/install.sh"

if docker compose version >/dev/null 2>&1; then
  rendered=$(docker compose \
    --file "$hill_dir/tests/compose.fixture.yaml" \
    --file "$hill_dir/credentials.compose.yaml" \
    config)
  [[ $rendered == *'/run/finals-hill/credentials/current/hill_reset'* ]]
  [[ $rendered == *'/run/finals-hill/credentials/current/hill_teams'* ]]
  [[ $rendered != *'external: true'* ]]
  for role in hill-01 hill-02 hill-03; do
    docker compose \
      --file "$hill_dir/tests/compose.fixture.yaml" \
      --file "$hill_dir/$role.networks.compose.yaml" \
      config >/dev/null
    n=${role#hill-0}
    published=$(docker compose \
      --file "$hill_dir/tests/compose.fixture.yaml" \
      --file "$hill_dir/credentials.compose.yaml" \
      --file "$hill_dir/$role.networks.compose.yaml" \
      --file "$hill_dir/$role.endpoint.compose.yaml" \
      config --format json | python3 -c 'import json,sys; p=json.load(sys.stdin)["services"]["arena"]["ports"]; print(len(p), p[0]["host_ip"], p[0]["published"], p[0]["target"])')
    [[ $published == "1 10.60.210.1$n 710$n 710$n" ]]
  done
  # the full hill-02 file set leaves no external secret, so up can start the evm
  rendered=$(docker compose \
    --file "$hill_dir/tests/hill-02.fixture.yaml" \
    --file "$hill_dir/credentials.compose.yaml" \
    --file "$hill_dir/hill-02.networks.compose.yaml" \
    --file "$hill_dir/hill-02.endpoint.compose.yaml" \
    --file "$hill_dir/hill-02.evm.compose.yaml" \
    config)
  [[ $rendered == *'/run/finals-hill/evm/mnemonic'* ]]
  [[ $rendered != *'external: true'* ]]
fi
