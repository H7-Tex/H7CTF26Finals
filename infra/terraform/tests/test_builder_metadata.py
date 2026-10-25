import base64
import gzip
import hashlib
import json
import re
import shutil
import stat
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[2]
INSTALLER = ROOT / "terraform/scripts/install-verified-build-payload"
TEMPLATES = (
    ROOT / "terraform/environments/production/oci-gateway-builder/bootstrap-cloud-init.tftpl",
    ROOT / "terraform/environments/production/oci-runtime-builders/bootstrap-cloud-init.tftpl",
)


class BuilderMetadataTests(unittest.TestCase):
    def test_bastion_subnet_egress_is_only_operations_ssh(self):
        network = (ROOT / "terraform/modules/oci-network/main.tf").read_text(encoding="utf-8")
        self.assertEqual(network.count('resource "oci_core_security_list" "bastion_egress"'), 1)
        self.assertIn('destination      = "10.60.200.5/32"', network)
        self.assertIn('protocol         = "6"', network)
        self.assertIn('min = 22', network)
        self.assertIn('max = 22', network)
        self.assertIn('security_list_ids = each.key == "services"', network)
        self.assertNotIn('destination      = "0.0.0.0/0"', network[network.index('resource "oci_core_security_list" "bastion_egress"'):network.index('resource "oci_core_route_table" "edge"')])

    def test_operations_bastion_is_fixed_and_source_restricted(self):
        environment = (ROOT / "terraform/environments/production/oci-platform/main.tf").read_text(encoding="utf-8")
        outputs = (ROOT / "terraform/environments/production/oci-platform/outputs.tf").read_text(encoding="utf-8")
        module = (ROOT / "terraform/modules/oci-platform/main.tf").read_text(encoding="utf-8")
        variables = (ROOT / "terraform/modules/oci-platform/variables.tf").read_text(encoding="utf-8")
        self.assertEqual(environment.count('resource "oci_bastion_bastion" "operations"'), 1)
        self.assertIn('bastion_type                 = "standard"', environment)
        self.assertIn(
            'client_cidr_block_allow_list = ["27.61.61.38/32", "27.61.63.104/32", "144.24.149.51/32"]',
            environment,
        )
        self.assertIn('max_session_ttl_in_seconds   = 10800', environment)
        self.assertIn('name                         = "operations"', environment)
        self.assertIn('target_subnet_id             = var.subnet_ids["services"]', environment)
        self.assertIn('dns_proxy_status             = "DISABLED"', environment)
        self.assertIn("ignore_changes = [bastion_type]", environment)
        self.assertNotIn('client_cidr_block_allow_list = ["0.0.0.0/0"]', environment)
        self.assertIn('oci_bastion_bastion.operations.private_endpoint_ip_address', outputs)
        self.assertEqual(
            environment.count(
                "operations_bastion_source_ip    = oci_bastion_bastion.operations.private_endpoint_ip_address"
            ),
            1,
        )
        self.assertIn('variable "operations_bastion_source_ip"', variables)
        self.assertIn('startswith(var.operations_bastion_source_ip, "10.60.200.")', variables)
        self.assertEqual(module.count("10-bastion.conf"), 2)
        self.assertEqual(
            module.count(
                'ExecStartPost=/usr/sbin/nft add rule inet finals_host input ip saddr ${var.operations_bastion_source_ip} tcp dport 22 accept'
            ),
            1,
        )
        self.assertIn('"  - [\\"systemctl\\", \\"daemon-reload\\"]\\n  - [\\"/usr/local/sbin/finals-platform-activate\\", \\"operations\\"]', module)
        self.assertIn("operations_unused_relay_files", module)
        self.assertIn("local.operations_unused_relay_files", module)
        self.assertNotIn("0.0.0.0/0 tcp dport 22 accept", module)

    def test_checker_status_is_fixed_and_bounded(self):
        module = (ROOT / "terraform/modules/oci-platform/main.tf").read_text(encoding="utf-8")
        wrapper = (ROOT / "terraform/modules/oci-platform/scripts/commission-runtime-artifact").read_text(encoding="utf-8")
        status = wrapper[wrapper.index("  control:checker-status)"):wrapper.index("  hill-0[123]:hill-artifacts)")]
        self.assertIn("control:checker-status)", wrapper)
        self.assertIn("http://127.0.0.1:9160/readyz", status)
        self.assertIn("systemctl is-active --quiet checker-runtime.service", status)
        self.assertIn("systemctl is-active --quiet peer-reconciler.timer", status)
        self.assertEqual(status.count("timeout --signal=TERM --kill-after=2s 10s"), 2)
        self.assertIn("--connect-timeout 2 --max-time 3", status)
        self.assertIn('checker-runtime.service=%s\\npeer-reconciler.timer=%s\\nreadyz-http=%s\\n', status)
        self.assertIn("[[ $checker_runtime == active && $reconciler_timer == active && $readyz_http == 200 ]]", status)
        self.assertLess(status.index("checker-runtime.service=%s"), status.index("$checker_runtime == active"))
        self.assertIn("--silent --output /dev/null --write-out", status)
        self.assertNotIn("operations_commission_control_action_script", module)

    def test_anvil_deploy_is_fixed_bounded_and_rollback_safe(self):
        module = (ROOT / "terraform/modules/oci-platform/main.tf").read_text(encoding="utf-8")
        wrapper = (ROOT / "terraform/modules/oci-platform/scripts/commission-runtime-artifact").read_text(encoding="utf-8")
        deployer_path = ROOT / "terraform/modules/oci-platform/scripts/deploy-anvil-artifact"
        deployer = deployer_path.read_text(encoding="utf-8")
        deploy = wrapper[wrapper.index("  platform:anvil-deploy)"):wrapper.index("  control:checker-status)")]
        subprocess.run(["bash", "-n", str(deployer_path)], check=True)
        self.assertIn("maximum=536870912", deploy)
        self.assertIn("[[ ${#request[@]} -eq 5 ]]", deploy)
        self.assertIn("expected_game_sha256=${request[3]}", deploy)
        self.assertIn("objectstorage\\.ap-hyderabad-1\\.oraclecloud\\.com", deploy)
        self.assertIn(hashlib.sha256(deployer_path.read_bytes()).hexdigest(), deploy)
        self.assertIn("install -D -o root -g root -m 0700 /dev/stdin /var/tmp/finals-anvil-deploy.sh", deploy)
        self.assertNotIn("/bin/bash -s", deploy)
        self.assertIn("/bin/bash /var/tmp/finals-anvil-deploy.sh", deploy)
        self.assertIn("< /dev/null", deploy)
        self.assertIn('grep -Fxq "anvil-deploy-revision=$revision"', deploy)
        self.assertIn("grep -Fxq anvil-deploy=complete", deploy)
        self.assertIn("[[ $(stat -c %s \"$bundle\") -eq $expected_size ]]", deployer)
        self.assertIn("h7ctf-anvil-deploy-v1", deployer)
        self.assertIn("$'deploy.sh\\ngame.yaml\\nimages.tar.gz\\nmanifest.json'", deployer)
        self.assertIn('["format","game","images","migrations","revision"]', deployer)
        self.assertIn('[[ $revision == "$expected_revision" ]]', deployer)
        self.assertIn('[[ $target_game == "$expected_game_sha256" ]]', deployer)
        self.assertIn("uncompressed_maximum=2147483648", deployer)
        self.assertIn('docker load --input "$work/images.tar"', deployer)
        self.assertIn('"anvil-finals-api:" + $revision', deployer)
        self.assertIn('"anvil-finals-web:" + $revision', deployer)
        self.assertIn("anvil-finals-api:previous", deployer)
        self.assertIn("anvil-finals-web:previous", deployer)
        self.assertLess(deployer.index("rollback_needed=1"), deployer.index('docker load --input "$work/images.tar"'))
        self.assertIn("anvil-deploy-rollback=complete", deployer)
        self.assertIn("/api/health /api/v1/info", deployer)
        self.assertEqual(deployer.count("images_active"), 3)
        self.assertIn("systemctl start anvil-finals-backup.service", deployer)
        self.assertIn("target_migration_sha256", deployer)
        self.assertGreaterEqual(deployer.count("migration_sha256"), 4)
        self.assertEqual(deployer.count("exec -T postgres"), 2)
        self.assertEqual(deployer.count("< /dev/null"), 2)
        self.assertIn("anvil-deploy=complete", deployer)
        deploy_sudoer = "ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-runtime-artifact platform anvil-deploy"
        self.assertEqual(module.count(deploy_sudoer), 1)
        self.assertNotIn("control checker-recover", module)
        self.assertNotIn("control state-summary", module)

    def test_anvil_status_is_fixed_read_only_and_redacted(self):
        module = (ROOT / "terraform/modules/oci-platform/main.tf").read_text(encoding="utf-8")
        wrapper = (ROOT / "terraform/modules/oci-platform/scripts/commission-runtime-artifact").read_text(encoding="utf-8")
        status = wrapper[wrapper.index("  platform:anvil-status)"):wrapper.index("  control:checker-status)")]
        self.assertIn("ANVIL_IMAGE_REVISION", status)
        self.assertIn("for service in api web ingress", status)
        self.assertIn("docker compose --project-name anvil-finals", status)
        self.assertIn('docker inspect --format "{{.Image}}"', status)
        self.assertIn("anvil-status=complete", status)
        self.assertNotIn("docker inspect --format '{{json .Config.Env}}'", status)
        self.assertNotIn("cat $env_file", status)
        sudoer = "ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-runtime-artifact platform anvil-status"
        self.assertEqual(module.count(sudoer), 1)

    def test_operations_runtime_artifact_relay_is_fixed(self):
        module = (ROOT / "terraform/modules/oci-platform/main.tf").read_text(encoding="utf-8")
        wrapper = ROOT / "terraform/modules/oci-platform/scripts/commission-runtime-artifact"
        source = wrapper.read_text(encoding="utf-8")
        subprocess.run(["bash", "-n", str(wrapper)], check=True)
        self.assertIn("f3716d884f4ed3ebe5b5c4138d459aa2e35324c0839c5466167d91cd6796cc20", source)
        self.assertIn("control:checker-status)", source)
        self.assertIn("platform:anvil-deploy)", source)
        self.assertIn("platform:anvil-status)", source)
        self.assertNotIn("control:checker-recover)", source)
        self.assertNotIn("control:state-summary)", source)
        self.assertNotIn("control:checker-artifacts)", source)
        self.assertNotIn("finals-commission-runtime-artifact control checker-artifacts", module)
        self.assertIn('file("${path.module}/scripts/commission-runtime-artifact")', module)
        self.assertNotIn("finals-commission-runtime-artifact *", module)

    def test_operations_production_runtime_recovery_is_fixed(self):
        module = (ROOT / "terraform/modules/oci-platform/main.tf").read_text(encoding="utf-8")
        wrapper = ROOT / "terraform/modules/oci-platform/scripts/commission-production-runtime"
        content = wrapper.read_text(encoding="utf-8")
        subprocess.run(["bash", "-n", str(wrapper)], check=True)
        self.assertIn('file("${path.module}/scripts/commission-production-runtime")', module)
        self.assertIn("^production-(0[1-9]|1[0-6])$", content)
        self.assertIn("firstboot.done=yes", content)
        self.assertIn("legacy-firewall-diagnose", content)
        self.assertIn("legacy-firewall-repair", content)
        self.assertIn("icmp-host-prohibited", content)
        self.assertIn("iptables-restore --test", content)
        self.assertIn("proxy-listeners=6", content)
        self.assertNotIn("docker-store", content)
        self.assertIn("model-a-network-repair=complete", content)
        self.assertIn("23f3b34a0d14c6ab4c8e5df065a4e8dd3fa7bac79e5ed82d5e085910c9b1d2dc", content)
        self.assertNotIn("finals-commission-production-runtime *", module)

    def test_control_checker_artifact_commissioning_is_fixed(self):
        module = (ROOT / "terraform/modules/oci-platform/main.tf").read_text(encoding="utf-8")
        wrapper = ROOT / "terraform/modules/oci-platform/scripts/commission-checker-artifacts"
        source = wrapper.read_text(encoding="utf-8")
        subprocess.run(["bash", "-n", str(wrapper)], check=True)
        self.assertIn("expected_size=495626240", source)
        self.assertIn("expected_sha256=46d07d20db8805c43918e6c695e18fe500066306c681946ffbe6ab6adee17174", source)
        self.assertIn("/usr/local/libexec/finals-platform/checker-preflight", source)
        self.assertIn('file("${path.module}/scripts/commission-checker-artifacts")', module)
        self.assertIn("base64gzip(local.control_commission_script)", module)
        self.assertIn("ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-checker-artifacts", module)
        self.assertIn("ocarun ALL=(root) NOPASSWD: /usr/local/sbin/checker-runtime-commission", module)
        self.assertNotIn("finals-commission-checker-artifacts *", module)

    def test_hill_commissioning_is_fixed(self):
        module = (ROOT / "terraform/modules/oci-platform/main.tf").read_text(encoding="utf-8")
        scripts = ROOT / "terraform/modules/oci-platform/scripts"
        for name in ("commission-hill-artifacts", "commission-hill-config", "commission-hill-start"):
            subprocess.run(["bash", "-n", str(scripts / name)], check=True)
        artifacts = (scripts / "commission-hill-artifacts").read_text(encoding="utf-8")
        self.assertIn("expected_size=385986560", artifacts)
        self.assertIn("expected_sha256=f3716d884f4ed3ebe5b5c4138d459aa2e35324c0839c5466167d91cd6796cc20", artifacts)
        self.assertIn("python3 \"$release/verify-release.py\" --role \"$role\" --load", artifacts)
        self.assertIn("ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-install-secret-bundle hill-control", module)
        self.assertNotIn("finals-commission-hill-artifacts *", module)

    def test_platform_image_override_is_scoped_to_platform_host(self):
        module = (ROOT / "terraform/modules/oci-platform/main.tf").read_text(encoding="utf-8")
        environment = (ROOT / "terraform/environments/production/oci-platform/main.tf").read_text(encoding="utf-8")
        variables = (ROOT / "terraform/modules/oci-platform/variables.tf").read_text(encoding="utf-8")
        self.assertIn('each.key == "platform" && var.platform_image_id != null', module)
        self.assertIn("for_each = local.x86_hosts", module)
        self.assertIn('resource "oci_core_instance" "host_arm"', module)
        self.assertIn("for_each = local.arm_hosts", module)
        self.assertIn("replace_triggered_by = [terraform_data.host_image_generation[each.key]]", module)
        for role in ("operations", "repository", "mirror"):
            self.assertIn(f'from = oci_core_instance.host["{role}"]', module)
            self.assertIn(f'to   = oci_core_instance.host_arm["{role}"]', module)
        self.assertIn('relay_authorized_keys_readable_roles = ["platform", "control"]', environment)
        self.assertIn("platform_image_id               = var.platform_image_id", environment)
        self.assertIn('variable "platform_image_id"', variables)

    def test_host_image_generation_is_scoped_per_host(self):
        module = (ROOT / "terraform/modules/oci-platform/main.tf").read_text(encoding="utf-8")
        self.assertIn(
            '''resource "terraform_data" "host_image_generation" {
  for_each = local.x86_hosts

  triggers_replace = [
    each.key == "platform" && var.platform_image_id != null ? var.platform_image_id : var.x86_image_id,
  ]
}''',
            module,
        )
        self.assertNotIn('resource "terraform_data" "x86_generation"', module)
        self.assertEqual(
            module.count("replace_triggered_by = [terraform_data.host_image_generation[each.key]]"),
            1,
        )

    def test_oci_stack_packages_are_byte_reproducible(self):
        repository = ROOT.parent
        package_script = ROOT / "terraform/scripts/package-oci-stack.sh"
        with tempfile.TemporaryDirectory() as temporary:
            checkout = Path(temporary) / "checkout"
            subprocess.run(
                ["git", "clone", "--quiet", "--no-hardlinks", str(repository), str(checkout)],
                check=True,
            )
            candidate = checkout / package_script.relative_to(repository)
            shutil.copy2(package_script, candidate)
            subprocess.run(["git", "-C", str(checkout), "add", str(candidate)], check=True)
            subprocess.run(
                [
                    "git", "-C", str(checkout),
                    "-c", "user.name=Package Test",
                    "-c", "user.email=package-test@example.invalid",
                    "commit", "--quiet", "--allow-empty", "-m", "package test",
                ],
                check=True,
            )
            command = [str(candidate), "oci-runtime-builders"]
            first_path = Path(subprocess.run(command, cwd=checkout, check=True, capture_output=True, text=True).stdout.splitlines()[0])
            first = first_path.read_bytes()
            time.sleep(2.1)
            second_path = Path(subprocess.run(command, cwd=checkout, check=True, capture_output=True, text=True).stdout.splitlines()[0])
            self.assertEqual(first, second_path.read_bytes())

    def test_production_image_bakes_the_pinned_model_a_release(self):
        builders = ROOT / "terraform/environments/production/oci-runtime-builders"
        main = (builders / "main.tf").read_text(encoding="utf-8")
        variables = (builders / "variables.tf").read_text(encoding="utf-8")
        package = (ROOT / "terraform/scripts/package-oci-stack.sh").read_text(encoding="utf-8")
        build = (ROOT / "images/runtime/build-image").read_text(encoding="utf-8")
        self.assertIn('role == "production" ? local.model_a_release_file : []', main)
        self.assertIn('check "model_a_release"', main)
        self.assertIn('"fetch-model-a-release"', main)
        self.assertIn('model-a-runtime  = "${path.module}/../../../../model-a-runtime"', main)
        self.assertIn('startswith(path, "evidence/")', main)
        self.assertIn("sensitive   = true", variables.split('variable "model_a_release_url"', 1)[1].split("}", 1)[0])
        self.assertIn("infra/model-a-runtime", package)
        release = json.loads((ROOT / "model-a-runtime/evidence/release-gates.json").read_text(encoding="utf-8")) if (ROOT / "model-a-runtime/evidence/release-gates.json").exists() else None
        for digest in ("d1d427d928b1aa96394a201af048ec5f3c1eb67471b36bae65c9887c95b9a7e4", "ee06b3b975ae5fac7e7600e3c0214eab7099029106289705c9fbe1d12b70c348"):
            self.assertIn(digest, variables)
        # the release is fetched only after the production policy phase and before tools and first boot
        self.assertLess(build.index("phase=production-policy"), build.index("run_phase model-a-release"))
        self.assertIn("run_phase model-a-volume-policy", build)
        self.assertLess(build.index("run_phase model-a-release"), build.index("run_phase model-a-volume-policy"))
        self.assertLess(build.index("run_phase model-a-volume-policy"), build.index("systemctl enable finals-model-a-firstboot.service"))
        self.assertLess(build.index("run_phase model-a-release"), build.index("systemctl enable finals-model-a-firstboot.service"))

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

    def test_gateway_builder_packages_every_router_policy_input(self):
        source = (ROOT / "terraform/environments/production/oci-gateway-builder/main.tf").read_text(encoding="utf-8")
        self.assertIn('"cloud-init.yaml"', source)
        self.assertIn('"tests/challenge_access.sh"', source)
        self.assertIn('"rootfs/usr/local/sbin/event-router-public-ingress"', source)

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

    def test_runtime_builder_prepares_sshd_runtime_before_validation(self):
        installer = (ROOT / "images/runtime/install.sh").read_text(encoding="utf-8")
        self.assertIn("install -d -m 0755 /run/sshd", installer)
        self.assertLess(installer.index("install -d -m 0755 /run/sshd"), installer.index("sshd -t"))

    def test_control_reconciler_ships_the_canonical_router_validator(self):
        reconciler = (ROOT / "reconciler/install.sh").read_text(encoding="utf-8")
        builders = (ROOT / "terraform/environments/production/oci-runtime-builders/main.tf").read_text(encoding="utf-8")
        package = (ROOT / "terraform/scripts/package-oci-stack.sh").read_text(encoding="utf-8")
        path = "images/router/rootfs/usr/local/libexec/event-router/render_inventory.py"
        self.assertIn(f"../{path}", reconciler)
        self.assertIn(path, builders)
        self.assertIn(path, package)

    def test_production_go_build_uses_and_removes_an_explicit_cache(self):
        builder = (ROOT / "images/runtime/build-image").read_text(encoding="utf-8")
        cache = "export GOCACHE=/var/cache/finals-image-builder/go-build"
        workspace = "export GOPATH=/var/cache/finals-image-builder/go"
        tests = 'run_phase deployment-tests 10m "$source_dir/deployment/tests/run.sh"'
        cleanup = "rm -rf /var/cache/finals-image-builder"
        for value in (cache, workspace, tests, cleanup):
            self.assertIn(value, builder)
        self.assertLess(builder.index(cache), builder.index(tests))
        self.assertLess(builder.index(workspace), builder.index(tests))
        self.assertGreater(builder.index(cleanup), builder.index(tests))

    def test_failed_runtime_builders_are_prohibited(self):
        failed_builders = (
            "ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goacy3dojy463ubuy7ibn5w5qkl2wuaoclhof7q2k54wof2q",
            "ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goaccomxx6u2gtj4l75e7rmruf3ygrvp2sqy7e3m3ta6x3ia",
            "ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goacrkckfhkxhedqym7qggptmctcbcg5wrijqg7xhn6v7drq",
            "ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goacmb2j6gjpf63gphl7xhdc4izh4uakh6nlm5uw2pbwaguq",
            "ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goacz5owemazyq72tfqdriutkqsv4k4arluim2mt223sknfq",
            "ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goacdkqloulenb33an5dw6aj4fro4wbt7dplrt22v43vpyqa",
            "ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goacf74slght5m37vsh54tdyyfhm2ukebicmx5du2deywo3a",
            "ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goacoy7zvi6n667lc5cru636x3syhzpzuwmrhnlklybla5qa",
            "ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goac3z62q66d7h5qkfxwvnekd6x3scgdaldfyqpbeoklsuaa",
            "ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goaclkmig5434ou6hkigzf4qx5d3uvbofeiejfoy7fwljc2a",
            "ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goacubaccuijeotibtjqw7zt325dhg4fdw756gntikdnwgoa",
            "ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goacw7aqccrl4vifdxeiyukg3lygu6hnwyqhlrhxtjwwwagq",
        )
        variables = (ROOT / "terraform/environments/production/oci-runtime-images/variables.tf").read_text(encoding="utf-8")
        docs = "\n".join(
            (ROOT / f"terraform/environments/production/{root}/README.md").read_text(encoding="utf-8")
            for root in ("oci-runtime-builders", "oci-runtime-images")
        )
        for failed_builder in failed_builders:
            self.assertIn(failed_builder, variables)
            self.assertIn(failed_builder, docs)

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
        self.assertIn('checkers         = "${path.module}/../../../../checkers"', source)
        self.assertIn('hills            = "${path.module}/../../../../hills"', source)
        self.assertIn('team-access      = "${path.module}/../../../../team-access"', source)
        self.assertIn('"deployment/install.sh"', source)
        self.assertIn('"deployment/tests/run.sh"', source)
        self.assertIn('"hills/install.sh"', source)
        self.assertIn('"hills/tests/run.sh"', source)
        self.assertIn('"team-access/install.sh"', source)
        self.assertIn('"team-access/tests/run.sh"', source)
        self.assertIn("infra/archive infra/checkers infra/deployment infra/hills infra/images/runtime", package_script)
        self.assertIn("infra/secrets infra/team-access infra/volumes", package_script)

    def test_model_a_builder_tests_do_not_require_a_developer_path(self):
        source = (ROOT / "model-a-runtime/tests/test_model_a.py").read_text(encoding="utf-8")
        self.assertNotIn("/home/abu", source)
        self.assertEqual(source.count('@unittest.skipUnless(CHALLENGE.is_dir(), "challenge repository is not packaged")'), 2)

    def test_runtime_builder_preserves_every_source_executable(self):
        source = (ROOT / "terraform/environments/production/oci-runtime-builders/main.tf").read_text(encoding="utf-8")
        block = source[source.index("executable_files = toset(["):]
        block = block[:block.index("])")]
        declared = set(re.findall(r'"([^"]+)"', block))
        roots = {
            ROOT / "archive": "archive",
            ROOT / "checkers": "checkers",
            ROOT / "deployment": "deployment",
            ROOT / "hills": "hills",
            ROOT / "model-a-runtime": "model-a-runtime",
            ROOT / "images/runtime": "",
            ROOT / "platform": "platform",
            ROOT / "reconciler": "reconciler",
            ROOT / "secrets": "secret-bootstrap",
            ROOT / "team-access": "team-access",
            ROOT / "volumes": "volumes",
        }
        expected = set()
        for root, prefix in roots.items():
            for path in root.rglob("*"):
                if path.is_file() and path.stat().st_mode & stat.S_IXUSR:
                    expected.add("/".join(filter(None, (prefix, path.relative_to(root).as_posix()))))
        self.assertEqual(expected, declared)

    def test_builder_packages_include_the_archive_client(self):
        package_script = (ROOT / "terraform/scripts/package-oci-stack.sh").read_text(encoding="utf-8")
        self.assertIn("oci-gateway-builder) PATHS+=(infra/archive infra/images/router", package_script)
        self.assertIn("oci-runtime-builders) PATHS+=(infra/archive infra/checkers infra/deployment", package_script)

    def test_ingress_package_includes_router_cloud_init(self):
        package_script = (ROOT / "terraform/scripts/package-oci-stack.sh").read_text(encoding="utf-8")
        self.assertIn("oci-ingress) PATHS+=(infra/images/router)", package_script)

    def test_platform_package_includes_commissioning_sources(self):
        package_script = (ROOT / "terraform/scripts/package-oci-stack.sh").read_text(encoding="utf-8")
        for path in (
            "infra/platform/rootfs/usr/local/libexec/finals-platform/firewall",
            "infra/images/router/rootfs/usr/local/libexec/event-router/render_inventory.py",
        ):
            self.assertIn(path, package_script)

    def test_runtime_builder_replaces_for_par_and_user_data_changes(self):
        source = (ROOT / "terraform/environments/production/oci-runtime-builders/main.tf").read_text(encoding="utf-8")
        self.assertIn('resource "terraform_data" "builder_generation"', source)
        self.assertIn("oci_objectstorage_preauthrequest.source[each.key].id", source)
        self.assertIn("sha256(local.bootstrap_user_data[each.key])", source)
        self.assertIn("terraform_data.builder_generation[each.key]", source)

    def test_runtime_builder_metadata_limit_is_an_instance_precondition(self):
        source = (ROOT / "terraform/environments/production/oci-runtime-builders/main.tf").read_text(encoding="utf-8")
        self.assertNotIn('check "bootstrap_metadata_limit"', source)
        instance = source.split('resource "oci_core_instance" "builder"', 1)[1]
        self.assertIn("precondition {", instance)
        self.assertIn("length(local.bootstrap_user_data[each.key]) < 16384", instance)

    def test_runtime_builder_pins_reviewed_anvil(self):
        root = ROOT / "terraform/environments/production/oci-runtime-builders"
        variables = (root / "variables.tf").read_text(encoding="utf-8")
        example = (root / "terraform.tfvars.example").read_text(encoding="utf-8")
        revision = "c9176fef6aa87817d54d4c5254f77837f512929c"
        self.assertIn(f'var.anvil_revision == "{revision}"', variables)
        self.assertIn(f'anvil_revision      = "{revision}"', example)

    def test_runtime_canaries_are_private_bounded_and_fail_closed(self):
        root = ROOT / "terraform/environments/production/oci-runtime-canaries"
        source = (root / "main.tf").read_text(encoding="utf-8")
        script = (root / "canary-check.sh.tftpl").read_text(encoding="utf-8")
        cloud_init = (root / "canary-cloud-init.tftpl").read_text(encoding="utf-8")
        package = (ROOT / "terraform/scripts/package-oci-stack.sh").read_text(encoding="utf-8")
        self.assertIn("oci-runtime-canaries", package)
        self.assertIn("assign_public_ip       = false", source)
        self.assertNotIn("ssh_authorized_keys", source)
        self.assertNotIn('direction                 = "INGRESS"', source)
        self.assertIn('destination_type          = "SERVICE_CIDR_BLOCK"', source)
        self.assertIn("min = 443", source)
        self.assertIn("max = 443", source)
        self.assertNotIn('resource "oci_core_volume"', source)
        self.assertNotIn('resource "oci_core_route', source)
        self.assertNotIn('destination               = "0.0.0.0/0"', source)
        self.assertIn("/etc/runtime-image.json", script)
        self.assertIn("067_deployment_pipeline_events.sql", script)
        self.assertIn("deployment-orchestrator host-preflight", script)
        self.assertIn("runtime image package manifest hash mismatch", script)
        self.assertIn("10m", cloud_init)
        self.assertIn("mode: poweroff", cloud_init)

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
            self.assertIn('regex("^[A-Za-z0-9._/@-]+$", file.path)', source)

    def test_long_lived_compute_addresses_and_storage_are_guarded(self):
        storage = (ROOT / "terraform/modules/oci-storage/main.tf").read_text(encoding="utf-8")
        volume_start = storage.index('resource "oci_core_volume" "data"')
        attachment_start = storage.index('resource "oci_core_volume_attachment" "data"')
        policy_start = storage.index('resource "oci_core_volume_backup_policy"')
        self.assertIn("prevent_destroy = true", storage[volume_start:attachment_start])
        self.assertNotIn("prevent_destroy = true", storage[attachment_start:policy_start])
        self.assertIn("volume_id       = oci_core_volume.data[each.key].id", storage[attachment_start:policy_start])
        self.assertIn("offset_seconds    = 0", storage[policy_start:])
        self.assertIn('period            = "ONE_DAY"', storage[policy_start:])
        self.assertIn("retention_seconds = 604800", storage[policy_start:])
        for relative in (
            "terraform/modules/oci-compute-fleet/main.tf",
        ):
            source = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("prevent_destroy = true", source)

        platform = (ROOT / "terraform/modules/oci-platform/main.tf").read_text(encoding="utf-8")
        self.assertNotIn("prevent_destroy = true", platform)
        rotation = (ROOT / "terraform/OPERATIONS-ROTATION-WINDOW.md").read_text(encoding="utf-8")
        self.assertIn("only the stateless operations host", rotation)
        self.assertIn("must not change or destroy platform", rotation)

        gateway_rotation = (ROOT / "terraform/GATEWAY-ROTATION-WINDOW.md").read_text(encoding="utf-8")
        self.assertIn("primary and standby gateways", gateway_rotation)
        self.assertIn("reserved public addresses remain protected", gateway_rotation)
        self.assertIn("captures volume remains unchanged", gateway_rotation)

        ingress = (ROOT / "terraform/modules/oci-ingress/main.tf").read_text(encoding="utf-8")
        self.assertNotIn("prevent_destroy = true", ingress)
        self.assertIn('resource "oci_core_private_ip" "service_ingress"', ingress)
        self.assertIn('ip_address   = "10.60.250.120"', ingress)
        fleet = (ROOT / "terraform/modules/oci-compute-fleet/main.tf").read_text(encoding="utf-8")
        self.assertEqual(fleet.count("prevent_destroy = true"), 1)
        self.assertIn('resource "oci_core_volume" "production_data"', fleet)
        self.assertIn('resource "oci_core_volume_attachment" "production_data"', fleet)
        self.assertIn('resource "terraform_data" "production_generation"', fleet)
        self.assertEqual(fleet.count("replace_triggered_by = [terraform_data.production_generation]"), 4)
        self.assertIn("size_in_gbs         = 50", fleet)
        volume_start = fleet.index('resource "oci_core_volume" "production_data"')
        attachment_start = fleet.index('resource "oci_core_volume_attachment" "production_data"')
        workbench_start = fleet.index('resource "oci_core_instance" "workbench"')
        self.assertNotIn("prevent_destroy = true", fleet[volume_start:attachment_start])
        self.assertNotIn("prevent_destroy = true", fleet[attachment_start:workbench_start])

    def test_operations_relay_key_is_forced_and_role_scoped(self):
        ingress = (ROOT / "terraform/modules/oci-ingress/main.tf").read_text(encoding="utf-8")
        platform = (ROOT / "terraform/modules/oci-platform/main.tf").read_text(encoding="utf-8")
        variables = (ROOT / "terraform/modules/oci-platform/variables.tf").read_text(encoding="utf-8")
        router_cloud_init = (ROOT / "images/router/cloud-init.yaml").read_text(encoding="utf-8")
        forced = 'restrict,command=\\"/usr/local/sbin/finals-secret-relay-receive\\"'
        self.assertIn(forced, ingress)
        self.assertIn(forced, platform)
        self.assertIn('["platform", "control", "repository"]', platform)
        self.assertIn('__OPERATIONS_RELAY_AUTHORIZED_KEY__', router_cloud_init)
        self.assertIn('AuthorizedKeysFile .ssh/authorized_keys /etc/ssh/operations_relay_authorized_keys_%u', router_cloud_init)
        self.assertIn('contains(local.operations_relay_roles, role)', platform)
        ingress_metadata = ingress[ingress.index("metadata = {"):ingress.index("instance_options")]
        platform_metadata = platform[platform.index("metadata = {"):platform.index("instance_options")]
        self.assertIn("ssh_authorized_keys = trimspace(var.organizer_ssh_authorized_keys)", ingress_metadata)
        self.assertIn("ssh_authorized_keys = trimspace(var.organizer_ssh_authorized_keys)", platform_metadata)
        self.assertNotIn('ssh_authorized_keys = join(', ingress_metadata)
        self.assertNotIn('ssh_authorized_keys = join(', platform_metadata)
        self.assertIn("local.operations_relay_authorized_key", ingress_metadata)
        self.assertIn("local.cloud_init_by_role[each.key]", platform_metadata)
        self.assertIn('operations_relay_ssh_public_key', variables)
        self.assertIn('[A-Za-z0-9+/]{68}', variables)
        generated_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIE5+zFPUdhav0YumdESFR9fVhwTeCI43Rn43xyDp5J2a"
        self.assertRegex(generated_key, re.compile(r"^ssh-ed25519 [A-Za-z0-9+/]{68}$"))
        self.assertFalse(generated_key.endswith("="))

    def test_model_a_wrappers_are_fixed_and_pin_the_reviewed_router_files(self):
        platform = (ROOT / "terraform/modules/oci-platform/main.tf").read_text(encoding="utf-8")
        router = ROOT / "images/router/rootfs"
        public_ingress = router / "usr/local/sbin/event-router-public-ingress"
        self.assertIn(hashlib.sha256(public_ingress.read_bytes()).hexdigest(), platform)
        self.assertNotIn("      activate)", platform)
        self.assertEqual(platform.count('ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-production-keys ""'), 1)
        self.assertEqual(platform.count('ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-gateway-model-a ""'), 1)
        for wrapper in ("finals-commission-production-keys", "finals-commission-gateway-model-a"):
            self.assertNotIn(f"/usr/local/sbin/{wrapper} *", platform)
        self.assertIn("^production-(0[1-9]|1[0-5])$", platform)
        self.assertIn("SHA256:dfPMQE51IWgeI/TQvWs+zgCNU1dyZhpMBnQap/pmA0I", platform)
        self.assertIn('UserKnownHostsFile="$work/known_hosts"', platform)
        self.assertNotIn("base64encode(local.operations_commission_", platform)
        self.assertIn("| base64 -d | gzip -d |", platform)

    def test_weights_are_delivered_with_the_atomic_anvil_bundle(self):
        platform = (ROOT / "terraform/modules/oci-platform/main.tf").read_text(encoding="utf-8")
        deployer = (ROOT / "terraform/modules/oci-platform/scripts/deploy-anvil-artifact").read_text(encoding="utf-8")
        self.assertNotIn("weights-65-30-5", platform)
        self.assertIn("game.yaml", deployer)
        self.assertIn('[[ $target_game == "$expected_game_sha256" ]]', deployer)
        self.assertNotIn("feb6acb5d932594c8d4bc8b4370413d7c1b584877ba86d888c0a1f0ee8c90b49", deployer)
        self.assertIn('install -o root -g root -m 0644 "$work/game.yaml" "$project/game.yaml"', deployer)
        self.assertIn('install -o root -g root -m 0644 "$work/game.yaml.previous" "$project/game.yaml"', deployer)

    def test_operations_rotation_commissioning_is_fixed_and_hash_bound(self):
        platform = (ROOT / "terraform/modules/oci-platform/main.tf").read_text(encoding="utf-8")
        initializer = (ROOT / "volumes/initialize-volume.py").read_bytes()
        self.assertIn(hashlib.sha256(initializer).hexdigest(), platform)
        self.assertIn("operations_commission_script", platform)
        self.assertIn('resource "terraform_data" "operations_generation"', platform)
        self.assertIn('input = "bootstrap"', platform)
        self.assertIn('check "operations_commission_cloud_init"', platform)
        self.assertIn('local.cloud_init_by_role[role] == local.cloud_init_base_by_role[role]', platform)
        self.assertIn("StrictHostKeyChecking=yes", platform)
        self.assertIn("UserKnownHostsFile=/etc/finals-platform/operations/known_hosts", platform)
        platform_secret = "ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-secret platform anvil"
        platform_volume = "ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-volume platform volume-initialize"
        migration_061 = "ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-volume platform migration-061"
        platform_quiesce = "ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-volume platform platform-quiesce"
        anvil_restart = "ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-volume platform anvil-restart"
        self.assertEqual(platform.count(platform_secret), 0)
        self.assertEqual(platform.count(platform_volume), 0)
        self.assertNotIn("arena-schema", platform)
        self.assertEqual(platform.count(migration_061), 0)
        self.assertEqual(platform.count(platform_quiesce), 0)
        self.assertEqual(platform.count(anvil_restart), 1)
        self.assertNotIn("history-fix-135", platform)
        self.assertNotIn("weights-65-30-5", platform)
        self.assertNotIn("finals-commission-secret platform *", platform)
        self.assertNotIn("finals-commission-volume platform *", platform)
        self.assertNotIn("migration-061=complete", platform)
        self.assertIn("platform-quiesce=complete", platform)
        self.assertIn("systemctl disable --now anvil-finals-backup.timer", platform)
        self.assertIn("sha256sum --check --strict SHA256SUMS", platform)
        self.assertIn("umount /srv/anvil", platform)
        self.assertIn("systemctl restart anvil-finals.service", platform)
        self.assertIn('[[ $status == 200 ]]', platform)
        self.assertIn("anvil-restart=complete", platform)
        self.assertNotIn("anvil-audit-complete", platform)
        self.assertNotIn("admin-promote", platform)
        self.assertIn("operations_commission_secret_script", platform)
        self.assertNotIn("base64gzip(local.operations_commission_secret_script)", platform)
        self.assertNotIn("base64encode(local.operations_commission_", platform)
        self.assertIn("| gzip -d | install", platform)
        self.assertIn("75a1f6046817a6b83a214b3feeea9b7327a2ba0951bfedc20f811564ef6262e9", platform)
        checker_status = "ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-runtime-artifact control checker-status"
        self.assertEqual(platform.count(checker_status), 1)
        anvil_deploy = "ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-runtime-artifact platform anvil-deploy"
        self.assertEqual(platform.count(anvil_deploy), 1)
        self.assertIn("reconciler-access)", platform)
        self.assertIn("sudo -n chmod 0755 \\$h; sudo -n chmod 0644 \\$h/authorized_keys", platform)
        self.assertNotIn("operations_commission_action_bundle", platform)
        self.assertIn("base64gzip(local.operations_commission_script)", platform)
        self.assertNotIn("finals-commission-control-action", platform)
        reconciler = "ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-control-secret control-reconciler"
        checkers = "ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-control-secret control-checkers"
        self.assertEqual(platform.count(reconciler), 0)
        self.assertEqual(platform.count(checkers), 1)
        self.assertNotIn("finals-commission-control-secret *", platform)
        control_secret = platform[
            platform.index("operations_commission_control_secret_script"):
            platform.index("operations_commission_stage_central_script")
        ]
        self.assertIn("dd bs=65537 count=1", control_secret)
        self.assertIn("-le 65536", control_secret)
        self.assertIn("StrictHostKeyChecking=yes", control_secret)
        self.assertIn("-- ubuntu@10.60.201.20", control_secret)
        self.assertIn('case "$1" in', control_secret)
        self.assertIn("control-reconciler|control-checkers", control_secret)
        self.assertNotIn('"$@"', control_secret)
        self.assertNotIn("eval ", control_secret)
        self.assertNotIn("bash -c", control_secret)
        self.assertNotIn("finals-commission-platform-diagnostic", platform)
        firewall_wrapper = platform[
            platform.index("operations_commission_host_firewall_script"):
            platform.index("operations_commission_stage_central_script")
        ]
        self.assertIn(
            'filesha256("${path.module}/../../../platform/rootfs/usr/local/libexec/finals-platform/firewall")',
            firewall_wrapper,
        )
        self.assertIn("read -r host type key extra", firewall_wrapper)
        self.assertNotIn("IFS= read -r host type key extra", firewall_wrapper)
        targets = [
            "platform",
            "control",
            "repository",
            "mirror",
            "hill-01",
            "hill-02",
            "hill-03",
            *(f"production-{number:02d}" for number in range(1, 17)),
        ]
        for target in targets:
            fixed = f"ocarun ALL=(root) NOPASSWD: /usr/local/sbin/finals-commission-host-firewall {target}"
            self.assertEqual(platform.count(fixed), 1 if target.startswith(("hill-", "production-")) else 0, target)
        self.assertNotIn("finals-commission-host-firewall *", platform)
        self.assertIn("StrictHostKeyChecking=yes", firewall_wrapper)
        self.assertIn('UserKnownHostsFile="$work/known_hosts"', firewall_wrapper)
        self.assertIn("production-0[1-9]|production-1[0-6]", firewall_wrapper)
        self.assertIn('sudo -n /usr/bin/python3 \\"\\$temporary\\" --render', firewall_wrapper)
        self.assertNotIn('/bin/bash \\"\\$temporary\\" --render', firewall_wrapper)
        self.assertNotIn('sudo -n \\"\\$temporary\\" --render', firewall_wrapper)
        firewall = (ROOT / "platform/rootfs/usr/local/libexec/finals-platform/firewall").read_text()
        self.assertEqual(firewall.splitlines()[0], "#!/usr/bin/env python3")
        self.assertIn("nft --check --file -", firewall_wrapper)
        self.assertIn("systemctl restart finals-host-firewall.service", firewall_wrapper)
        self.assertIn("base64gzip(file(", firewall_wrapper)
        for forbidden in ('"$@"', "eval ", "bash -c", "StrictHostKeyChecking=accept-new"):
            self.assertNotIn(forbidden, firewall_wrapper)
        self.assertIn("base64gzip(local.operations_commission_host_firewall_script)", platform)
        self.assertIn("relay_authorized_keys_readable_roles", platform)
        self.assertNotIn("finals-commission-volume gateway-primary volume-initialize", platform)
        self.assertNotIn("finals-commission-volume gateway-standby volume-initialize", platform)
        self.assertIn("sudo install -D -m 0755 /dev/stdin /usr/local/sbin/finals-initialize-volume", platform)
        self.assertIn("sudo /opt/anvil/current/deployments/finals/preflight.sh", platform)
        self.assertIn("sudo systemctl is-active --quiet anvil-finals.service", platform)
        self.assertIn("--resolve finals.h7tex.com:443:10.60.200.10", platform)
        self.assertIn("COUNT(*) FILTER (WHERE name IS NULL OR checksum IS NULL)", platform)
        self.assertIn("systemctl start anvil-finals-backup.service", platform)
        self.assertIn("backup_after -gt $backup_before", platform)
        self.assertIn('test -s "$latest_backup/SHA256SUMS"', platform)
        self.assertIn('stat -c \"%u:%g:%a\" /srv/anvil/postgres) == 70:70:700', platform)
        self.assertIn('stat -c \"%u:%g:%a\" /srv/anvil/storage) == 0:0:700', platform)
        self.assertIn('stat -c \"%u:%g:%a\" /srv/anvil/backups) == 0:0:700', platform)
        self.assertNotIn("finals-commission-inventory", platform)
        self.assertIn("finals-commission-stage-central", platform)
        self.assertIn("finals-commission-clear-central", platform)
        self.assertIn("/run/finals-commissioning/central_id_ed25519", platform)
        self.assertIn("findmnt -n -o FSTYPE /run", platform)
        self.assertLess(platform.index("findmnt -n -o FSTYPE /run"), platform.index("mktemp -d /run/finals-central-stage"))
        self.assertLess(platform.index("mktemp -d /run/finals-central-stage"), platform.index("age --decrypt --identity"))
        self.assertIn("SHA256:cdz/qtyNUAL19bQV2ey1KgT3f6CCYXvML2CWI069bHA", platform)
        self.assertIn("SHA256:dfPMQE51IWgeI/TQvWs+zgCNU1dyZhpMBnQap/pmA0I", platform)
        self.assertIn('set(files) != {"ssh_private_key", "known_hosts"}', platform)
        self.assertNotIn("finals-commission-gateway-secret gateway-primary gateway-wireguard", platform)
        self.assertNotIn("finals-commission-gateway-secret gateway-standby gateway-reconciler", platform)
        self.assertIn('"sudo -n /usr/local/sbin/finals-install-secret-bundle $bundle"', platform)
        self.assertNotIn('exec ssh -F /dev/null -i /run/finals-commissioning/central_id_ed25519', platform)
        self.assertNotIn("finals-commission-gateway-authorizer gateway-primary", platform)
        self.assertNotIn("finals-commission-gateway-authorizer gateway-standby", platform)
        self.assertIn("operations_commission_gateway_role_script", platform)
        self.assertIn('length(base64encode(local.cloud_init_by_role["operations"]))', platform)
        self.assertIn('length(trimspace(var.organizer_ssh_authorized_keys)) < 31488', platform)
        self.assertNotIn("finals-commission-gateway-role gateway-primary", platform)
        self.assertNotIn("finals-commission-gateway-role gateway-standby", platform)
        self.assertNotIn("finals-commission-gateway-role-audit", platform)
        self.assertIn("address=10.60.250.10", platform)
        self.assertIn("expected=active", platform)
        self.assertIn("address=10.60.250.11", platform)
        self.assertIn("expected=standby", platform)
        self.assertIn('*) echo "unsupported fixed gateway target"', platform)
        self.assertIn("ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goac3ig6mf6qsd4ax7yacftguhu2qhvn3rjeili2qhmw2kjq", platform)
        self.assertIn("ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goacxgdwf25buf5ollmxlnw4e77g4y6coln6aqw2uvmovssq", platform)
        self.assertIn("ocid1.image.oc1.ap-hyderabad-1.aaaaaaaaoufvtqzgsc5kacdw6vlxmvre7mvozuwucuyknlm72mhrrojf5hsa", platform)
        self.assertIn("http://169.254.169.254/opc/v2/instance/", platform)
        self.assertIn("Authorization: Bearer Oracle", platform)
        self.assertIn("9e070c898e68e95f6329c8af6e8e62055673a2b8f9e6deb78e030a94f6b24aa0", platform)
        self.assertIn("sudo -n /usr/local/sbin/event-router-initialize", platform)
        self.assertEqual(platform.count("sudo -n /usr/local/sbin/event-router-initialize"), 1)
        self.assertIn("sudo -n systemctl is-active --quiet event-router.target", platform)

        self.assertIn("! -e /etc/finals-platform/role && ! -L /etc/finals-platform/role", platform)
        self.assertIn("sudo -n test ! -e /etc/event-router/role", platform)
        self.assertIn("sudo -n test -f /etc/event-router/role", platform)
        self.assertIn("sudo -n test ! -L /etc/event-router/role", platform)
        self.assertIn("sudo -n cat /etc/event-router/role", platform)
        self.assertNotIn("$(cat /etc/event-router/role)", platform)
        self.assertNotIn("router=$(cat /etc/event-router/role", platform)
        self.assertIn('echo "gateway role tuple is not authorized"', platform)
        self.assertNotIn("repair=remove-production", platform)
        self.assertNotIn("sudo rm -f -- /etc/finals-platform/role", platform)
        self.assertNotIn('install -D -m 0644 /dev/stdin /etc/event-router/role', platform)
        authorizer = 'sudo -n /usr/local/sbin/event-router-authorize-reconciler /etc/event-router/reconciler_authorized_key'
        self.assertEqual(platform.count(authorizer), 1)
        self.assertNotIn('test -f /etc/event-router/reconciler_authorized_key', platform)
        self.assertNotIn('test ! -L /etc/event-router/reconciler_authorized_key', platform)
        self.assertNotIn('event-router-authorize-reconciler "$1"', platform)
        self.assertNotIn('event-router-authorize-reconciler "$@"', platform)
        self.assertNotRegex(platform, r"sudo -n (?:/bin/)?(?:ba)?sh(?:\\s|$)")
        self.assertNotIn("peer-reconciler@$address", platform)
        standby = platform[platform.index("gateway-standby)"):platform.index("esac", platform.index("gateway-standby)"))]
        self.assertIn("sha256sum -c -", standby)
        self.assertNotIn("finals-volume@captures.service", standby)
        self.assertNotIn('"$@"', platform)

    def test_public_ingress_action_uses_fixed_compact_port_maps(self):
        platform = (ROOT / "terraform/modules/oci-platform/main.tf").read_text(encoding="utf-8")
        tool_path = ROOT / "images/router/rootfs/usr/local/sbin/event-router-public-ingress"
        tool = tool_path.read_text(encoding="utf-8")
        subprocess.run(["bash", "-n", str(tool_path)], check=True)
        wrapper = platform[
            platform.index("operations_commission_gateway_model_a_script"):
            platform.index("operations_commission_runtime_artifact_script")
        ]
        self.assertIn("public-ingress-open|public-ingress-status)", wrapper)
        self.assertIn(hashlib.sha256(tool_path.read_bytes()).hexdigest(), wrapper)
        self.assertIn("/usr/local/sbin/event-router-public-ingress $verb", wrapper)
        for value in ("hill_base=20000", "ssh_base=22000", "service_base=30000"):
            self.assertIn(value, tool)
        self.assertIn("for team in $(seq 1 15)", tool)
        self.assertIn("for hill in 1 2 3", tool)
        self.assertIn("for box in $(seq 1 16)", tool)
        self.assertIn("for service in $(seq 1 6)", tool)
        for name, count in (
            ("hill_dnat", 45),
            ("service_dnat", 96),
            ("ssh_dnat", 15),
            ("hill_snat", 45),
            ("ssh_snat", 15),
        ):
            self.assertIn(f"map_count {name}) -eq {count}", tool)
        self.assertIn("ip daddr 10.60.250.100 dnat ip to tcp dport map @hill_dnat", tool)
        self.assertIn("ip daddr 10.60.250.100 dnat ip to tcp dport map @service_dnat", tool)
        self.assertIn("ip daddr 10.60.250.100 dnat ip to tcp dport map @ssh_dnat", tool)
        self.assertIn("ct original proto-dst map @hill_snat", tool)
        self.assertIn("ct original proto-dst map @ssh_snat", tool)
        self.assertIn("ip daddr @released_production_addresses tcp dport @service_ports", tool)
        self.assertIn("ip daddr @production_addresses tcp dport 22", tool)
        self.assertNotIn("20011 :", tool)
        self.assertNotIn("30011 :", tool)

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

    def test_run_command_identity_is_compartment_scoped_and_self_only(self):
        root = ROOT / "terraform/environments/production/oci-foundation"
        source = (root / "main.tf").read_text(encoding="utf-8")
        outputs = (root / "outputs.tf").read_text(encoding="utf-8")
        self.assertIn('resource "oci_identity_dynamic_group" "finals_run_command"', source)
        self.assertIn("ALL {instance.compartment.id = '${oci_identity_compartment.finals.id}'}", source)
        self.assertIn('resource "oci_identity_policy" "finals_run_command"', source)
        self.assertIn("use instance-agent-command-execution-family", source)
        self.assertIn("where request.instance.id=target.instance.id", source)
        self.assertNotIn("manage all-resources", source)
        self.assertIn('output "run_command_dynamic_group_id"', outputs)
        self.assertIn('output "run_command_policy_id"', outputs)

    def test_private_oci_management_route_is_fixed_and_guarded(self):
        network = (ROOT / "terraform/modules/oci-network/main.tf").read_text(encoding="utf-8")
        self.assertIn('resource "oci_core_service_gateway" "management"', network)
        self.assertIn('values = ["All HYD Services In Oracle Services Network"]', network)
        self.assertEqual(network.count('destination_type  = "SERVICE_CIDR_BLOCK"'), 2)
        gateway = network[network.index('resource "oci_core_service_gateway" "management"'):]
        self.assertIn("prevent_destroy = true", gateway)
        self.assertIn("length(data.oci_core_services.regional.services) == 1", gateway)

    def test_router_public_game_ingress_has_three_fixed_tcp_ranges(self):
        network = (ROOT / "terraform/modules/oci-network/main.tf").read_text(encoding="utf-8")
        self.assertIn('resource "oci_core_network_security_group_security_rule" "router_public_game_ingress"', network)
        self.assertIn("for_each = local.router_public_game_ingress", network)
        self.assertIn("min         = 20011", network)
        self.assertIn("max         = 20159", network)
        self.assertIn("min         = 22001", network)
        self.assertIn("max         = 22016", network)
        self.assertIn("min         = 30011", network)
        self.assertIn("max         = 30166", network)
        resource = network[network.index('resource "oci_core_network_security_group_security_rule" "router_public_game_ingress"'):]
        self.assertIn('source                    = "0.0.0.0/0"', resource)
        self.assertIn('protocol                  = "6"', resource)
        self.assertIn("stateless                 = true", resource)

    def test_fleet_can_expand_without_targeting_resources(self):
        module = ROOT / "terraform/modules/oci-compute-fleet"
        source = (module / "main.tf").read_text(encoding="utf-8")
        variables = (module / "variables.tf").read_text(encoding="utf-8")
        root = (ROOT / "terraform/environments/production/oci-fleet/main.tf").read_text(encoding="utf-8")
        self.assertIn("for team in var.production_numbers", source)
        self.assertIn("for team in var.workbench_numbers", source)
        self.assertIn('team == 16 ? "admin-workbench" : team == 17 ? "spare-workbench"', source)
        self.assertIn("each.value.team > 15 || trimspace", source)
        self.assertIn('variable "production_numbers"', variables)
        self.assertIn('variable "workbench_numbers"', variables)
        self.assertIn("number >= 1 && number <= 16", variables)
        self.assertIn("number >= 1 && number <= 17", variables)
        self.assertIn("Every enabled workbench requires", source)
        self.assertIn('variable "reference_production_image_id"', variables)
        self.assertIn("each.value.team == 16 && var.reference_production_image_id != null", source)
        self.assertIn("reference_production_image_id      = var.reference_production_image_id", root)
        staging = source[source.index('resource "oci_core_private_ip" "staging"'):source.index('resource "oci_core_volume" "production_data"')]
        self.assertNotIn("prevent_destroy = true", staging)
        self.assertNotIn("ignore_changes", staging)
        self.assertIn("vnic_id      = data.oci_core_vnic_attachments.production[each.key].vnic_attachments[0].vnic_id", staging)
        self.assertIn("production_numbers                 = var.production_numbers", root)
        self.assertIn("workbench_numbers                  = var.workbench_numbers", root)

    def test_support_workbenches_have_isolated_fixed_subnets(self):
        network = (ROOT / "terraform/modules/oci-network/main.tf").read_text(encoding="utf-8")
        self.assertIn('cidr         = "10.61.16.0/24"', network)
        self.assertIn('display_name = "admin-workbench"', network)
        self.assertIn('cidr         = "10.61.17.0/24"', network)
        self.assertIn('display_name = "spare-workbench"', network)
        self.assertIn("local.support_workbench_subnets", network)

    def test_obsolete_gateway_image_and_plan_are_prohibited(self):
        failed_builders = (
            "ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goaceebogxa47rg74d6izhqorb2dgnjjlfsv7gupjwbevyva",
            "ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goacvwoxwqstnmj6bwirfuxxan45gpqbbuzt7fw5if2zjfbq",
            "ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goacptf4hmhhjlqee2ucownqcd6amop4lye7j3m3z27z2uqq",
            "ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goac4ydsjdkbgos2khrmbkfcaof3auparnd66bkinjgnkgiq",
            "ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goaccuukzrd6z3cb5mkyrxfuxep4dgdhb2hfvseo25l7fizq",
            "ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goackghwgzi5kmx47jm27ifbvo4lamzmyhltr6gfikylkllq",
            "ocid1.instance.oc1.ap-hyderabad-1.anuhsljrgek2goackhel3yztpwcpfg2dygvuo3f3tzmf2aoayodhlug5scqq",
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
