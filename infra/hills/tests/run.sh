#!/usr/bin/env bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

hill_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
bash -n "$hill_dir/install.sh" "$hill_dir/tests/run.sh"
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
  done
fi
