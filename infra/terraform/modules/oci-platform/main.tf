locals {
  hosts = {
    platform = {
      private_ip   = "10.60.200.10"
      subnet       = "services"
      shape        = "VM.Standard.E4.Flex"
      architecture = "x86"
      ocpus        = 4
      memory_gb    = 16
      boot_gb      = 150
    }
    operations = {
      private_ip   = "10.60.200.5"
      subnet       = "services"
      shape        = "VM.Standard.A1.Flex"
      architecture = "arm"
      ocpus        = 2
      memory_gb    = 8
      boot_gb      = 50
    }
    control = {
      private_ip   = "10.60.201.20"
      subnet       = "core"
      shape        = "VM.Standard.E4.Flex"
      architecture = "x86"
      ocpus        = 8
      memory_gb    = 32
      boot_gb      = 150
    }
    repository = {
      private_ip   = "10.60.201.30"
      subnet       = "core"
      shape        = "VM.Standard.A1.Flex"
      architecture = "arm"
      ocpus        = 2
      memory_gb    = 8
      boot_gb      = 50
    }
    mirror = {
      private_ip   = "10.60.202.10"
      subnet       = "mirror"
      shape        = "VM.Standard.A1.Flex"
      architecture = "arm"
      ocpus        = 4
      memory_gb    = 16
      boot_gb      = 50
    }
    hill-01 = {
      private_ip   = "10.60.210.11"
      subnet       = "hills"
      shape        = "VM.Standard.E4.Flex"
      architecture = "x86"
      ocpus        = 2
      memory_gb    = 16
      boot_gb      = 150
    }
    hill-02 = {
      private_ip   = "10.60.210.12"
      subnet       = "hills"
      shape        = "VM.Standard.E4.Flex"
      architecture = "x86"
      ocpus        = 2
      memory_gb    = 16
      boot_gb      = 150
    }
    hill-03 = {
      private_ip   = "10.60.210.13"
      subnet       = "hills"
      shape        = "VM.Standard.E4.Flex"
      architecture = "x86"
      ocpus        = 2
      memory_gb    = 16
      boot_gb      = 150
    }
  }

  tags = {
    event      = "finals-2026"
    managed_by = "terraform"
  }

  operations_relay_authorized_key = "restrict,command=\"/usr/local/sbin/finals-secret-relay-receive\" ${var.operations_relay_ssh_public_key}"
  operations_relay_roles          = toset(["platform", "control", "repository"])

  operations_commission_initializer_sha256         = "eaeb4c33d2c94f59dee9b01b2b6dbce8e8f8adf720e4108f713456f7cf4f69ab"
  operations_commission_anvil_sha256               = "c760f5097b671cfa1423bd30b407cbbc9cb415fe4a82510d84c9120818143a19"
  operations_commission_script                     = <<-SCRIPT
    #!/usr/bin/env bash
    set -euo pipefail

    [[ $EUID -eq 0 ]] || { echo "commissioning wrapper must run as root" >&2; exit 1; }
    [[ $(cat /etc/finals-platform/role 2>/dev/null) == '{"role":"operations"}' ]] || {
      echo "commissioning wrapper is restricted to the operations host" >&2
      exit 1
    }
    target=$${1:-}
    action=$${2:-}
    [[ $# -eq 2 && $action == volume-initialize ]] || {
      echo "usage: finals-commission-volume {platform|gateway-primary|gateway-standby} volume-initialize" >&2
      exit 2
    }
    case "$target" in
      platform)
        address=10.60.200.10
        post_command='set -Eeuo pipefail; sudo systemctl restart finals-volume@anvil.service; mountpoint -q /srv/anvil; [[ $(sudo stat -c "%u:%g:%a" /srv/anvil/postgres) == 70:70:700 ]]; [[ $(sudo stat -c "%u:%g:%a" /srv/anvil/storage) == 0:0:700 ]]; [[ $(sudo stat -c "%u:%g:%a" /srv/anvil/backups) == 0:0:700 ]]; sudo test -s /etc/anvil/finals.env; sudo test -s /etc/anvil/tls/fullchain.pem; sudo test -s /etc/anvil/tls/privkey.pem; sudo /opt/anvil/current/deployments/finals/preflight.sh; sudo systemctl enable anvil-finals.service anvil-finals-backup.timer; sudo systemctl restart anvil-finals.service; sudo systemctl start anvil-finals-backup.timer; sudo systemctl is-active --quiet anvil-finals.service; curl --fail --silent --show-error --output /dev/null --connect-timeout 5 --max-time 15 --proto "=https" --tlsv1.2 --resolve finals.h7tex.com:443:10.60.200.10 https://finals.h7tex.com/; migration_ok=$(sudo /usr/bin/docker compose --project-name anvil-finals --project-directory /opt/anvil/current/deployments/finals --env-file /etc/anvil/finals.env -f /opt/anvil/current/deployments/finals/compose.yaml exec -T postgres psql --username anvil --dbname anvil --tuples-only --no-align --command "SELECT (COUNT(*) > 0 AND COUNT(*) FILTER (WHERE name IS NULL OR checksum IS NULL) = 0)::text FROM schema_migrations;"); [[ $migration_ok == t ]]; backup_before=$(sudo find /srv/anvil/backups -mindepth 1 -maxdepth 1 -type d -name "anvil-*" -printf "." | wc -c); sudo systemctl start anvil-finals-backup.service; [[ $(sudo systemctl show --property=Result --value anvil-finals-backup.service) == success ]]; backup_after=$(sudo find /srv/anvil/backups -mindepth 1 -maxdepth 1 -type d -name "anvil-*" -printf "." | wc -c); [[ $backup_after -gt $backup_before ]]; latest_backup=$(sudo find /srv/anvil/backups -mindepth 1 -maxdepth 1 -type d -name "anvil-*" -printf "%T@ %p\n" | sort -n | tail -n 1 | cut -d " " -f 2-); [[ -n $latest_backup && $(sudo stat -c "%u:%g:%a" "$latest_backup") == 0:0:700 ]]; sudo test -s "$latest_backup/database.dump"; sudo test -s "$latest_backup/storage.tar.gz"; sudo test -s "$latest_backup/SHA256SUMS"'
        ;;
      gateway-primary)
        address=10.60.250.10
        post_command='sudo systemctl restart finals-volume@captures.service && mountpoint -q /srv/captures && sudo systemctl restart event-router-flow-log.service event-router-activate.service'
        ;;
      gateway-standby)
        address=10.60.250.11
        post_command='printf "%s  %s\n" "${local.operations_commission_initializer_sha256}" /usr/local/sbin/finals-initialize-volume | sha256sum -c - >/dev/null'
        ;;
    esac

    temporary=$(mktemp /run/finals-volume-initialize.XXXXXX)
    trap 'rm -f -- "$temporary"' EXIT
    cat > "$temporary"
    printf '%s  %s\n' "${local.operations_commission_initializer_sha256}" "$temporary" | sha256sum -c - >/dev/null

    ssh_options=(
      -F /dev/null
      -i /run/finals-commissioning/central_id_ed25519
      -o BatchMode=yes
      -o ConnectTimeout=10
      -o IdentitiesOnly=yes
      -o PasswordAuthentication=no
      -o StrictHostKeyChecking=yes
      -o UserKnownHostsFile=/etc/finals-platform/operations/known_hosts
    )
    /usr/bin/ssh "$${ssh_options[@]}" -- "ubuntu@$address" \
      'sudo install -D -m 0755 /dev/stdin /usr/local/sbin/finals-initialize-volume' < "$temporary"
    /usr/bin/ssh "$${ssh_options[@]}" -- "ubuntu@$address" "$post_command"
  SCRIPT
  operations_commission_secret_script              = <<-SCRIPT
    #!/usr/bin/env bash
    set -euo pipefail

    [[ $EUID -eq 0 ]] || { echo "secret commissioning wrapper must run as root" >&2; exit 1; }
    [[ $(cat /etc/finals-platform/role 2>/dev/null) == '{"role":"operations"}' ]] || {
      echo "secret commissioning wrapper is restricted to the operations host" >&2
      exit 1
    }
    [[ $# -eq 2 && $1 == platform && $2 == anvil ]] || {
      echo "usage: finals-commission-secret platform anvil" >&2
      exit 2
    }
    temporary=$(mktemp /run/finals-anvil-secret.XXXXXX)
    trap 'rm -f -- "$temporary"' EXIT
    cat > "$temporary"
    printf '%s  %s\n' "${local.operations_commission_anvil_sha256}" "$temporary" | sha256sum -c - >/dev/null
    exec /usr/bin/ssh \
      -F /dev/null \
      -i /run/finals-commissioning/central_id_ed25519 \
      -o BatchMode=yes \
      -o ConnectTimeout=10 \
      -o IdentitiesOnly=yes \
      -o PasswordAuthentication=no \
      -o StrictHostKeyChecking=yes \
      -o UserKnownHostsFile=/etc/finals-platform/operations/known_hosts \
      -- ubuntu@10.60.200.10 \
      'sudo chmod 0644 /etc/ssh/operations_relay_authorized_keys_ubuntu && sudo /usr/sbin/sshd -t && sudo systemctl reload ssh.service && sudo /usr/local/sbin/finals-install-secret-bundle anvil' < "$temporary"
  SCRIPT
  operations_commission_control_action_script      = <<-SCRIPT
    #!/usr/bin/env bash
    set -euo pipefail

    [[ $EUID -eq 0 ]] || { echo "control action wrapper must run as root" >&2; exit 1; }
    [[ $(cat /etc/finals-platform/role 2>/dev/null) == '{"role":"operations"}' ]] || exit 1
    [[ -f /run/finals-commissioning/central_id_ed25519 && ! -L /run/finals-commissioning/central_id_ed25519 ]] || exit 1
    [[ $# -eq 1 ]] || { echo "usage: finals-commission-control-action ACTION" >&2; exit 2; }
    case "$1" in
      reconcile-once)
        remote='set -euo pipefail; sudo -n systemctl start peer-reconciler.service; [[ $(sudo -n systemctl show --property=Result --value peer-reconciler.service) == success ]]; echo peer-reconciler-once=success'
        ;;
      reconciler-enable)
        remote='set -euo pipefail; sudo -n systemctl enable --now peer-reconciler.timer >/dev/null; sudo -n systemctl is-active --quiet peer-reconciler.timer; echo peer-reconciler-timer=active'
        ;;
      control-status)
        remote='set -euo pipefail; for unit in checker-runtime.service peer-reconciler.service peer-reconciler.timer; do state=$(sudo -n systemctl is-active "$unit" 2>/dev/null || true); case "$state" in active|inactive|failed|activating|deactivating) ;; *) state=unknown ;; esac; printf "%s=%s\n" "$unit" "$state"; done; if curl --fail --silent --output /dev/null --connect-timeout 2 --max-time 3 http://127.0.0.1:9160/readyz; then echo checker-ready=yes; else echo checker-ready=no; fi'
        ;;
      *) echo "unsupported fixed control action" >&2; exit 2 ;;
    esac
    /usr/bin/ssh \
      -F /dev/null \
      -i /run/finals-commissioning/central_id_ed25519 \
      -o BatchMode=yes \
      -o ConnectTimeout=10 \
      -o IdentitiesOnly=yes \
      -o PasswordAuthentication=no \
      -o StrictHostKeyChecking=yes \
      -o UserKnownHostsFile=/etc/finals-platform/operations/known_hosts \
      -- ubuntu@10.60.201.20 "$remote"
  SCRIPT
  operations_commission_control_secret_script      = <<-SCRIPT
    #!/usr/bin/env bash
    set -euo pipefail

    [[ $EUID -eq 0 ]] || { echo "control secret commissioning must run as root" >&2; exit 1; }
    [[ $(cat /etc/finals-platform/role 2>/dev/null) == '{"role":"operations"}' ]] || exit 1
    [[ -f /run/finals-commissioning/central_id_ed25519 && ! -L /run/finals-commissioning/central_id_ed25519 ]] || exit 1
    [[ $# -eq 1 ]] || { echo "usage: finals-commission-control-secret BUNDLE" >&2; exit 2; }
    case "$1" in
      control-reconciler|control-checkers) bundle=$1 ;;
      *) echo "unsupported fixed control secret bundle" >&2; exit 2 ;;
    esac
    temporary=$(mktemp /run/finals-control-secret.XXXXXX)
    trap 'rm -f -- "$temporary"' EXIT
    dd bs=65537 count=1 status=none > "$temporary"
    [[ -s $temporary && $(stat -c '%s' "$temporary") -le 65536 ]] || exit 1
    /usr/bin/ssh \
      -F /dev/null \
      -i /run/finals-commissioning/central_id_ed25519 \
      -o BatchMode=yes \
      -o ConnectTimeout=10 \
      -o IdentitiesOnly=yes \
      -o PasswordAuthentication=no \
      -o StrictHostKeyChecking=yes \
      -o UserKnownHostsFile=/etc/finals-platform/operations/known_hosts \
      -- ubuntu@10.60.201.20 "sudo -n /usr/local/sbin/finals-install-secret-bundle $bundle" < "$temporary"
  SCRIPT
  operations_commission_host_firewall_script       = <<-SCRIPT
    #!/usr/bin/env bash
    set -euo pipefail

    [[ $EUID -eq 0 ]] || { echo "host firewall commissioning must run as root" >&2; exit 1; }
    [[ $(cat /etc/finals-platform/role 2>/dev/null) == '{"role":"operations"}' ]] || exit 1
    central=/run/finals-commissioning/central_id_ed25519
    [[ -f $central && ! -L $central && $# -eq 1 ]] || {
      echo "usage: finals-commission-host-firewall TARGET" >&2
      exit 2
    }
    target=$1
    case "$target" in
      platform) address=10.60.200.10; port=22; role=platform ;;
      control) address=10.60.201.20; port=22; role=control ;;
      repository) address=10.60.201.30; port=2222; role=repository ;;
      mirror) address=10.60.202.10; port=22; role=mirror ;;
      hill-01) address=10.60.210.11; port=22; role=hill-01 ;;
      hill-02) address=10.60.210.12; port=22; role=hill-02 ;;
      hill-03) address=10.60.210.13; port=22; role=hill-03 ;;
      production-0[1-9]|production-1[0-6])
        number=$${target#production-}
        address="10.60.$((10#$number)).2"
        port=22
        role=production
        ;;
      *) echo "unsupported fixed firewall target" >&2; exit 2 ;;
    esac
    expected_host=$address
    [[ $port -eq 22 ]] || expected_host="[$address]:$port"
    work=$(mktemp -d /run/finals-host-firewall.XXXXXX)
    trap 'rm -rf -- "$work"' EXIT
    IFS= read -r host type key extra
    [[ $host == "$expected_host" && $type == ssh-ed25519 && $key =~ ^[A-Za-z0-9+/]{68}$ && -z $${extra:-} ]] || {
      echo "host key line is invalid for the fixed target" >&2
      exit 1
    }
    printf '%s %s %s\n' "$host" "$type" "$key" > "$work/known_hosts"
    printf '%s' '${base64gzip(file("${path.module}/../../../platform/rootfs/usr/local/libexec/finals-platform/firewall"))}' | base64 -d | gzip -d > "$work/firewall"
    [[ $(sha256sum "$work/firewall" | awk '{print $1}') == '${filesha256("${path.module}/../../../platform/rootfs/usr/local/libexec/finals-platform/firewall")}' ]]
    remote="set -euo pipefail
      [[ \$(cat /etc/finals-platform/role 2>/dev/null) == '{\"role\":\"$role\"}' ]]
      temporary=/run/finals-host-firewall.next
      trap 'sudo -n rm -f -- \"\$temporary\"' EXIT
      sudo -n install -o root -g root -m 0755 /dev/stdin \"\$temporary\"
      echo '${filesha256("${path.module}/../../../platform/rootfs/usr/local/libexec/finals-platform/firewall")}  '\"\$temporary\" | sudo -n sha256sum -c --quiet
      sudo -n \"\$temporary\" --render '$role' | sudo -n nft --check --file -
      sudo -n install -o root -g root -m 0755 \"\$temporary\" /usr/local/libexec/finals-platform/firewall
      sudo -n systemctl restart finals-host-firewall.service
      sudo -n systemctl is-active --quiet finals-host-firewall.service
      echo '${filesha256("${path.module}/../../../platform/rootfs/usr/local/libexec/finals-platform/firewall")}  /usr/local/libexec/finals-platform/firewall' | sudo -n sha256sum -c --quiet
      printf '%s firewall-applied ${filesha256("${path.module}/../../../platform/rootfs/usr/local/libexec/finals-platform/firewall")}\n' '$target'"
    exec /usr/bin/ssh \
      -F /dev/null \
      -i "$central" \
      -p "$port" \
      -o BatchMode=yes \
      -o ConnectTimeout=10 \
      -o IdentitiesOnly=yes \
      -o PasswordAuthentication=no \
      -o StrictHostKeyChecking=yes \
      -o UserKnownHostsFile="$work/known_hosts" \
      -- "ubuntu@$address" "$remote" < "$work/firewall"
  SCRIPT
  operations_commission_stage_central_script       = <<-SCRIPT
    #!/usr/bin/env bash
    set -euo pipefail

    [[ $EUID -eq 0 ]] || { echo "central staging must run as root" >&2; exit 1; }
    [[ $(cat /etc/finals-platform/role 2>/dev/null) == '{"role":"operations"}' ]] || {
      echo "central staging is restricted to the operations host" >&2
      exit 1
    }
    [[ $# -eq 0 ]] || { echo "central staging takes no arguments" >&2; exit 2; }
    event_key=/etc/finals-platform/operations/id_ed25519
    event_hosts=/etc/finals-platform/operations/known_hosts
    [[ -f $event_key && ! -L $event_key && -f $event_hosts && ! -L $event_hosts ]] || {
      echo "persistent event relay identity is not commissioned" >&2
      exit 1
    }
    event_fingerprint=$(ssh-keygen -yf "$event_key" | ssh-keygen -lf - -E sha256 | awk '{print $2}')
    [[ $event_fingerprint == 'SHA256:cdz/qtyNUAL19bQV2ey1KgT3f6CCYXvML2CWI069bHA' ]] || {
      echo "persistent event relay fingerprint is not authorized" >&2
      exit 1
    }
    [[ $(findmnt -n -o FSTYPE /run) == tmpfs ]]
    [[ ! -e /run/finals-commissioning || (-d /run/finals-commissioning && ! -L /run/finals-commissioning) ]]
    work=$(mktemp -d /run/finals-central-stage.XXXXXX)
    trap 'find "$work" -depth -delete' EXIT
    dd bs=65537 count=1 status=none > "$work/bundle.age"
    [[ -s $work/bundle.age && $(stat -c '%s' "$work/bundle.age") -le 65536 ]] || {
      echo "central ciphertext has an invalid size" >&2
      exit 1
    }
    age --decrypt --identity /etc/ssh/ssh_host_ed25519_key < "$work/bundle.age" > "$work/bundle.json"
    python3 - "$work/bundle.json" "$work/key" <<'PY'
    import base64
    import json
    import os
    import sys
    document = json.load(open(sys.argv[1], encoding="utf-8"))
    if set(document) != {"type", "files"} or document["type"] != "operations-relay":
        raise SystemExit("central bundle has an invalid envelope")
    files = document["files"]
    if not isinstance(files, dict) or set(files) != {"ssh_private_key", "known_hosts"}:
        raise SystemExit("central bundle has an invalid file set")
    key = base64.b64decode(files["ssh_private_key"], validate=True)
    if not key.startswith(b"-----BEGIN OPENSSH PRIVATE KEY-----\n") or len(key) > 4096:
        raise SystemExit("central private key is malformed")
    descriptor = os.open(sys.argv[2], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(key)
    PY
    fingerprint=$(ssh-keygen -yf "$work/key" | ssh-keygen -lf - -E sha256 | awk '{print $2}')
    [[ $fingerprint == 'SHA256:dfPMQE51IWgeI/TQvWs+zgCNU1dyZhpMBnQap/pmA0I' ]] || {
      echo "central key fingerprint is not authorized" >&2
      exit 1
    }
    install -d -o root -g root -m 0700 /run/finals-commissioning
    install -o root -g root -m 0600 "$work/key" /run/finals-commissioning/central_id_ed25519
    echo central-staged-in-tmpfs
  SCRIPT
  operations_commission_clear_central_script       = <<-SCRIPT
    #!/usr/bin/env bash
    set -euo pipefail

    [[ $EUID -eq 0 ]] || { echo "central clearing must run as root" >&2; exit 1; }
    [[ $(cat /etc/finals-platform/role 2>/dev/null) == '{"role":"operations"}' ]] || exit 1
    [[ $# -eq 0 ]] || { echo "central clearing takes no arguments" >&2; exit 2; }
    rm -f -- /run/finals-commissioning/central_id_ed25519
    test ! -e /run/finals-commissioning/central_id_ed25519
  SCRIPT
  operations_commission_gateway_secret_script      = <<-SCRIPT
    #!/usr/bin/env bash
    set -euo pipefail

    [[ $EUID -eq 0 ]] || { echo "gateway secret commissioning must run as root" >&2; exit 1; }
    [[ $(cat /etc/finals-platform/role 2>/dev/null) == '{"role":"operations"}' ]] || exit 1
    [[ -f /run/finals-commissioning/central_id_ed25519 && ! -L /run/finals-commissioning/central_id_ed25519 ]] || exit 1
    [[ $# -eq 2 ]] || { echo "usage: finals-commission-gateway-secret TARGET BUNDLE" >&2; exit 2; }
    case "$1:$2" in
      gateway-primary:gateway-wireguard) address=10.60.250.10; bundle=gateway-wireguard ;;
      gateway-primary:gateway-reconciler) address=10.60.250.10; bundle=gateway-reconciler ;;
      gateway-standby:gateway-wireguard) address=10.60.250.11; bundle=gateway-wireguard ;;
      gateway-standby:gateway-reconciler) address=10.60.250.11; bundle=gateway-reconciler ;;
      *) echo "unsupported fixed gateway secret target" >&2; exit 2 ;;
    esac
    temporary=$(mktemp /run/finals-gateway-secret.XXXXXX)
    trap 'rm -f -- "$temporary"' EXIT
    dd bs=65537 count=1 status=none > "$temporary"
    [[ -s $temporary && $(stat -c '%s' "$temporary") -le 65536 ]] || exit 1
    ssh -F /dev/null -i /run/finals-commissioning/central_id_ed25519 \
      -o BatchMode=yes -o ConnectTimeout=10 -o IdentitiesOnly=yes -o PasswordAuthentication=no \
      -o StrictHostKeyChecking=yes -o UserKnownHostsFile=/etc/finals-platform/operations/known_hosts \
      -- "ubuntu@$address" "sudo -n /usr/local/sbin/finals-install-secret-bundle $bundle" < "$temporary"
  SCRIPT
  operations_commission_gateway_authorizer_script  = <<-SCRIPT
    #!/usr/bin/env bash
    set -euo pipefail

    [[ $EUID -eq 0 ]] || exit 1
    [[ $(cat /etc/finals-platform/role 2>/dev/null) == '{"role":"operations"}' ]] || exit 1
    [[ -f /run/finals-commissioning/central_id_ed25519 && ! -L /run/finals-commissioning/central_id_ed25519 ]] || exit 1
    [[ $# -eq 1 ]] || exit 2
    case "$1" in
      gateway-primary) address=10.60.250.10 ;;
      gateway-standby) address=10.60.250.11 ;;
      *) echo "unsupported fixed gateway authorizer target" >&2; exit 2 ;;
    esac

    exec /usr/bin/ssh \
      -F /dev/null \
      -i /run/finals-commissioning/central_id_ed25519 \
      -o BatchMode=yes \
      -o ConnectTimeout=10 \
      -o IdentitiesOnly=yes \
      -o PasswordAuthentication=no \
      -o StrictHostKeyChecking=yes \
      -o UserKnownHostsFile=/etc/finals-platform/operations/known_hosts \
      -- "ubuntu@$address" \
      'sudo -n /usr/local/sbin/event-router-authorize-reconciler /etc/event-router/reconciler_authorized_key'
  SCRIPT
  operations_commission_gateway_role_script        = <<-SCRIPT
    #!/usr/bin/env bash
    set -euo pipefail

    [[ $EUID -eq 0 ]] || { echo "gateway role repair must run as root" >&2; exit 1; }
    [[ $(cat /etc/finals-platform/role 2>/dev/null) == '{"role":"operations"}' ]] || {
      echo "gateway role repair is restricted to the operations host" >&2
      exit 1
    }
    [[ -f /run/finals-commissioning/central_id_ed25519 && ! -L /run/finals-commissioning/central_id_ed25519 ]] || exit 1
    [[ $# -eq 1 ]] || { echo "usage: finals-commission-gateway-role {gateway-primary|gateway-standby}" >&2; exit 2; }
    case "$1" in
      gateway-primary)
        address=10.60.250.10
        expected=active
        expected_instance=ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goac3ig6mf6qsd4ax7yacftguhu2qhvn3rjeili2qhmw2kjq
        expected_name=gateway-primary
        ;;
      gateway-standby)
        address=10.60.250.11
        expected=standby
        expected_instance=ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goacxgdwf25buf5ollmxlnw4e77g4y6coln6aqw2uvmovssq
        expected_name=gateway-standby
        ;;
      *) echo "unsupported fixed gateway target" >&2; exit 2 ;;
    esac

    /usr/bin/ssh \
      -F /dev/null \
      -i /run/finals-commissioning/central_id_ed25519 \
      -o BatchMode=yes \
      -o ConnectTimeout=10 \
      -o IdentitiesOnly=yes \
      -o PasswordAuthentication=no \
      -o StrictHostKeyChecking=yes \
      -o UserKnownHostsFile=/etc/finals-platform/operations/known_hosts \
      -- "ubuntu@$address" 'set -euo pipefail
        metadata=$(curl --fail --silent --show-error --connect-timeout 2 --max-time 5 \
          -H "Authorization: Bearer Oracle" http://169.254.169.254/opc/v2/instance/)
        python3 -c "import json,sys; d=json.load(sys.stdin); expected=dict(zip((\"id\",\"image\",\"displayName\"),sys.argv[1:])); raise SystemExit(0 if all(d.get(k)==v for k,v in expected.items()) else 1)" \
          "'$expected_instance'" \
          ocid1.image.oc1.ap-hyderabad-1.aaaaaaaaoufvtqzgsc5kacdw6vlxmvre7mvozuwucuyknlm72mhrrojf5hsa \
          "'$expected_name'" <<<"$metadata"
        initializer=/usr/local/sbin/event-router-initialize
        [[ -f $initializer && ! -L $initializer ]]
        read -r initializer_sha _ < <(sha256sum "$initializer")
        [[ $initializer_sha == 9e070c898e68e95f6329c8af6e8e62055673a2b8f9e6deb78e030a94f6b24aa0 ]]
        if [[ ! -e /etc/finals-platform/role && ! -L /etc/finals-platform/role ]] && sudo -n test ! -e /etc/event-router/role && sudo -n test ! -L /etc/event-router/role; then
          :
        elif [[ ! -e /etc/finals-platform/role && ! -L /etc/finals-platform/role ]] && sudo -n test -f /etc/event-router/role && sudo -n test ! -L /etc/event-router/role && [[ $(sudo -n cat /etc/event-router/role) == "'$expected'" ]]; then
          :
        else
          echo "gateway role tuple is not authorized" >&2
          exit 1
        fi
        sudo -n /usr/local/sbin/event-router-initialize "'$expected'"
        [[ ! -e /etc/finals-platform/role && ! -L /etc/finals-platform/role ]]
        sudo -n test -f /etc/event-router/role
        sudo -n test ! -L /etc/event-router/role
        [[ $(sudo -n cat /etc/event-router/role) == "'$expected'" ]]
        sudo -n systemctl is-active --quiet event-router.target'
  SCRIPT
  operations_commission_gateway_role_audit_script  = <<-SCRIPT
    #!/usr/bin/env bash
    set -euo pipefail
    [[ $EUID -eq 0 && $(cat /etc/finals-platform/role 2>/dev/null) == '{"role":"operations"}' ]] || exit 1
    [[ -f /run/finals-commissioning/central_id_ed25519 && ! -L /run/finals-commissioning/central_id_ed25519 ]] || exit 1
    [[ $# -eq 1 ]] || exit 2
    case "$1" in
      gateway-primary) address=10.60.250.10 ;;
      gateway-standby) address=10.60.250.11 ;;
      *) echo "unsupported fixed gateway audit target" >&2; exit 2 ;;
    esac
    exec /usr/bin/ssh -F /dev/null -i /run/finals-commissioning/central_id_ed25519 \
      -o BatchMode=yes -o ConnectTimeout=10 -o IdentitiesOnly=yes -o PasswordAuthentication=no \
      -o StrictHostKeyChecking=yes -o UserKnownHostsFile=/etc/finals-platform/operations/known_hosts \
      -- "ubuntu@$address" 'set -euo pipefail
        platform=$(cat /etc/finals-platform/role 2>/dev/null || true)
        if sudo -n test ! -e /etc/event-router/role && sudo -n test ! -L /etc/event-router/role; then
          router=
        elif sudo -n test -f /etc/event-router/role && sudo -n test ! -L /etc/event-router/role; then
          router=$(sudo -n cat /etc/event-router/role)
        else
          router=__unexpected__
        fi
        case "$platform" in
          "") platform_category=absent ;;
          "{\"role\":\"production\"}") platform_category=production ;;
          "{\"role\":\"gateway\"}") platform_category=gateway ;;
          *) platform_category=unexpected ;;
        esac
        case "$router" in active|standby) router_category=$router ;; "") router_category=absent ;; *) router_category=unexpected ;; esac
        printf "platform=%s router=%s\n" "$platform_category" "$router_category"'
  SCRIPT
  operations_commission_production_keys_script     = <<-SCRIPT
    #!/usr/bin/env bash
    set -euo pipefail
    # model a: put one team's ssh keys on its own production box. stdin is a header
    # line "production-NN apply|rollback", then for apply the box's host key line
    # "known-host 10.60.N.2 ssh-ed25519 ..." and the authorized_keys lines.
    [[ $EUID -eq 0 && $(cat /etc/finals-platform/role 2>/dev/null) == '{"role":"operations"}' ]] || exit 1
    central=/run/finals-commissioning/central_id_ed25519
    [[ -f $central && ! -L $central && $# -eq 0 ]] || exit 2
    work=$(mktemp -d /run/finals-production-keys.XXXXXX)
    trap 'rm -rf -- "$work"' EXIT
    dd bs=16385 count=1 status=none > "$work/in"
    [[ -s $work/in && $(stat -c '%s' "$work/in") -le 16384 ]] || { echo "payload size is invalid" >&2; exit 1; }
    read -r target action < <(head -n1 "$work/in")
    [[ $target =~ ^production-(0[1-9]|1[0-5])$ ]] || { echo "unsupported fixed production target" >&2; exit 2; }
    address="10.60.$((10#$${BASH_REMATCH[1]})).2"
    [[ $action == apply || $action == rollback ]] || exit 2
    tail -n +2 "$work/in" > "$work/body"
    read -r marker host type key < <(head -n1 "$work/body")
    [[ $marker == known-host && $host == "$address" && $type == ssh-ed25519 && $key =~ ^[A-Za-z0-9+/]{68}$ ]] || { echo "host key line is invalid" >&2; exit 1; }
    printf '%s %s %s\n' "$address" "$type" "$key" > "$work/known_hosts"
    tail -n +2 "$work/body" > "$work/authorized_keys"
    ssh_to() { ssh -F /dev/null -i "$central" -o BatchMode=yes -o ConnectTimeout=10 -o IdentitiesOnly=yes \
      -o PasswordAuthentication=no -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$work/known_hosts" -- "ubuntu@$address" "$1"; }
    if [[ $action == rollback ]]; then
      ssh_to 'set -eu; cd "$HOME/.ssh"; test -f authorized_keys.prev; cp -p authorized_keys authorized_keys.swap; mv authorized_keys.prev authorized_keys; mv authorized_keys.swap authorized_keys.prev; ssh-keygen -lf authorized_keys | wc -l'
      exit 0
    fi
    lines=0 organizer=0
    while IFS= read -r line; do
      [[ $line =~ ^ssh-ed25519\ [A-Za-z0-9+/]{68}(\ [A-Za-z0-9._@:-]{1,100})?$ ]] || { echo "authorized key line is invalid" >&2; exit 1; }
      [[ $(ssh-keygen -lf - <<<"$line" | awk '{print $2}') != 'SHA256:dfPMQE51IWgeI/TQvWs+zgCNU1dyZhpMBnQap/pmA0I' ]] || organizer=1
      lines=$((lines + 1))
    done < "$work/authorized_keys"
    (( organizer == 1 && lines >= 2 && lines <= 64 )) || { echo "keys must keep the organizer and add 1-63 team keys" >&2; exit 1; }
    ssh_to 'set -eu; umask 077; mkdir -p "$HOME/.ssh"; cd "$HOME/.ssh"; cat > authorized_keys.next; if [ -f authorized_keys ]; then cp -p authorized_keys authorized_keys.prev; fi; mv authorized_keys.next authorized_keys; ssh-keygen -lf authorized_keys | wc -l' < "$work/authorized_keys"
  SCRIPT
  operations_commission_gateway_model_a_script     = <<-SCRIPT
    #!/usr/bin/env bash
    set -euo pipefail
    # event-time exception to the gateway image: stage the reviewed model a router
    # files (hash pinned), activate them, or flip the production-ssh switch.
    # stdin header: "gateway-primary|gateway-standby stage NAME|activate|enable|disable"
    [[ $EUID -eq 0 && $(cat /etc/finals-platform/role 2>/dev/null) == '{"role":"operations"}' ]] || exit 1
    central=/run/finals-commissioning/central_id_ed25519
    [[ -f $central && ! -L $central && $# -eq 0 ]] || exit 2
    work=$(mktemp -d /run/finals-gateway-model-a.XXXXXX)
    trap 'rm -rf -- "$work"' EXIT
    dd bs=65537 count=1 status=none > "$work/in"
    [[ -s $work/in && $(stat -c '%s' "$work/in") -le 65536 ]] || exit 1
    read -r target action name < <(head -n1 "$work/in")
    case "$target" in
      gateway-primary) address=10.60.250.10 ;;
      gateway-standby) address=10.60.250.11 ;;
      *) echo "unsupported fixed gateway target" >&2; exit 2 ;;
    esac
    declare -A pinned=(
      [nftables]=b3122786466030efae9b2cb29903116d42aa824d6c703235968222f52807a269
      [render]=a40b74f027e0137442f1f6ddfa1ce4f86b2a490c29716a5716aa9af8c1aa4dc6
      [apply-inventory]=4725b32ca95776bfcfcbe61f8ee5e7ee66711e8008a7cdd1350ff494ccdf7e57
    )
    ssh_to() { ssh -F /dev/null -i "$central" -o BatchMode=yes -o ConnectTimeout=10 -o IdentitiesOnly=yes \
      -o PasswordAuthentication=no -o StrictHostKeyChecking=yes -o UserKnownHostsFile=/etc/finals-platform/operations/known_hosts -- "ubuntu@$address" "$1"; }
    case "$action" in
      stage)
        [[ -n $${pinned[$name]:-} ]] || { echo "unsupported model a file" >&2; exit 2; }
        tail -n +2 "$work/in" > "$work/file"
        read -r sum _ < <(sha256sum "$work/file")
        [[ $sum == "$${pinned[$name]}" ]] || { echo "model a file hash is not the reviewed one" >&2; exit 1; }
        ssh_to "set -eu; sudo -n install -d -m 0700 /var/lib/event-router/model-a; sudo -n tee /var/lib/event-router/model-a/$name >/dev/null" < "$work/file"
        ;;
      activate)
        ssh_to "set -eu; d=/var/lib/event-router/model-a
          echo '$${pinned[nftables]}  '\$d/nftables | sudo -n sha256sum -c --quiet
          echo '$${pinned[render]}  '\$d/render | sudo -n sha256sum -c --quiet
          echo '$${pinned[apply-inventory]}  '\$d/apply-inventory | sudo -n sha256sum -c --quiet
          sudo -n install -m 0644 \$d/nftables /etc/nftables.conf
          sudo -n install -m 0755 \$d/render /usr/local/libexec/event-router/render_inventory.py
          sudo -n install -m 0755 \$d/apply-inventory /usr/local/sbin/event-router-apply-inventory
          sudo -n nft -c -f /etc/nftables.conf
          sudo -n systemctl restart nftables.service event-router-restore.service
          if sudo -n grep -Fxq active /etc/event-router/role; then sudo -n systemctl restart event-router-activate.service; fi
          sudo -n nft list set inet event_router peer_production_access >/dev/null"
        ;;
      enable|disable)
        ssh_to "set -eu; if [ $action = enable ]; then echo enabled | sudo -n tee /etc/event-router/production-ssh >/dev/null; else sudo -n rm -f /etc/event-router/production-ssh; fi
          sudo -n test ! -f /var/lib/event-router/active-peers.json || sudo -n /usr/local/sbin/event-router-apply-inventory /var/lib/event-router/active-peers.json
          sudo -n nft list set inet event_router peer_production_access | grep -c ' \. ' || true"
        ;;
      *) echo "unsupported model a action" >&2; exit 2 ;;
    esac
  SCRIPT
  operations_commission_sudoers                    = <<-SUDOERS
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-operations-ssh gateway-primary gateway-wireguard
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-operations-ssh gateway-primary gateway-reconciler
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-operations-ssh gateway-standby gateway-wireguard
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-operations-ssh gateway-standby gateway-reconciler
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-operations-ssh platform anvil
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-operations-ssh control control-reconciler
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-operations-ssh control control-checkers
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-operations-ssh repository repository
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-secret platform anvil
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-volume platform volume-initialize
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-control-action reconcile-once
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-control-action reconciler-enable
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-control-action control-status
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-control-secret control-reconciler
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-control-secret control-checkers
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-host-firewall platform
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-host-firewall control
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-host-firewall repository
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-host-firewall mirror
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-host-firewall hill-01
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-host-firewall hill-02
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-host-firewall hill-03
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-host-firewall production-01
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-host-firewall production-02
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-host-firewall production-03
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-host-firewall production-04
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-host-firewall production-05
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-host-firewall production-06
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-host-firewall production-07
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-host-firewall production-08
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-host-firewall production-09
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-host-firewall production-10
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-host-firewall production-11
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-host-firewall production-12
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-host-firewall production-13
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-host-firewall production-14
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-host-firewall production-15
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-host-firewall production-16
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-volume gateway-primary volume-initialize
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-volume gateway-standby volume-initialize
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-stage-central
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-clear-central
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-gateway-secret gateway-primary gateway-wireguard
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-gateway-secret gateway-primary gateway-reconciler
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-gateway-secret gateway-standby gateway-wireguard
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-gateway-secret gateway-standby gateway-reconciler
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-gateway-authorizer gateway-primary
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-gateway-authorizer gateway-standby
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-gateway-role gateway-primary
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-gateway-role gateway-standby
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-gateway-role-audit gateway-primary
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-gateway-role-audit gateway-standby
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-production-keys ""
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-gateway-model-a ""
  SUDOERS
  operations_commission_runcmd = join("\n", [
    "  - |",
    "    set -eu",
    "    printf '%s' '${base64gzip(local.operations_commission_script)}' | base64 -d | gzip -d | install -D -m 0755 /dev/stdin /usr/local/sbin/finals-commission-volume",
    "    printf '%s' '${base64gzip(local.operations_commission_secret_script)}' | base64 -d | gzip -d | install -D -m 0755 /dev/stdin /usr/local/sbin/finals-commission-secret",
    "    printf '%s' '${base64gzip(local.operations_commission_control_action_script)}' | base64 -d | gzip -d | install -D -m 0755 /dev/stdin /usr/local/sbin/finals-commission-control-action",
    "    printf '%s' '${base64gzip(local.operations_commission_control_secret_script)}' | base64 -d | gzip -d | install -D -m 0755 /dev/stdin /usr/local/sbin/finals-commission-control-secret",
    "    printf '%s' '${base64gzip(local.operations_commission_host_firewall_script)}' | base64 -d | gzip -d | install -D -m 0755 /dev/stdin /usr/local/sbin/finals-commission-host-firewall",
    "    printf '%s' '${base64gzip(local.operations_commission_stage_central_script)}' | base64 -d | gzip -d | install -D -m 0755 /dev/stdin /usr/local/sbin/finals-commission-stage-central",
    "    printf '%s' '${base64gzip(local.operations_commission_clear_central_script)}' | base64 -d | gzip -d | install -D -m 0755 /dev/stdin /usr/local/sbin/finals-commission-clear-central",
    "    printf '%s' '${base64gzip(local.operations_commission_gateway_secret_script)}' | base64 -d | gzip -d | install -D -m 0755 /dev/stdin /usr/local/sbin/finals-commission-gateway-secret",
    "    printf '%s' '${base64gzip(local.operations_commission_gateway_authorizer_script)}' | base64 -d | gzip -d | install -D -m 0755 /dev/stdin /usr/local/sbin/finals-commission-gateway-authorizer",
    "    printf '%s' '${base64gzip(local.operations_commission_gateway_role_script)}' | base64 -d | gzip -d | install -D -m 0755 /dev/stdin /usr/local/sbin/finals-commission-gateway-role",
    "    printf '%s' '${base64gzip(local.operations_commission_gateway_role_audit_script)}' | base64 -d | gzip -d | install -D -m 0755 /dev/stdin /usr/local/sbin/finals-commission-gateway-role-audit",
    "    printf '%s' '${base64gzip(local.operations_commission_production_keys_script)}' | base64 -d | gzip -d | install -D -m 0755 /dev/stdin /usr/local/sbin/finals-commission-production-keys",
    "    printf '%s' '${base64gzip(local.operations_commission_gateway_model_a_script)}' | base64 -d | gzip -d | install -D -m 0755 /dev/stdin /usr/local/sbin/finals-commission-gateway-model-a",
    "    temporary=$(mktemp /etc/sudoers.d/.finals-operations-commissioning.XXXXXX)",
    "    printf '%s' '${base64gzip(local.operations_commission_sudoers)}' | base64 -d | gzip -d > \"$temporary\"",
    "    chmod 0440 \"$temporary\"",
    "    visudo -cf \"$temporary\" >/dev/null",
    "    mv \"$temporary\" /etc/sudoers.d/finals-operations-commissioning",
    "",
  ])

  cloud_init_base_by_role = {
    for role in keys(local.hosts) : role => <<-YAML
      #cloud-config
      ssh_deletekeys: true
      ssh_genkeytypes:
        - ed25519
      write_files:
        - path: /etc/ssh/sshd_config.d/91-operations-relay.conf
          owner: root:root
          permissions: '0644'
          content: |
            AuthorizedKeysFile .ssh/authorized_keys /etc/ssh/operations_relay_authorized_keys_%u
        - path: /etc/ssh/operations_relay_authorized_keys_ubuntu
          owner: root:root
          permissions: '${contains(var.relay_authorized_keys_readable_roles, role) ? "0644" : "0600"}'
          content: |
            ${contains(local.operations_relay_roles, role) ? local.operations_relay_authorized_key : ""}
      runcmd:
        - ["/usr/sbin/sshd", "-t"]
        - ["systemctl", "restart", "ssh.service"]
        - ["/usr/local/sbin/finals-host-recipient"]
        - ["/usr/local/sbin/finals-platform-activate", "${role}"]
    YAML
  }
  cloud_init_by_role = {
    for role, content in local.cloud_init_base_by_role : role => role == "operations" ? replace(
      content,
      "  - [\"/usr/local/sbin/finals-platform-activate\", \"operations\"]\n",
      "  - [\"/usr/local/sbin/finals-platform-activate\", \"operations\"]\n${local.operations_commission_runcmd}",
    ) : content
  }
}

check "operations_commission_cloud_init" {
  assert {
    condition     = length(regexall("finals-commission-volume", local.cloud_init_by_role["operations"])) > 0
    error_message = "Operations cloud-init must install the fixed commissioning wrapper."
  }

  assert {
    condition = (
      length(base64encode(local.cloud_init_by_role["operations"])) +
      length(trimspace(var.organizer_ssh_authorized_keys)) < 31488
    )
    error_message = "Operations cloud-init must fit the OCI base64 metadata limit."
  }

  assert {
    condition = alltrue([
      for role in keys(local.hosts) : role == "operations" || local.cloud_init_by_role[role] == local.cloud_init_base_by_role[role]
    ])
    error_message = "The commissioning window must not alter any non-operations cloud-init payload."
  }
}

resource "terraform_data" "operations_generation" {
  input = "bootstrap"
}

resource "oci_core_instance" "host" {
  for_each = local.hosts

  availability_domain = var.availability_domain
  compartment_id      = var.compartment_id
  display_name        = each.key
  shape               = each.value.shape
  freeform_tags       = merge(local.tags, { role = each.key })

  shape_config {
    ocpus         = each.value.ocpus
    memory_in_gbs = each.value.memory_gb
  }

  create_vnic_details {
    assign_public_ip = false
    display_name     = each.key
    hostname_label   = replace(each.key, "-", "")
    nsg_ids          = [var.infra_nsg_id]
    private_ip       = each.value.private_ip
    subnet_id        = var.subnet_ids[each.value.subnet]
  }

  source_details {
    source_id               = each.value.architecture == "x86" ? var.x86_image_id : var.arm_image_id
    source_type             = "image"
    boot_volume_size_in_gbs = each.value.boot_gb
  }

  metadata = {
    ssh_authorized_keys = trimspace(var.organizer_ssh_authorized_keys)
    user_data           = base64encode(local.cloud_init_by_role[each.key])
  }

  instance_options {
    are_legacy_imds_endpoints_disabled = true
  }

}
