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

  operations_commission_initializer_sha256  = "eaeb4c33d2c94f59dee9b01b2b6dbce8e8f8adf720e4108f713456f7cf4f69ab"
  operations_commission_anvil_sha256        = "c760f5097b671cfa1423bd30b407cbbc9cb415fe4a82510d84c9120818143a19"
  operations_commission_script              = <<-SCRIPT
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
        post_command='set -Eeuo pipefail; sudo systemctl restart finals-volume@anvil.service; mountpoint -q /srv/anvil; [[ $(sudo stat -c "%u:%g:%a" /srv/anvil/postgres) == 70:70:700 ]]; [[ $(sudo stat -c "%u:%g:%a" /srv/anvil/storage) == 0:0:700 ]]; [[ $(sudo stat -c "%u:%g:%a" /srv/anvil/backups) == 0:0:700 ]]; sudo test -s /etc/anvil/finals.env; sudo test -s /etc/anvil/tls/fullchain.pem; sudo test -s /etc/anvil/tls/privkey.pem; sudo /opt/anvil/current/deployments/finals/preflight.sh; sudo systemctl enable anvil-finals.service anvil-finals-backup.timer; sudo systemctl restart anvil-finals.service; sudo systemctl start anvil-finals-backup.timer; sudo systemctl is-active --quiet anvil-finals.service; curl --fail --silent --show-error --output /dev/null --connect-timeout 5 --max-time 15 --proto "=https" --tlsv1.2 --resolve finals.h7tex.com:443:10.60.200.10 https://finals.h7tex.com/'
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
      -i /etc/finals-platform/operations/id_ed25519
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
  operations_commission_secret_script       = <<-SCRIPT
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
      -i /etc/finals-platform/operations/id_ed25519 \
      -o BatchMode=yes \
      -o ConnectTimeout=10 \
      -o IdentitiesOnly=yes \
      -o PasswordAuthentication=no \
      -o StrictHostKeyChecking=yes \
      -o UserKnownHostsFile=/etc/finals-platform/operations/known_hosts \
      -- ubuntu@10.60.200.10 \
      'sudo chmod 0644 /etc/ssh/operations_relay_authorized_keys_ubuntu && sudo /usr/sbin/sshd -t && sudo systemctl reload ssh.service && sudo /usr/local/sbin/finals-install-secret-bundle anvil' < "$temporary"
  SCRIPT
  operations_commission_inventory_script    = <<-SCRIPT
    #!/usr/bin/env bash
    set -euo pipefail

    [[ $EUID -eq 0 ]] || { echo "inventory commissioning wrapper must run as root" >&2; exit 1; }
    [[ $(cat /etc/finals-platform/role 2>/dev/null) == '{"role":"operations"}' ]] || {
      echo "inventory commissioning wrapper is restricted to the operations host" >&2
      exit 1
    }
    [[ $# -eq 1 ]] || { echo "usage: finals-commission-inventory {gateway-primary|gateway-standby}" >&2; exit 2; }
    case "$1" in
      gateway-primary) address=10.60.250.10 ;;
      gateway-standby) address=10.60.250.11 ;;
      *) echo "unsupported fixed inventory target" >&2; exit 2 ;;
    esac

    temporary=$(mktemp /run/finals-peer-inventory.XXXXXX)
    trap 'rm -f -- "$temporary"' EXIT
    dd bs=262145 count=1 status=none > "$temporary"
    [[ -s $temporary && $(stat -c '%s' "$temporary") -le 262144 ]] || {
      echo "inventory has an invalid size" >&2
      exit 1
    }

    exec /usr/bin/ssh \
      -F /dev/null \
      -i /etc/finals-platform/operations/id_ed25519 \
      -o BatchMode=yes \
      -o ConnectTimeout=10 \
      -o IdentitiesOnly=yes \
      -o PasswordAuthentication=no \
      -o StrictHostKeyChecking=yes \
      -o UserKnownHostsFile=/etc/finals-platform/operations/known_hosts \
      -- "peer-reconciler@$address" < "$temporary"
  SCRIPT
  operations_commission_gateway_role_script = <<-SCRIPT
    #!/usr/bin/env bash
    set -euo pipefail

    [[ $EUID -eq 0 ]] || { echo "gateway role repair must run as root" >&2; exit 1; }
    [[ $(cat /etc/finals-platform/role 2>/dev/null) == '{"role":"operations"}' ]] || {
      echo "gateway role repair is restricted to the operations host" >&2
      exit 1
    }
    [[ $# -eq 1 ]] || { echo "usage: finals-commission-gateway-role {gateway-primary|gateway-standby}" >&2; exit 2; }
    case "$1" in
      gateway-primary) address=10.60.250.10; expected=active ;;
      gateway-standby) address=10.60.250.11; expected=standby ;;
      *) echo "unsupported fixed gateway target" >&2; exit 2 ;;
    esac

    exec /usr/bin/ssh \
      -F /dev/null \
      -i /etc/finals-platform/operations/id_ed25519 \
      -o BatchMode=yes \
      -o ConnectTimeout=10 \
      -o IdentitiesOnly=yes \
      -o PasswordAuthentication=no \
      -o StrictHostKeyChecking=yes \
      -o UserKnownHostsFile=/etc/finals-platform/operations/known_hosts \
      -- "ubuntu@$address" 'set -euo pipefail
        platform_role=$(cat /etc/finals-platform/role 2>/dev/null || true)
        router_role=$(cat /etc/event-router/role 2>/dev/null || true)
        case "$platform_role" in
          "" ) ;;
          "{\"role\":\"production\"}" ) sudo rm -f -- /etc/finals-platform/role ;;
          * ) echo "gateway has an unexpected platform role marker" >&2; exit 1 ;;
        esac
        case "$router_role" in
          "'$expected'" ) ;;
          "" ) printf "%s\n" "'$expected'" | sudo install -D -m 0644 /dev/stdin /etc/event-router/role ;;
          * ) echo "gateway has an unexpected router role marker" >&2; exit 1 ;;
        esac
        [[ ! -e /etc/finals-platform/role ]]
        [[ $(cat /etc/event-router/role) == "'$expected'" ]]
        if [[ -f /etc/event-router/reconciler_authorized_key && ! -L /etc/event-router/reconciler_authorized_key ]]; then
          sudo /usr/local/sbin/event-router-authorize-reconciler /etc/event-router/reconciler_authorized_key
        fi'
  SCRIPT
  operations_commission_sudoers             = <<-SUDOERS
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-operations-ssh gateway-primary gateway-wireguard
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-operations-ssh gateway-primary gateway-reconciler
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-operations-ssh gateway-standby gateway-wireguard
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-operations-ssh gateway-standby gateway-reconciler
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-operations-ssh platform anvil
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-operations-ssh control control-reconciler
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-operations-ssh control control-checkers
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-operations-ssh repository repository
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-volume platform volume-initialize
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-volume gateway-primary volume-initialize
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-volume gateway-standby volume-initialize
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-secret platform anvil
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-inventory gateway-primary
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-inventory gateway-standby
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-gateway-role gateway-primary
    ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-gateway-role gateway-standby
  SUDOERS
  operations_commission_runcmd = join("\n", [
    "  - |",
    "    set -eu",
    "    printf '%s' '${base64encode(local.operations_commission_script)}' | base64 -d | install -D -m 0755 /dev/stdin /usr/local/sbin/finals-commission-volume",
    "    printf '%s' '${base64encode(local.operations_commission_secret_script)}' | base64 -d | install -D -m 0755 /dev/stdin /usr/local/sbin/finals-commission-secret",
    "    printf '%s' '${base64encode(local.operations_commission_inventory_script)}' | base64 -d | install -D -m 0755 /dev/stdin /usr/local/sbin/finals-commission-inventory",
    "    printf '%s' '${base64encode(local.operations_commission_gateway_role_script)}' | base64 -d | install -D -m 0755 /dev/stdin /usr/local/sbin/finals-commission-gateway-role",
    "    temporary=$(mktemp /etc/sudoers.d/.finals-operations-commissioning.XXXXXX)",
    "    printf '%s' '${base64encode(local.operations_commission_sudoers)}' | base64 -d > \"$temporary\"",
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
