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

  operations_commission_initializer_sha256 = "687563400a57f907a777946f58a165b5554b8f14146fd3eec3252d65cc00c146"
  operations_commission_script             = <<-SCRIPT
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
        post_command='sudo systemctl restart finals-volume@anvil.service && mountpoint -q /srv/anvil && if sudo test -s /etc/anvil/finals.env && sudo test -s /etc/anvil/tls/fullchain.pem && sudo test -s /etc/anvil/tls/privkey.pem; then sudo systemctl enable --now anvil-finals.service anvil-finals-backup.timer; fi'
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
  operations_commission_sudoers            = <<-SUDOERS
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
  SUDOERS
  operations_commission_runcmd             = <<-YAML
        - |
          set -eu
          printf '%s' '${base64encode(local.operations_commission_script)}' | base64 -d | install -D -m 0755 /dev/stdin /usr/local/sbin/finals-commission-volume
          temporary=$(mktemp /etc/sudoers.d/.finals-operations-commissioning.XXXXXX)
          printf '%s' '${base64encode(local.operations_commission_sudoers)}' | base64 -d > "$temporary"
          chmod 0440 "$temporary"
          visudo -cf "$temporary" >/dev/null
          mv "$temporary" /etc/sudoers.d/finals-operations-commissioning
  YAML

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
          permissions: '0600'
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
      "        - [\"/usr/local/sbin/finals-platform-activate\", \"operations\"]\n",
      "        - [\"/usr/local/sbin/finals-platform-activate\", \"operations\"]\n${local.operations_commission_runcmd}",
    ) : content
  }
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
