import base64
import gzip
import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[2]
INSTALLER = ROOT / "terraform/scripts/install-verified-build-payload"
TEMPLATES = (
    ROOT / "terraform/environments/production/oci-gateway-builder/bootstrap-cloud-init.tftpl",
    ROOT / "terraform/environments/production/oci-runtime-builders/bootstrap-cloud-init.tftpl",
)


class BuilderMetadataTests(unittest.TestCase):
    def test_bootstrap_metadata_stays_below_oci_limit(self):
        substitutions = {
            "installer_base64": base64.b64encode(INSTALLER.read_bytes()).decode(),
            "source_url_json": json.dumps("https://objectstorage.ap-hyderabad-1.oraclecloud.com/p/" + "a" * 4000),
            "source_size": "999999999",
            "source_sha256": "f" * 64,
        }
        for template_path in TEMPLATES:
            rendered = template_path.read_text(encoding="utf-8")
            for name, value in substitutions.items():
                rendered = rendered.replace("${" + name + "}", value)
            self.assertNotIn("${", rendered, template_path.name)
            raw = rendered.encode()
            encoded = base64.b64encode(gzip.compress(raw, mtime=0))
            self.assertLess(len(raw), 16 * 1024, template_path.name)
            self.assertLess(len(encoded), 16 * 1024, template_path.name)

    def test_bootstrap_contains_only_verified_source_installer(self):
        for template_path in TEMPLATES:
            content = template_path.read_text(encoding="utf-8")
            self.assertIn("install-verified-build-payload", content)
            self.assertIn('all: "| tee -a /var/log/cloud-init-output.log /dev/console"', content)
            self.assertEqual(content.count("${source_url_json}"), 1)
            self.assertNotIn("${source_url_json}", content.split("runcmd:", 1)[1])
            self.assertNotIn("/opt/finals-platform", content)
            self.assertNotIn("secret-bootstrap", content)
            self.assertNotIn("cloud-init single", content)

    def test_download_is_bounded_before_digest_verification(self):
        installer = INSTALLER.read_text(encoding="utf-8")
        self.assertIn('ulimit -f "$(( (expected_size + 511) / 512 ))"', installer)
        self.assertIn('--max-filesize "$expected_size"', installer)
        self.assertIn("--connect-timeout 10", installer)
        self.assertIn("--max-time 120", installer)
        self.assertIn('sha256sum --check --status', installer)
        self.assertIn('/bin/bash "$destination"', installer)
        self.assertIn("trap record_failure ERR", installer)
        for phase in ("download", "verify", "execute"):
            self.assertIn(f"phase={phase}", installer)

    def test_builder_payloads_have_overall_deadlines_and_failure_evidence(self):
        payloads = {
            "oci-gateway-builder": "15m",
            "oci-runtime-builders": "90m",
        }
        for root, deadline in payloads.items():
            payload = (ROOT / f"terraform/environments/production/{root}/build-payload.tftpl").read_text(encoding="utf-8")
            source = (ROOT / f"terraform/environments/production/{root}/main.tf").read_text(encoding="utf-8")
            self.assertIn("source_revision='${source_revision}'", payload)
            self.assertIn("trap record_failure ERR", payload)
            self.assertIn(f"deadline={deadline}", payload)
            self.assertIn(f"timeout --signal=TERM --kill-after=30s {deadline}", payload)
            self.assertIn("source_revision = var.source_revision", source)

    def test_image_builds_have_bounded_phases_and_serial_evidence(self):
        gateway = (ROOT / "images/router/build-image").read_text(encoding="utf-8")
        runtime = (ROOT / "images/runtime/build-image").read_text(encoding="utf-8")
        for source in (gateway, runtime):
            self.assertIn("trap record_failure ERR", source)
            self.assertIn("logger --stderr", source)
            self.assertIn('timeout --signal=TERM --kill-after=30s "$deadline" "$@"', source)
            self.assertIn("phase=seal-schedule", source)
        for phase in ("secret-tests", "volume-tests", "router-tests"):
            self.assertIn(f"run_phase {phase} 5m", gateway)
        for phase in ("deployment-tests", "platform-tests", "checker-tests", "runtime-tests"):
            self.assertIn(f"run_phase {phase} 10m", runtime)

    def test_seal_success_binds_revision_and_package_manifest_before_poweroff(self):
        images = (
            (ROOT / "images/router/seal-image", ROOT / "images/router/gateway-image-seal.service"),
            (ROOT / "images/runtime/seal-image", ROOT / "images/runtime/runtime-image-seal.service"),
        )
        for script_path, unit_path in images:
            script = script_path.read_text(encoding="utf-8")
            success = "package_manifest_sha256=$package_sha phase=$phase status=success"
            self.assertIn("source_revision=$source_revision", script)
            self.assertIn(success, script)
            self.assertGreater(script.index(success), script.index("cloud-init clean --logs --machine-id"))
            self.assertLess(script.index(success), script.index("systemctl poweroff"))
            self.assertIn("trap record_failure ERR", script)
            unit = unit_path.read_text(encoding="utf-8")
            self.assertIn("StandardOutput=journal+console", unit)
            self.assertIn("StandardError=journal+console", unit)

    def test_gateway_bootstrap_installs_router_prerequisites(self):
        template = TEMPLATES[0].read_text(encoding="utf-8")
        for package in (
            "age", "conntrack", "iproute2", "nftables", "openssh-client",
            "openssh-server", "python3", "sudo", "systemd-timesyncd", "wireguard-tools",
        ):
            self.assertIn(f"  - {package}\n", template)

    def test_runtime_builder_packages_the_deployment_orchestrator(self):
        source = (ROOT / "terraform/environments/production/oci-runtime-builders/main.tf").read_text(encoding="utf-8")
        package_script = (ROOT / "terraform/scripts/package-oci-stack.sh").read_text(encoding="utf-8")
        self.assertIn('deployment       = "${path.module}/../../../../deployment"', source)
        self.assertIn('hills            = "${path.module}/../../../../hills"', source)
        self.assertIn('"deployment/install.sh"', source)
        self.assertIn('"deployment/tests/run.sh"', source)
        self.assertIn('"hills/install.sh"', source)
        self.assertIn('"hills/tests/run.sh"', source)
        self.assertIn("infra/deployment infra/hills infra/images/runtime", package_script)

    def test_builder_packages_include_the_archive_client(self):
        package_script = (ROOT / "terraform/scripts/package-oci-stack.sh").read_text(encoding="utf-8")
        self.assertIn("oci-gateway-builder) PATHS+=(infra/archive infra/images/router", package_script)
        self.assertIn("oci-runtime-builders) PATHS+=(infra/archive infra/deployment", package_script)

    def test_runtime_builder_replaces_for_par_and_user_data_changes(self):
        source = (ROOT / "terraform/environments/production/oci-runtime-builders/main.tf").read_text(encoding="utf-8")
        self.assertIn('resource "terraform_data" "builder_generation"', source)
        self.assertIn("oci_objectstorage_preauthrequest.source[each.key].id", source)
        self.assertIn("sha256(local.bootstrap_user_data[each.key])", source)
        self.assertIn("terraform_data.builder_generation[each.key]", source)

    def test_runtime_builder_pins_reviewed_anvil(self):
        root = ROOT / "terraform/environments/production/oci-runtime-builders"
        variables = (root / "variables.tf").read_text(encoding="utf-8")
        example = (root / "terraform.tfvars.example").read_text(encoding="utf-8")
        revision = "7e202e9594e2ccbdf4ef592529765f17ca60ccec"
        self.assertIn(f'var.anvil_revision == "{revision}"', variables)
        self.assertIn(f'anvil_revision      = "{revision}"', example)

    def test_builder_provenance_and_hard_metadata_gates_exist(self):
        package_script = (ROOT / "terraform/scripts/package-oci-stack.sh").read_text(encoding="utf-8")
        self.assertIn("status --porcelain --untracked-files=normal", package_script)
        self.assertIn("'HEAD^{commit}'", package_script)
        self.assertIn("packaged-source-revision", package_script)
        for root in ("oci-gateway-builder", "oci-runtime-builders"):
            source = (ROOT / f"terraform/environments/production/{root}/main.tf").read_text(encoding="utf-8")
            self.assertIn('precondition {', source)
            self.assertIn('length(local.bootstrap_user_data', source)
            self.assertIn('var.source_revision == local.packaged_source_revision', source)
            self.assertIn('replace_triggered_by', source)

    def test_long_lived_compute_addresses_and_storage_are_guarded(self):
        storage = (ROOT / "terraform/modules/oci-storage/main.tf").read_text(encoding="utf-8")
        volume_start = storage.index('resource "oci_core_volume" "data"')
        attachment_start = storage.index('resource "oci_core_volume_attachment" "data"')
        policy_start = storage.index('resource "oci_core_volume_backup_policy"')
        self.assertIn("prevent_destroy = true", storage[volume_start:attachment_start])
        self.assertIn("prevent_destroy = true", storage[attachment_start:policy_start])
        for relative in (
            "terraform/modules/oci-platform/main.tf",
            "terraform/modules/oci-ingress/main.tf",
            "terraform/modules/oci-compute-fleet/main.tf",
        ):
            source = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("prevent_destroy = true", source)

        ingress = (ROOT / "terraform/modules/oci-ingress/main.tf").read_text(encoding="utf-8")
        self.assertGreaterEqual(ingress.count("prevent_destroy = true"), 3)
        self.assertIn('resource "oci_core_private_ip" "service_ingress"', ingress)
        self.assertIn('ip_address   = "10.60.250.120"', ingress)
        fleet = (ROOT / "terraform/modules/oci-compute-fleet/main.tf").read_text(encoding="utf-8")
        self.assertGreaterEqual(fleet.count("prevent_destroy = true"), 5)
        self.assertIn('resource "oci_core_volume" "production_data"', fleet)
        self.assertIn('resource "oci_core_volume_attachment" "production_data"', fleet)
        self.assertIn("size_in_gbs         = 50", fleet)

    def test_operations_relay_key_is_forced_and_role_scoped(self):
        ingress = (ROOT / "terraform/modules/oci-ingress/main.tf").read_text(encoding="utf-8")
        platform = (ROOT / "terraform/modules/oci-platform/main.tf").read_text(encoding="utf-8")
        variables = (ROOT / "terraform/modules/oci-platform/variables.tf").read_text(encoding="utf-8")
        forced = 'restrict,command=\\"/usr/local/sbin/finals-secret-relay-receive\\"'
        self.assertIn(forced, ingress)
        self.assertIn(forced, platform)
        self.assertIn('["platform", "control", "repository"]', platform)
        self.assertIn('operations_relay_ssh_public_key', variables)
        self.assertIn('[A-Za-z0-9+/]{68}', variables)
        generated_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIE5+zFPUdhav0YumdESFR9fVhwTeCI43Rn43xyDp5J2a"
        self.assertRegex(generated_key, re.compile(r"^ssh-ed25519 [A-Za-z0-9+/]{68}$"))
        self.assertFalse(generated_key.endswith("="))

    def test_transient_object_payload_is_sensitive(self):
        for root in ("oci-gateway-builder", "oci-runtime-builders"):
            source = (ROOT / f"terraform/environments/production/{root}/main.tf").read_text(encoding="utf-8")
            self.assertRegex(source, r"content\s+= sensitive\(local\.build_payload")

    def test_finals_budget_is_guarded_and_alerts_on_absolute_spend(self):
        root = ROOT / "terraform/environments/production/oci-foundation"
        source = (root / "main.tf").read_text(encoding="utf-8")
        variables = (root / "variables.tf").read_text(encoding="utf-8")
        budget = source[source.index('resource "oci_budget_budget" "finals"'):source.index('resource "oci_budget_alert_rule" "actual"')]
        self.assertIn("amount         = 325", budget)
        self.assertIn('target_type    = "COMPARTMENT"', budget)
        self.assertIn("prevent_destroy = true", budget)
        for threshold in (175, 250, 300, 315):
            self.assertRegex(source, rf"\w+\s+= {threshold}\n")
        self.assertIn('threshold_type = "ABSOLUTE"', source)
        self.assertIn('type           = "ACTUAL"', source)
        self.assertGreaterEqual(source.count("prevent_destroy = true"), 2)
        self.assertIn('variable "budget_alert_recipients"', variables)
        self.assertIn("sensitive   = true", variables)

    def test_foundation_null_routing_default_is_plan_safe(self):
        for relative in (
            "terraform/environments/production/oci-foundation/variables.tf",
            "terraform/modules/oci-network/variables.tf",
        ):
            variables = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("var.routing_private_ip_id == null ? true : startswith", variables)

    def test_fleet_can_expand_without_targeting_resources(self):
        module = ROOT / "terraform/modules/oci-compute-fleet"
        source = (module / "main.tf").read_text(encoding="utf-8")
        variables = (module / "variables.tf").read_text(encoding="utf-8")
        root = (ROOT / "terraform/environments/production/oci-fleet/main.tf").read_text(encoding="utf-8")
        self.assertIn("for team in var.production_numbers", source)
        self.assertIn("for team in var.workbench_numbers", source)
        self.assertIn('variable "production_numbers"', variables)
        self.assertIn('variable "workbench_numbers"', variables)
        self.assertIn("number >= 1 && number <= 16", variables)
        self.assertIn("number >= 1 && number <= 15", variables)
        self.assertIn("Every enabled workbench requires", source)
        self.assertIn("production_numbers                 = var.production_numbers", root)
        self.assertIn("workbench_numbers                  = var.workbench_numbers", root)

    def test_obsolete_gateway_image_and_plan_are_prohibited(self):
        failed_builders = (
            "ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goaceebogxa47rg74d6izhqorb2dgnjjlfsv7gupjwbevyva",
            "ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goacvwoxwqstnmj6bwirfuxxan45gpqbbuzt7fw5if2zjfbq",
        )
        docs = "\n".join(
            (ROOT / f"terraform/environments/production/{root}/README.md").read_text(encoding="utf-8")
            for root in ("oci-gateway-builder", "oci-gateway-image")
        )
        self.assertIn("gateway-5095652d3d90", docs)
        self.assertIn("11bdcffc06c9d4d0b6f08a58b0cf34e6f1aa0d1f", docs)
        for failed_builder in failed_builders:
            self.assertIn(failed_builder, docs)
        self.assertGreaterEqual(docs.count("prohibited"), 2)
        self.assertGreaterEqual(docs.count("router-image"), 2)
        capture_variables = (ROOT / "terraform/environments/production/oci-gateway-image/variables.tf").read_text(encoding="utf-8")
        for failed_builder in failed_builders:
            self.assertIn(f'var.builder_instance_id != "{failed_builder}"', capture_variables)


if __name__ == "__main__":
    unittest.main()
