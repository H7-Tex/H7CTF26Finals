#!/usr/bin/env bash
set -euo pipefail

secret_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
# shellcheck source=/dev/null
source "$secret_dir/finals-secret-relay-receive"

[[ $(requested_bundle gateway 'install gateway-wireguard') == gateway-wireguard ]]
[[ $(requested_bundle gateway 'install gateway-reconciler') == gateway-reconciler ]]
[[ $(requested_bundle platform 'install anvil') == anvil ]]
[[ $(requested_bundle control 'install control-reconciler') == control-reconciler ]]
[[ $(requested_bundle repository 'install repository') == repository ]]

! requested_bundle platform 'install repository'
! requested_bundle repository 'install anvil'
! requested_bundle mirror 'install repository'
! requested_bundle hill-01 'install anvil'
! requested_bundle gateway 'install gateway-wireguard extra'
! requested_bundle gateway 'sh -c id'
! requested_bundle gateway ''
